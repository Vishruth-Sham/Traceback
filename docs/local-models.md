# Local processor models: transcription and interpretation

Status reviewed: 2026-09-26. The adapters, bounded REST runner, scheduler, task quick add, and reviewed note-placement proposal path are implemented. The recorded machine/runtime measurements remain historical evidence from 2026-09-14. Representative personal-content quality was not benchmarked, and voice/STT is currently deprioritized rather than treated as the next milestone.

Status: `processor/` implements the two synchronous adapters required by
[processor-contract.md](processor-contract.md) — `transcribe` (whisper.cpp)
and `interpret` (loopback Ollama `qwen3.5:4b`) — with no database writes, no
cloud inference, and no microphone recording. This document records the
actual installed runtime, exact import/signatures for integration, and
measured (not benchmarked-for-quality) evidence from this machine. A later
pass (2026-09-14) fixed a durability gap in `processor/runner.py`'s
`RestClient` — see "REST runner" below — and added four tests; no adapter
behavior (`transcribe`/`interpret`) changed. A further pass (same day) added
the recurring scheduler (`processor/scheduler.py`,
`scripts/processor_service.py`), a reproducible latency/memory benchmark
script (`scripts/model_benchmark.py`), and end-to-end PostgreSQL-backed
tests covering staleness/lease/generation-conflict safety and failure
preservation (`tests/test_processor_end_to_end.py`) — see the relevant
sections below.

## Machine this was validated on

- Base M5 MacBook Air, macOS 26.6.2 (Darwin 25.6.0), 16GB unified memory (`sysctl hw.memsize`).
- `whisper.cpp` 1.9.4 installed via `brew install whisper-cpp` (binary: `whisper-cli`, Homebrew Cellar — not inside this repo).
- `ollama` 0.30.11, already installed and running as a user service, bound to `127.0.0.1:11434` only (verified with `lsof -iTCP -sTCP:LISTEN`).
- Whisper `small` multilingual weights: `ggml-small.bin`, SHA-256 `1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b`, 465MB, downloaded to `~/.cache/whisper-cpp/ggml-small.bin` (outside Git; path is user-overridable, see Configuration below).
- `qwen3.5:4b`, pulled via `ollama pull qwen3.5:4b`: digest `2a654d98e6fb`, format `gguf`, quantization `Q4_K_M`, 3.4GB on disk, 4.7B parameters, context length up to 262144 (adapter caps this — see below). `ollama show qwen3.5:4b` reports capabilities `completion, vision, tools, thinking` and uses a custom `qwen3.5` renderer/parser (not a plain chat template — see Known limitation below).

Both downloads were explicitly authorized for this work. Approximate disk cost before downloading: ~488MB (whisper small) + ~3.4GB (qwen3.5:4b Q4_K_M) ≈ 3.9GB; 337GB was free on this machine beforehand. `scripts/model_setup.py` prints these estimates and only downloads with `--install`.

## Integration: exact import and signatures

```python
from pathlib import Path
from processor import transcribe, interpret
from processor.errors import ModelUnavailableError, TranscriptionError, InterpretationError

transcript: str = transcribe(audio_path: Path) -> str
proposal: dict = interpret(text: str, context: dict) -> dict
```

- `processor.transcription.transcribe(audio_path: Path, *, settings: ProcessorSettings | None = None) -> str`
  Shells out to `whisper-cli`. Raises `ModelUnavailableError` if the binary or
  model weights are missing, `TranscriptionError` for a missing/empty/oversized
  input file, a timeout, or a nonzero exit.
- `processor.interpretation.interpret(text: str, context: dict, *, settings: ProcessorSettings | None = None) -> dict`
  Calls Ollama's `/api/chat` over loopback HTTP only (stdlib `urllib`, no new
  dependency). Raises `ModelUnavailableError` if Ollama cannot be reached and
  `InterpretationError` if no schema-valid proposal is produced within the
  bounded retry budget (default 2 attempts) or the input text is empty.
  Returns a plain `dict` already matching the envelope in
  processor-contract.md, e.g.:

  ```json
  {"items": [{"item_type": "task", "title": "Finish the capture endpoint", "content_md": "...", "category_id": null, "project_id": null, "folder_id": null, "due_date": null, "due_time": null, "due_timezone": null}]}
  ```

- `context` expected keys (all optional, used for grounding and validation):
  `captured_at`, `source_timezone`, `source_date`, `categories` — a list of
  `{"id": <uuid>, "slug": ..., "name": ...}` (or plain UUID strings) — and,
  since 2026-09-14, `projects`/`folders` — each a list of `{"id": <uuid>,
  "title": ...}` for existing project/folder items, so the model can place a
  proposed item directly inside one it recognizes by name (e.g. "For the
  Apartment Move project, ..."). Any `category_id`/`project_id`/`folder_id`
  the model proposes that is not in the corresponding supplied list is
  coerced to `null` before returning — enforced in code, not merely
  requested by prompt — and at most one of the three may be set on a
  proposed item (`processor/schemas.py` rejects both `project_id` and
  `folder_id` together, and silently drops a redundant `category_id` when
  either is set, since the backend derives category from the container).
  `processor/runner.py` fetches `projects`/`folders` via `GET
  /items?item_type=project|folder` (bounded to 50 each) and, after
  `interpret()` returns, resolves the chosen container's current version
  (the model only knows its id) before submitting the interpretation —
  see "REST runner" below.
- Both functions are synchronous, make no database writes, and never execute
  SQL/shell from model output. `interpret` never receives or returns
  completion/archive/delete fields; `processor/schemas.py` rejects them.

## Dependencies

No new third-party packages were added to `pyproject.toml` (a coordinator-owned
file) — both adapters use only the Python standard library (`subprocess`,
`urllib.request`) plus `pydantic`, which the backend already depends on.
`processor/` imports nothing from `backend/`; the task deadline validation
rules in `processor/schemas.py` are a self-contained reimplementation of the
same rules in `backend/schemas.py` (`TaskFields`), so a worker of this
contract does not need to depend on the coordinator's files.

## Configuration

`processor/config.py` (`ProcessorSettings`, `pydantic-settings`) reads
`TRACEBACK_PROCESSOR_*` environment variables or `.env`, so the coordinator's
integration can override without editing this worker's files. Defaults used
for validation on this machine:

| Setting | Default | Notes |
| --- | --- | --- |
| `whisper_binary` | resolved via `shutil.which("whisper-cli")` | |
| `whisper_model_path` | `~/.cache/whisper-cpp/ggml-small.bin` | outside Git |
| `whisper_language` | `auto` | multilingual small model |
| `whisper_timeout_s` | 180 | |
| `whisper_max_audio_bytes` | 100MB | |
| `ollama_base_url` | `http://127.0.0.1:11434` | loopback only |
| `ollama_model` | `qwen3.5:4b` | |
| `ollama_num_ctx` | 8192 | within the plan's 4K–8K context budget |
| `ollama_max_output_tokens` | 700 | bounded output |
| `ollama_max_input_chars` | 12000 | bounds text sent to the model (~3–4K tokens), leaving room for the prompt/schema/output inside `num_ctx` |
| `ollama_temperature` | 0.0 | deterministic extraction |
| `ollama_retry_attempts` | 2 | bounded rounds for malformed JSON, not tool-calling rounds |
| `ollama_think` | `false` | non-thinking mode requested (see limitation below) |
| `max_proposal_items` | 10 | matches the contract's cap |

## Known runtime limitation: Ollama's `format` JSON-schema mode does not constrain this model

Ollama supports passing a full JSON Schema as `format` for grammar-constrained
structured output. Tested directly against this installed `qwen3.5:4b`
(`curl http://127.0.0.1:11434/api/chat` with `format: <schema>`), the model
ignored the schema entirely and emitted unrelated keys (e.g. `action`,
`target`, `deadline`, or `id`/`type`/`deleted_at`) regardless of schema
shape (nested `$ref` or flattened). This model ships with a custom
`RENDERER qwen3.5` / `PARSER qwen3.5` in its Modelfile rather than the classic
Go chat template, and grammar-constrained decoding does not appear to compose
with that parser in this Ollama build (0.30.11).

Workaround implemented in `processor/interpretation.py`: the adapter sends
`format: "json"` (Ollama's basic syntactic-JSON mode, confirmed to work) plus
an explicit key-by-key shape written into the system prompt, then validates
the result against `processor/schemas.py` and retries with a correction
message (bounded by `ollama_retry_attempts`) on a schema violation. This was
reliable across all interpretation calls made during this validation
(including the automated test suite's live-model test). Report this to the
coordinator if a different Ollama/model version is later adopted — worth
re-testing whether schema-constrained `format` starts working, since it would
remove the need for the retry loop.

## Incident (2026-09-14, part 2): specific-time deadlines could exhaust the retry budget

After the process-staleness incident below was fixed, a real report — typing
"email sarah 5pm tomorrow" into Tasks quick-add — still produced "could not
understand this — original text is safe". Reproduced directly against
`processor.interpretation.interpret` with the real model: for a
specific-time phrase, `qwen3.5:4b` sometimes folds the resolved date/time
into `due_date` as a full ISO datetime instead of the three separate fields,
and/or writes `due_timezone` as a raw UTC offset instead of the IANA name,
e.g.:

```json
{"due_date": "2026-09-15T17:00:41+05:30", "due_time": "17:00:41", "due_timezone": "+05:30"}
```

`due_date` is a Pydantic `date` field, so this fails
`date_from_datetime_inexact` — and because that is a *field-level* error,
Pydantic never reaches `ProposedItem`'s `due_timezone` IANA check (a
model-level `mode="after"` validator), so the correction message sent back
to the model only ever mentioned the `due_date` problem. The model's retry
attempt fixed the surface shape of `due_date` but kept the same invalid
`due_timezone`, and after `ollama_retry_attempts` (2) the adapter gave up.
Not a process-staleness issue this time — a genuine model output-shape edge
case, reproducible directly at the Python level without going through
REST/UI at all.

**Fix** in `processor/interpretation.py`: `_parse_proposal_json` now repairs
both shapes *before* validation, so no retry is spent on a mistake the model
doesn't reliably self-correct from a terse Pydantic error — a `due_date`
containing `"T"` is truncated to its date portion; a `due_timezone` that is
a raw UTC offset (`+05:30`/`-08:00`) or `"Z"` is replaced with the capture's
own `source_timezone`; if no `source_timezone` is available to substitute,
the specific time is dropped entirely (`due_time`/`due_timezone` both set
`null`) rather than submitting an invalid combination. The system prompt
also gained explicit format rules (`due_date` must be exactly `YYYY-MM-DD`,
`due_timezone` must be copied exactly from `source_timezone`, never an
offset) to reduce how often the repair is needed at all, though the repair
is what makes this reliable regardless of whether the model follows the
prompt. Verified: 3/3 direct real-model calls with "email sarah 5pm
tomorrow" now succeed on the first attempt with `due_date: "2026-09-15"`,
`due_time: "17:00:00"`, `due_timezone: "Asia/Kolkata"`; retrying the exact
capture that had failed in production (`8506adf6-...`, `error_code:
InterpretationError`, "Ollama did not return a schema-valid proposal within
2 attempts") through the fixed, restarted pipeline resolved into one task,
archived afterward. New regression coverage in
`tests/test_processor_interpretation.py`: `test_parse_repairs_datetime_shaped_due_date_and_offset_timezone`,
`test_parse_repairs_z_suffixed_due_timezone`,
`test_parse_drops_unresolvable_offset_timezone_without_source_timezone`,
`test_interpret_succeeds_despite_malformed_due_date_from_model` (stubbed,
deterministic), and
`test_real_ollama_specific_time_deadline_does_not_exhaust_retries` (gated on
a live model, runs the literal reported phrase three times against the real
`qwen3.5:4b`).

## Measured evidence (synthetic fixtures only — not a quality benchmark)

Run `python3 scripts/model_smoke.py` after `python3 scripts/model_setup.py` to
reproduce. It synthesizes speech with macOS `say` + `afconvert` (no
microphone) and uses one fixed synthetic typed-text capture; it does **not**
evaluate transcription/interpretation accuracy against representative
personal recordings, which the contract explicitly reserves for later, real
usage. Sample run on this machine:

- Whisper `small`, warm (shader cache already compiled): ~0.5–0.8s to
  transcribe a ~5s synthetic utterance; child process peak RSS ~790MB
  (`resource.getrusage(RUSAGE_CHILDREN).ru_maxrss`).
- Whisper `small`, cold (first invocation on a fresh machine, before Metal
  shader compilation is cached): ~14.5s for the same clip — a one-time cost,
  not per-call once warm.
- `qwen3.5:4b` interpretation via loopback Ollama: ~2.5–5s per call for a
  one- or two-sentence capture, `ollama ps` reports the model resident at
  ~3.3GB, 100% GPU (Metal), with `CONTEXT 8192` confirming the configured
  `num_ctx` took effect.
- Code inspection and runtime observation confirm that the adapters call only
  `whisper-cli` (a local process) and Ollama on `127.0.0.1:11434`. A complete
  network-disabled run has not yet been performed, so offline operation remains
  to be verified explicitly.
- The model correctly produced `item_type`/`title`/`content_md` shaped output
  in every observed call, but its extraction/date-grounding accuracy varies
  (e.g. it sometimes left a "tomorrow" due date null instead of resolving it
  against `captured_at`, and in one exploratory probe outside the adapter's
  retry-validated path it invented a due date). The adapter's job is to
  reject anything schema-invalid and drop unknown categories to Inbox, which
  it does; it does not guarantee extraction correctness. Full personal
  recording/content quality has not been benchmarked, per the contract.

## Reproducible latency/memory benchmark (2026-09-14)

`scripts/model_benchmark.py` extends the single-shot smoke check above with
repeated iterations and min/mean/max/cold-vs-warm statistics. It downloads
nothing and exits early with a precise reason if a runtime/model/synthesis
tool is missing:

```sh
.venv/bin/python scripts/model_benchmark.py --whisper-iterations 4 --ollama-iterations 4
```

Measured on this machine (same hardware as "Machine this was validated on"
above; both models were already resident/shader-cached from a prior run
this session, so the "cold" figures below are *not* a fresh-machine cold
start — see the true one-time cold-cache figure, ~14.5s, already recorded
above):

- Whisper `small`, 4 transcription calls of the same ~5s synthetic
  utterance: 0.529–0.539s each (mean 0.535s), child process peak RSS
  ~842MB. Output was stable and reasonable across calls ("Buy milk tomorrow
  and finish the capture and point by 5pm for traceback." — whisper's own
  transcription of "endpoint", not an adapter bug).
- `qwen3.5:4b` via loopback Ollama, 4 interpretation calls of the same fixed
  sentence: first call 2.545s, next three 1.919–1.922s (warm mean 1.921s);
  `ollama ps` reported the model resident at 3.3GB, 100% GPU, `CONTEXT
  8192` (matching the configured `ollama_num_ctx`). All four calls produced
  the same schema-valid single-`note` proposal.

These numbers characterize the installed runtimes' speed/memory footprint
on this machine for short inputs; they are not a transcription/
interpretation quality benchmark (no representative personal-recording
fixture exists to benchmark against — see the contract and "What is not
covered here" below) and will differ on other hardware, input lengths, or
Ollama/whisper.cpp versions. Re-run the script to reproduce or update these
numbers rather than trusting this snapshot indefinitely.

## Acceptance

`tests/test_processor_schemas.py`, `tests/test_processor_transcription.py`,
`tests/test_processor_interpretation.py` (23 tests) all pass on this machine,
mixing pure validation unit tests, stubbed-adapter unit tests (retry logic,
unknown-category coercion, unreachable-Ollama handling — run with no live
model required), and two runtime smoke tests gated by
`pytest.mark.skipif` that report a precise skip reason
(e.g. "whisper-cli binary or model weights ... not installed" or "Ollama
loopback service or model qwen3.5:4b not available") instead of failing when
a runtime dependency is absent. On this machine both gated tests ran for
real, against the installed whisper.cpp binary/weights and the live
`qwen3.5:4b` model, and passed. At the time this document was first written,
`python3 -m pytest tests/ -q` (the full suite before the MCP adapter and this
document's own later runner fix existed) passed 54 tests total with no
regressions to the coordinator's backend tests; the full suite now includes
the coordinator's `traceback_mcp` adapter tests as well (see
`docs/mcp-adapter.md`) and the runner additions below — see that document or
re-run `pytest -q` for the current total rather than treating either count
here as current.

## REST runner (`processor/runner.py`)

At the coordinator's request, `processor/runner.py` adds a thin REST-only
integration on top of the two adapters: `python -m processor.runner` claims
one pending capture, transcribes/interprets it, and submits one atomic
interpretation, using only authenticated loopback HTTP (stdlib `urllib`, no
new dependency, no `backend`/database import).

- Config is env-only (`RunnerConfig`, `pydantic-settings`, prefix
  `TRACEBACK_PROCESSOR_`): `TRACEBACK_PROCESSOR_API_BASE_URL` (default
  `http://127.0.0.1:8000`), and an API token from
  `TRACEBACK_PROCESSOR_API_TOKEN` or (falling back, for convenience with the
  existing `.env`) `TRACEBACK_API_TOKEN`. The token is never accepted as a
  CLI argument and is never logged; `RestError`/log messages only surface a
  domain error's `code`/`message`/`details`, never raw response bodies or
  capture/transcript text.
- Flow: `GET /api/v1/captures?state=pending&limit=1` → `POST
  .../claim` (bounded `lease_seconds`) → `GET /api/v1/captures/{id}` for the
  full record, plus `GET /api/v1/categories`, `GET /items?item_type=project`,
  and `GET /items?item_type=folder` (bounded to 50 each) for interpretation
  context → for `typed`, use `raw_text` directly; for `audio`, stream
  `GET /api/v1/assets/{asset_id}/content` into a private
  `tempfile.TemporaryDirectory` (never a client-supplied path) and transcribe
  it, deleting the file when the `with` block exits → `interpret(...)` →
  `POST .../interpretations` with `mode="processor"`, the exact claimed
  `expected_generation`/`lease_token`, and one `"kind": "create"` operation
  per proposal entry, built by `_build_create_operation` (since 2026-09-14):
  if the proposed item names a `project_id`/`folder_id` still present in the
  freshly-fetched list, that becomes the operation's `project_id`/`folder_id`
  plus its current `project_expected_version`/`folder_expected_version`
  (looked up from the same list — the model only ever sees the id, never a
  version) and `item.category_id` is forced `null`; otherwise the item's
  `category_id` passes through unchanged. A container the model named that
  is no longer in the list it was given (e.g. archived between context-build
  and response) falls back to no placement rather than guessing a version,
  matching `interpret()`'s own unknown-id-to-null rule. Other source types
  (`file`, `url`, `import`) are explicitly rejected as unsupported by this
  runner rather than silently mishandled.
- On any adapter or REST failure after a successful claim, it calls `POST
  .../fail` with the same generation/lease — but only if
  `lease_expires_at` (returned by `/claim`) is still in the future; if the
  lease already expired (e.g. a slow model call), it logs and does nothing
  further, since a stale generation/lease report would itself be rejected by
  the backend and there is nothing more this runner can safely do. A claim
  conflict (already claimed/resolved) is reported as `status:
  "claim_conflict"` rather than raised. A REST read timeout (as opposed to a
  connection failure, already handled) is likewise mapped to
  `ModelUnavailableError` in `RestClient._request`/`download_asset_content`
  rather than escaping as a bare `TimeoutError`: before this fix, a slow
  response arriving *after* a successful claim would crash `run_once`
  without ever calling `/fail`, leaving the capture stuck `processing`
  until its lease naturally expired instead of being marked failed and
  surfaced with a clear error code. A timeout during the claim call itself
  (before any lease exists) is now also reported as a clean
  `status: "backend_unavailable"` instead of an unhandled crash.
- Processes exactly one capture per invocation (`run_once`), matching the
  contract's "one active model job" — no internal polling loop; the
  coordinator drives repeated invocation.

### Runner acceptance evidence

`tests/test_processor_runner.py` (16 tests, all passing): 14 unit tests
against a fake REST client covering the typed and audio happy paths,
unsupported source type, download+transcribe wiring, both failure-reporting
branches (lease valid vs. expired), claim conflicts, rejection of a
non-loopback backend URL, a backend-unavailable claim reported cleanly, a
mid-processing timeout still resulting in an explicit `/fail` report, and
(since 2026-09-14) a proposed `project_id` being resolved into a placement
operation with the container's looked-up version and a stale/unknown
container id falling back to no placement; plus
two unit tests against the real `RestClient` (with `urllib.request.urlopen`
monkeypatched to raise `TimeoutError`) confirming both `_request` and
`download_asset_content` map a read timeout to `ModelUnavailableError`
instead of letting it escape raw — and one live-HTTP
integration test that starts the real `backend.main:app` with `uvicorn` in a
background thread bound to `127.0.0.1` on an OS-assigned port, backed by the
same real Postgres database the rest of the test suite uses (via the
existing `client` fixture), with only `transcribe`/`interpret` stubbed for
determinism. That test creates a real typed capture over REST, runs the
actual `RestClient` against the live server, and asserts the capture ends up
`resolved` with one real `note` item created atomically and correctly
linked — proving the claim/lease/generation/atomic-interpretation wiring
against the real backend, not a mock of it.

Beyond the test suite, this was also run manually end to end with **no
stubbing**: a real `uvicorn` server on the real dev Postgres database, a real
typed capture created over REST, then `python -m processor.runner` using the
real `whisper.cpp`-backed `transcribe` path (not exercised by the typed
capture, since typed skips it) and the real loopback `qwen3.5:4b` via
`interpret`. Result: the capture was claimed, interpreted into one
`task` item ("Review Processor Integration Doc"), correctly routed to the
Projects category by the model, and the capture's processing state ended at
`resolved` — end-to-end, no mocks, on this machine's actual local models.

Repeated for the Tasks quick-add feature and its new project/folder
placement (2026-09-14): a real `project` item ("Apartment Move E2E") was
created over REST, then a typed capture "For the Apartment Move E2E
project, email Sarah Friday afternoon about the apartment move" was saved
and run through `python -m processor.runner` with no stubbing — real
loopback `qwen3.5:4b`. Result: the model recognized the named project from
the `projects` context list, the runner resolved its current version and
submitted a `"create"` operation with `project_id`/`project_expected_version`
set, and the backend atomically created one `task` item titled "Email Sarah
about apartment move", `category_id` forced to Projects, a `part_of`
relation to the project, and the capture's source link — all in the single
interpretation transaction, `processing.state` ending `resolved`. `due_date`
was correctly left `null` (no `captured_at` was supplied on this capture, so
"Friday afternoon" had nothing to ground against); a separate run that did
supply `captured_at`/`source_timezone` context (see
`tests/test_processor_interpretation.py::test_real_ollama_relative_date_grounds_against_captured_at_timezone_or_leaves_it_null`)
correctly resolved "Friday" to the actual following Friday's date and left
`due_time` null for the non-exact "afternoon". Both test entries were
archived afterward; nothing was deleted.

## Incident (2026-09-14, part 1): quick-add reliably failed due to a stale backend process, not model/prompt quality

Symptom reported: typed Tasks quick-add was "not reliably becoming a
structured task through local Qwen." Root cause, found by reproducing the
exact request the real UI sends against the actually-running dev stack
(not the test suite, which always runs against fresh code and therefore
never exhibited this): the backend `uvicorn backend.main:app` process
serving `http://127.0.0.1:8000` — the URL both `frontend/.env.local`'s
proxy route and `processor/runner.py`'s default target use — had been
started (`19:36:52`) **before** a later change added `processing_profile`
to `backend/capture_schemas.py`'s `CaptureMetadata` (a `StrictModel`,
`extra="forbid"`). `uvicorn` was not run with `--reload`, so that process
kept serving the old Pydantic model in memory indefinitely; every real
`TaskQuickAdd.tsx` submission (which always sends
`metadata: {"processing_profile": "task_quick_add"}`) was rejected with a
`422 extra_forbidden` before the capture was even persisted. Confirmed by
posting the frontend's exact request body directly:

```json
{"error":{"code":"invalid_input","message":"Request validation failed","details":{"errors":[{"type":"extra_forbidden","loc":["body","metadata","processing_profile"],"msg":"Extra inputs are not permitted","input":"task_quick_add"}]}}}
```

`GET /api/v1/health/ready` on that same stale process independently
confirmed the staleness: it reported `{"expected_revision": "20260915_0004",
"actual_revision": "20260915_0005"}` — its hardcoded expected-head string
predated migration `20260915_0005` (`uq_item_relation_single_parent`), even
though the database itself (and the code on disk) were already correctly at
`20260915_0005`. The database schema, `processor/runner.py`,
`processor/interpretation.py`, and the Qwen prompt/response handling were
all already correct; nothing about model or prompt quality was at fault.

**Fix applied:** restarted the stale `uvicorn` process (`kill` the old PID,
relaunch `uvicorn backend.main:app --host 127.0.0.1 --port 8000` from the
current checkout) so it loads the current `backend/` code. The already-
running `processor.scheduler` process needed no change (a fresh process
naturally reloads current `processor/` code on start; it was restarted
anyway as part of this diagnosis, not because it was stale). No database
migration, code, or config change was required — only the process restart.
Verified after restart: `/health/ready` reports `{"status": "ready"}`; the
frontend's exact request body now returns `201`; four separate real typed
captures with `metadata.processing_profile = "task_quick_add"` — one posted
directly to the backend, one posted through the actual Next.js proxy route
at `127.0.0.1:3000/api/v1/captures` (the same path a browser hitting the
real UI uses) — were each claimed by the running scheduler, interpreted by
real loopback `qwen3.5:4b`, and resolved into exactly one `task` item apiece
(archived afterward; nothing was deleted). See
`tests/test_task_quick_add.py::test_task_quick_add_frontend_request_shape_is_accepted`
and `tests/test_processor_runner.py::test_capture_processing_profile_is_forwarded_to_interpret_context`
/ `test_capture_without_metadata_defaults_to_general_profile` for the new
regression coverage this incident motivated: the first pins the exact
literal request body the frontend sends against `POST /captures` (so a
future field rename/removal on either side of that contract fails a test
immediately instead of a live server silently rejecting every submission
again), and the other two pin that `run_once` actually forwards
`capture["metadata"]["processing_profile"]` into `interpret()`'s context —
if that wiring ever silently breaks, `task_quick_add` captures would fall
back to the unconstrained "general" profile and the backend's
exactly-one-task enforcement in `interpret_capture`
(`backend/captures.py`) would never get exercised.

**Operational takeaway, not a code defect:** this stack has no process
supervisor and `uvicorn` intentionally runs without `--reload` (matching a
non-dev deployment); after editing `backend/` code, the running server
must be restarted (`kill` it and relaunch, or use a `--reload` process
locally) for the change to take effect. `scripts/processor_service.py
restart` already exists for the processor side; there is currently no
equivalent wrapper for the backend API process itself, since
`docs/local-development.md`'s documented workflow runs it in the
foreground and expects the operator to stop it with Ctrl-C and relaunch —
worth revisiting if backend code changes during a running session become a
recurring source of this exact failure mode.

## Local processor scheduler (`processor/scheduler.py`, 2026-09-14)

`run_once` (above) still processes at most one pending capture per call;
`processor/scheduler.py` is the "coordinator drives repeated invocation"
piece the runner's own docstring names, sized for one sole-user MacBook:

- `run_forever(rest, config, ...)` calls `run_once` on a fixed poll interval
  (`SchedulerConfig.poll_interval_s`, default 15s, bounded 1–3600s) until a
  `should_stop()` callable (a `StopSignal` set from `SIGTERM`/`SIGINT` in
  the CLI) says to stop; it checks the stop flag both before claiming and
  before sleeping, so shutdown lands within the current cycle rather than
  after a full extra poll interval. It never registers with launchd/cron
  and never touches anything outside the configured loopback REST API — no
  new state beyond the REST-tracked capture rows, so it is safely
  restartable at any point and adds no cloud fallback of any kind.
- An unexpected exception from one `run_once` call is logged and the loop
  continues; the capture in question is left in whatever state `run_once`'s
  own failure handling already gave it (typically `failed`, via `/fail`),
  not silently "fixed" or retried automatically. One active model job at a
  time, matching the contract.
- `python -m processor.scheduler` runs it in the foreground. For unattended
  background use, `scripts/processor_service.py` (`start`/`stop`/`status`/
  `restart`) manages exactly one such process with a PID file under
  `.local/traceback/` — the same self-contained pattern
  `scripts/local_db.py` uses for the local PostgreSQL cluster. `start` is
  idempotent (a second `start` while already running is a no-op reporting
  the existing PID); `stop` sends `SIGTERM` and waits (default 10s) for a
  clean exit before reporting failure; `status` distinguishes "not
  running" from "not running (stale pidfile)". None of this registers a
  macOS LaunchAgent, writes outside this checkout, or touches any global
  user configuration.

### Scheduler acceptance evidence

`tests/test_processor_scheduler.py` (8 tests, no network/real time): unit
tests against `run_forever` with a counting fake `sleep` and the same
`FakeRestClient` as the runner tests, covering an immediate stop request,
bounded `max_iterations` with sleeps between (not after) iterations, one
capture processed then subsequent idle wakes not resubmitting it, an
unexpected crash inside `run_once` not stopping the loop, a stop flag set
mid-run taking effect before the next sleep, and `SchedulerConfig`'s
loopback/poll-interval validation.

`tests/test_processor_service.py` (5 tests): a real subprocess lifecycle
test — `scripts/processor_service.py start` against an isolated
`TRACEBACK_PROCESSOR_STATE_DIR` (a pytest tmp path, never the real
`.local/traceback/processor.pid`) and a closed loopback port
(`127.0.0.1:1`, so every wake fails fast without needing a live backend) —
asserting the real background process starts (with the correct PID
recorded), a second `start` is a no-op, the log shows it actually ran, and
`stop` cleanly signals and reaps it with the PID file removed; that
`stop`/`status` on a never-started or stale-pidfile state report cleanly
rather than crashing; and that a pidfile pointing at a live PID that is
*not* our scheduler (the classic PID-reuse hazard for any pidfile-based
daemon — simulated with the test process's own PID, definitely not
`python -m processor.scheduler`) is reported as "an unrelated process" and
is never sent `SIGTERM`, verified via `scripts/processor_service.py`'s
`ps -p <pid> -o command=` check before treating any live PID as ours; and a
regression test that `start` still spawns a working scheduler when
`processor_service.py` itself is invoked with a bare `/usr/bin/python3`
(macOS's system Python, which lacks `pydantic`) — this was a real bug found
by manual testing (see below), not a hypothetical: `start()` originally
spawned the child with `sys.executable`, so running the wrapper with a
dependency-less interpreter produced a child that crashed on import before
`status` next had a chance to notice, even though `start` had already
printed success. Fixed by preferring this checkout's own
`.venv/bin/python3` for the spawned child regardless of which interpreter
ran the wrapper script.

Beyond the test suite, this was also verified manually against the real
dev database and a real running `uvicorn` (not the test fixture's
disposable database): created one real typed capture over REST, started
`scripts/processor_service.py` with a 3s poll interval (invoked with the
bare `python3` from PATH, to specifically exercise the interpreter fix
above) pointed at the real backend, and watched its log — the capture was
claimed and interpreted into one real item within one poll cycle (~3s),
then subsequent polls correctly logged `idle` rather than reprocessing it.
`stop` cleanly signaled and reaped the process (confirmed no orphan process
remained). The capture and resulting item were then unlinked, archived, and
permanently deleted through the same REST API to leave the local dev
database exactly as found.

## Reproducible latency/memory benchmark script (`scripts/model_benchmark.py`)

See "Reproducible latency/memory benchmark" above for the exact command and
this machine's measured results; that script is the reproducible artifact,
run again on any machine to get fresh numbers for it.

## Voice command stages (2026-09-26)

Added for the review-first voice feature ([features/voice-commands.md](features/voice-commands.md)); no new model or weights. Each recording is normalized with local `ffmpeg` (`processor/voice.py:normalize_audio`, fixed argv, 30 s timeout, `-t 120` bound, rejects audio over 65 s) before whisper.cpp, because the browser's WebM/Opus or MP4/AAC container was previously passed to `whisper-cli` unnormalized. Qwen (`processor/voice.py:extract_slots`, reusing the loopback Ollama call and bounded retries) returns spoken-form slots only under an `extra="forbid"` schema. Automated tests cover ffmpeg normalization of real WebM/Opus, M4A/AAC and Ogg/Opus clips generated with ffmpeg's synthetic sine source, and a real-HTTP round trip with Whisper and Qwen **stubbed**. **No latency, memory, thermal, or quality measurement of the new chain was made**; the 2026-09-14 numbers above still cover only Whisper and Qwen in isolation.

## What is not covered here

- Base `whisper` model latency/memory comparison (the plan's fallback if
  `small` proves too heavy) was not benchmarked; `small` was well within
  budget on this 16GB machine for short synthetic clips.
- The scheduler polls on a fixed interval; it does not back off when idle,
  adapt to load, or coordinate multiple machines/processes (a sole-user
  single MacBook is the stated scope). It does not integrate with
  launchd/systemd — starting it at login, if desired, is a manual step
  outside this repository's scope, deliberately, so as not to alter any
  global/user-level OS configuration.
- Real personal-recording transcription/interpretation quality, per-language
  mixed-speech accuracy, and long-context behavior are unevaluated.
