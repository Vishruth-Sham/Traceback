"""A practical recurring wrapper around `processor.runner.run_once`.

The contract and `docs/local-models.md` are explicit that `run_once`
processes at most one pending capture per invocation and that there is "no
internal polling loop; the coordinator drives repeated invocation." This
module is that repeated invocation, sized for a single sole-user MacBook:
one foreground/background Python process, one capture claimed at a time
(matching the "one active model job" rule), a fixed poll interval between
wakes, and no new persistent state beyond the existing REST-tracked capture
processing rows — this module itself is stateless and safely restartable at
any point. It never talks to anything but the configured loopback REST API
(itself never falling back to a cloud model), and an unexpected exception
from one wake is logged and the loop continues rather than crashing the
whole scheduler over one bad capture.

CLI: `python -m processor.scheduler` runs in the foreground until SIGINT/
SIGTERM; see `scripts/processor_service.py` for a start/stop/status wrapper
that runs it detached in the background with a PID file, the way
`scripts/local_db.py` manages the local PostgreSQL cluster.
"""

import logging
import signal
import time
from types import FrameType
from typing import Callable

from pydantic import Field

from processor.config import ProcessorSettings
from processor.runner import RestClient, RunnerConfig, run_once

logger = logging.getLogger("processor.scheduler")


class SchedulerConfig(RunnerConfig):
    """`RunnerConfig` plus the one extra knob the scheduler needs."""

    poll_interval_s: float = Field(default=15.0, ge=1, le=3600)
    # Used instead while the backend reports voice commands enabled, so a spoken command is picked up promptly.
    voice_poll_interval_s: float = Field(default=3.0, ge=1, le=3600)


class StopSignal:
    """A flag a signal handler sets; `run_forever` checks it between wakes.

    Kept separate from OS signal delivery so `run_forever`'s stop condition
    is a plain callable a test can drive deterministically without sending
    real signals or depending on wall-clock timing.
    """

    def __init__(self) -> None:
        self.requested = False

    def handler(self, signum: int, frame: FrameType | None) -> None:
        logger.info("received signal %s; stopping after the current cycle", signum)
        self.requested = True

    def __call__(self) -> bool:
        return self.requested


def next_interval(rest: RestClient, config: SchedulerConfig) -> float:
    """3 s while voice commands are enabled, else the idle interval; any failure keeps the safe default."""
    capabilities = getattr(rest, "capabilities", None)
    if capabilities is None:
        return config.poll_interval_s
    try:
        enabled = bool(capabilities()["voice_commands"]["enabled"])
    except Exception:  # noqa: BLE001 - polling cadence must never take the scheduler down
        return config.poll_interval_s
    return min(config.poll_interval_s, config.voice_poll_interval_s) if enabled else config.poll_interval_s


def run_forever(
    *,
    rest: RestClient,
    config: SchedulerConfig,
    processor_settings: ProcessorSettings | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    sleep: Callable[[float], None] = time.sleep,
    max_iterations: int | None = None,
) -> int:
    """Call `run_once` repeatedly, one capture per wake, until told to stop.

    Checks `should_stop()` before claiming and again before sleeping, so a
    stop request lands within one in-flight `run_once` call, not after a
    full extra poll interval. `max_iterations` bounds the loop for tests and
    for anyone who wants a bounded manual run; it is not used by the CLI
    (which runs until signaled). A crash inside `run_once` itself is caught,
    logged, and does not stop the loop — a single malformed capture or a
    transient bug must not take down unattended processing of everything
    after it, though it also never invents a "fixed" state: the capture in
    question keeps whatever state `run_once`'s own failure handling already
    left it in.
    """
    iterations = 0
    while not should_stop():
        if max_iterations is not None and iterations >= max_iterations:
            break
        try:
            result = run_once(rest=rest, config=config, processor_settings=processor_settings)
        except Exception:
            logger.exception("run_once raised unexpectedly; continuing after the next poll interval")
            result = None
        iterations += 1
        logger.info("iteration %d: %s", iterations, result or {"status": "idle"})
        if should_stop():
            break
        if max_iterations is not None and iterations >= max_iterations:
            break
        sleep(next_interval(rest, config))
    return iterations


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    config = SchedulerConfig()
    rest = RestClient(config)
    stop = StopSignal()
    signal.signal(signal.SIGTERM, stop.handler)
    signal.signal(signal.SIGINT, stop.handler)
    logger.info(
        "processor scheduler starting: poll_interval_s=%s api_base_url=%s lease_seconds=%s",
        config.poll_interval_s,
        config.api_base_url,
        config.lease_seconds,
    )
    iterations = run_forever(rest=rest, config=config, should_stop=stop)
    logger.info("processor scheduler stopping after %d iteration(s)", iterations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
