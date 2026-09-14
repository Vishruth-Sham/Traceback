"""Unit tests for processor.scheduler.run_forever and StopSignal.

No real time passes and no network is touched: `sleep` is a counting stub
and the REST client is the same `FakeRestClient` pattern used in
test_processor_runner.py. See tests/test_processor_service.py for a real
subprocess lifecycle (start/stop/status) test.
"""
import processor.scheduler as scheduler_module
from processor.scheduler import SchedulerConfig, StopSignal, run_forever
from tests.test_processor_runner import FakeRestClient, _typed_capture


def _config(**overrides) -> SchedulerConfig:
    return SchedulerConfig(api_base_url="http://127.0.0.1:0", api_token="unused-in-fake-client-tests", **overrides)


class CountingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def test_stop_signal_starts_false_and_flips_on_handler_call():
    stop = StopSignal()
    assert stop() is False
    stop.handler(15, None)  # SIGTERM's numeric value, but any int/frame stands in here
    assert stop() is True


def test_run_forever_stops_immediately_when_already_requested():
    fake = FakeRestClient(capture=_typed_capture())
    sleep = CountingSleep()
    iterations = run_forever(rest=fake, config=_config(), should_stop=lambda: True, sleep=sleep)
    assert iterations == 0
    assert sleep.calls == []
    assert fake.claimed == []


def test_run_forever_respects_max_iterations_and_sleeps_between_not_after():
    fake = FakeRestClient(capture=None)  # always idle: list_pending_captures returns []
    sleep = CountingSleep()
    iterations = run_forever(rest=fake, config=_config(poll_interval_s=5), sleep=sleep, max_iterations=3)
    assert iterations == 3
    # Sleeps between iterations, not after the last one.
    assert sleep.calls == [5, 5]


def test_run_forever_processes_one_capture_then_idles_without_duplicating(monkeypatch):
    import processor.runner as runner_module

    monkeypatch.setattr(
        runner_module,
        "interpret",
        lambda text, context, settings=None: {
            "items": [{"item_type": "note", "title": "x", "content_md": text, "category_id": None, "due_date": None, "due_time": None, "due_timezone": None}]
        },
    )

    class ResolvesAfterOneClaim(FakeRestClient):
        def list_pending_captures(self, limit=1):
            # Once claimed, the real backend would stop returning this capture
            # as "pending"; simulate that here so a second wake sees nothing.
            return [] if self.claimed else super().list_pending_captures(limit=limit)

    fake = ResolvesAfterOneClaim(capture=_typed_capture())
    sleep = CountingSleep()
    iterations = run_forever(rest=fake, config=_config(poll_interval_s=1), sleep=sleep, max_iterations=3)
    assert iterations == 3
    assert len(fake.claimed) == 1
    assert len(fake.submitted) == 1  # not resubmitted on later idle wakes


def test_run_forever_survives_an_unexpected_crash_in_run_once(monkeypatch):
    calls = {"n": 0}

    def flaky_run_once(*, rest, config, processor_settings=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom - unexpected bug")
        return {"status": "idle"}

    monkeypatch.setattr(scheduler_module, "run_once", flaky_run_once)
    fake = FakeRestClient(capture=None)
    sleep = CountingSleep()
    iterations = run_forever(rest=fake, config=_config(poll_interval_s=2), sleep=sleep, max_iterations=2)
    assert iterations == 2  # the crash on iteration 1 did not stop the loop
    assert calls["n"] == 2
    assert sleep.calls == [2]


def test_run_forever_stops_before_sleeping_once_flagged_mid_run(monkeypatch):
    stop = StopSignal()
    call_count = {"n": 0}

    def stopping_run_once(*, rest, config, processor_settings=None):
        call_count["n"] += 1
        if call_count["n"] == 2:
            stop.requested = True
        return {"status": "idle"}

    monkeypatch.setattr(scheduler_module, "run_once", stopping_run_once)
    fake = FakeRestClient(capture=None)
    sleep = CountingSleep()
    iterations = run_forever(rest=fake, config=_config(poll_interval_s=1), should_stop=stop, sleep=sleep)
    assert iterations == 2
    # No sleep after the iteration that set the stop flag.
    assert sleep.calls == [1]


def test_scheduler_config_still_rejects_non_loopback_backend_url():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="loopback"):
        SchedulerConfig(api_base_url="https://example.com", api_token="unused-test-token")


def test_scheduler_config_poll_interval_is_bounded():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _config(poll_interval_s=0)
    with pytest.raises(ValidationError):
        _config(poll_interval_s=999999)
