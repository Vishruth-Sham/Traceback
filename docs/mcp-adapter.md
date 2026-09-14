# Local MCP adapter

Status: implemented (2026-09-14). `traceback_mcp` is a thin Python stdio MCP
server (official `mcp` SDK 2.2.0) that wraps the loopback FastAPI REST API
in `docs/backend-api.md`. It is a second client of that API, not a second
implementation of its rules: every tool call becomes one authenticated HTTP
request, and the REST layer remains the sole writer, the sole owner of
business rules, and the source of canonical IDs, versions, and error codes.

`create_capture` accepts `processing_profile="note_quick_add"` and a bounded `placement_hint`; `get_capture` exposes the backend-validated proposal. Manual acceptance continues through `apply_capture_interpretation`. Processor leases, claim/fail internals, and proposal submission are not registered as MCP tools.

`traceback_mcp` never imports `backend`/`processor`/database modules, never
opens a PostgreSQL connection, and never starts the API or Ollama. If the
API is not running, every tool call fails with a `backend_unavailable`
tool error naming the configured URL.

## Architecture

```text
Codex / Claude Code → stdio JSON-RPC → traceback_mcp (this package) → loopback HTTP → FastAPI → PostgreSQL
```

- `traceback_mcp/config.py` — environment-only settings (`TRACEBACK_MCP_*`
  plus the existing `TRACEBACK_API_TOKEN`), loaded from the same ignored
  `.env` the backend/processor use — resolved from this package's own
  location on disk, not the launching client's current working directory,
  so it is found no matter what cwd an MCP client starts the adapter with.
  Rejects any `api_base_url` that is not plain HTTP on a loopback address.
- `traceback_mcp/rest_client.py` — a stdlib-only (`urllib`) HTTP client,
  mirroring `processor.runner.RestClient`'s style, so the adapter adds no
  runtime dependency beyond the `mcp` SDK itself. Distinguishes a
  structured REST domain error from a connection failure, a request
  timeout, and a 2xx response whose body is not valid JSON.
- `traceback_mcp/errors.py` — maps any of the above onto an MCP `ToolError`
  carrying `{code, message, details}` as JSON text, and enforces
  `confirm=true` for destructive tools before any HTTP call is made.
  Every resource-ID tool argument is typed `uuid.UUID`, so the MCP SDK
  itself rejects a path-injection-shaped or otherwise malformed ID during
  schema validation, before a tool body — and therefore before any REST
  call — ever runs.
- `traceback_mcp/tools/*.py` — one plain function per tool (directly unit
  testable), grouped by REST resource.
- `traceback_mcp/server.py` — builds the `MCPServer`, registers every tool
  with its title/description/`ToolAnnotations`.
- `traceback_mcp/__main__.py` — `python -m traceback_mcp` stdio entrypoint.
  Logging goes to stderr only; stdout carries only MCP JSON-RPC framing.

## Run it directly

```sh
uv sync --extra test --locked
.venv/bin/python -m traceback_mcp
```

It talks stdio, so running it directly just waits for JSON-RPC on stdin;
use an MCP client (or the protocol test below) to exercise it. The backend
API must already be running (`uvicorn backend.main:app ...`, see
`docs/local-development.md`).

## Configuration (environment-only)

| Variable | Default | Meaning |
| --- | --- | --- |
| `TRACEBACK_API_TOKEN` | — (required) | Same bearer token as REST/the processor. |
| `TRACEBACK_MCP_API_BASE_URL` | `http://127.0.0.1:8000` | Must be plain HTTP on a loopback address. |
| `TRACEBACK_MCP_CLIENT_LABEL` | `mcp` | Sent as `X-Traceback-Client`; distinguishes MCP-originated actions in history/attribution. |
| `TRACEBACK_MCP_REQUEST_TIMEOUT_S` | `30` | Per-request HTTP timeout. |
| `TRACEBACK_MCP_MAX_LIST_LIMIT` | `100` | Client-side cap on list/search `limit` arguments (REST enforces its own bound regardless). |

No secret is ever accepted as a command-line argument, and the adapter
never modifies a user's global client configuration — only this project's
own `.env` (already gitignored) and the example configs below.

## Codex and Claude Code stdio configuration

Neither example config below embeds `TRACEBACK_API_TOKEN`: `.env` is
resolved from `traceback_mcp`'s own installed location, not the client's
working directory, so this works regardless of which directory the client
happens to launch the adapter from.

- Claude Code: copy `docs/examples/claude_code_mcp.json.example` to
  `.mcp.json` at the repo root (or run
  `claude mcp add --transport stdio traceback -- /absolute/path/to/Traceback/.venv/bin/python -m traceback_mcp`),
  substituting the real path to this checkout's `.venv`. See
  <https://code.claude.com/docs/en/mcp#option-3-add-a-local-stdio-server>.
- Codex: append `docs/examples/codex_config.toml.example`'s
  `[mcp_servers.traceback]` section to Codex's `config.toml`, substituting
  the real path. See <https://developers.openai.com/codex/mcp/>.

Neither example file is wired into this repository's own tooling; both are
inert until a developer copies them into their own client configuration.

### Client discovery smoke test (reproducible, no global config touched)

Both CLIs support an isolated or project-scoped configuration surface, so
discovery can be verified without editing `~/.codex/config.toml` or the
user-scope `~/.claude.json`:

```sh
# Codex: point CODEX_HOME at a throwaway directory instead of ~/.codex.
mkdir -p /tmp/codex-mcp-smoketest
CODEX_HOME=/tmp/codex-mcp-smoketest codex mcp add traceback -- \
  /absolute/path/to/Traceback/.venv/bin/python -m traceback_mcp
CODEX_HOME=/tmp/codex-mcp-smoketest codex mcp list --json   # shows the stdio command/args
CODEX_HOME=/tmp/codex-mcp-smoketest codex mcp get traceback
rm -rf /tmp/codex-mcp-smoketest   # never touches the real ~/.codex

# Claude Code: --scope project writes only this repo's .mcp.json, not
# ~/.claude.json.
claude mcp add --transport stdio --scope project traceback -- \
  /absolute/path/to/Traceback/.venv/bin/python -m traceback_mcp
claude mcp get traceback   # confirms command/args; connection itself needs
                            # interactive approval ("run `claude` to approve"),
                            # which this smoke test does not do
claude mcp remove traceback -s project   # clean up .mcp.json again
```

This was run during review (2026-09-14, then re-verified the same day after
later processor-side changes): both CLIs correctly parsed the stdio
command/args with no secrets present, and neither the real
`~/.codex/config.toml` nor `~/.claude.json` was modified — verified both
times by comparing each file's checksum before and after (unchanged both
runs), not merely by reading the CLI's own success message. Claude Code
reported writing only this repo's `.mcp.json`, which was removed
afterward. Neither CLI has a subcommand that actually issues a JSON-RPC
`tools/call` from the command line — that would require an interactive
session and, for Claude Code, one-time approval of the pending
project-scoped server — so the actual protocol exchange (`initialize` →
`list_tools` → `call_tool`, including a destructive call refused for
missing `confirm`) is instead verified with the official `mcp` Python
client SDK in `tests/test_mcp_protocol.py`, run as part of every full test
pass; see Testing evidence below.

## Tool catalog

Every read tool is annotated `readOnlyHint=true, openWorldHint=false`
(closed-world: it only ever queries this one local backend). Every
mutation is `readOnlyHint=false`; permanent-deletion tools are additionally
`destructiveHint=true` **and** refuse to run without an explicit
`confirm=true` argument, checked before any HTTP call — content retrieved
from a note, capture, or search result is data, never authorization, so a
model must never set `confirm=true` from anything but the user's own
explicit request in the current turn.

| Tool | REST | Kind |
| --- | --- | --- |
| `list_categories` | `GET /categories` | read |
| `list_items` | `GET /items` | read |
| `list_projects` | `GET /items?item_type=project` | read |
| `search_items` | `GET /items?q=...` | read |
| `get_item` | `GET /items/{id}` | read |
| `create_item` | `POST /items` | mutate |
| `update_item` | `PATCH /items/{id}` | mutate |
| `append_to_item` | `POST /items/{id}/append` | mutate |
| `move_item` | `POST /items/{id}/move` | mutate |
| `archive_item` / `restore_item` | `POST /items/{id}/archive` \| `/restore` | mutate |
| `delete_item_permanently` | `DELETE /items/{id}` | **destructive** |
| `list_inbox` | `GET /inbox` | read |
| `get_item_history` | `GET /items/{id}/history` | read |
| `undo_action` | `POST /actions/{id}/undo` | mutate |
| `list_tasks` | `GET /tasks` | read |
| `complete_task` / `reopen_task` | `POST /tasks/{id}/complete` \| `/reopen` | mutate |
| `link_items` / `unlink_items` | `POST /relations` \| `DELETE /relations/{id}` | mutate |
| `create_capture` | `POST /captures` | mutate |
| `list_captures` | `GET /captures` | read |
| `get_capture` | `GET /captures/{id}` | read |
| `correct_capture` | `POST /captures/{id}/corrections` | mutate |
| `archive_capture` / `restore_capture` | `POST /captures/{id}/archive` \| `/restore` | mutate |
| `delete_capture_permanently` | `DELETE /captures/{id}` | **destructive** |
| `retry_capture` | `POST /captures/{id}/retry` | mutate |
| `apply_capture_interpretation` | `POST /captures/{id}/interpretations` | mutate (`mode="manual"` only) |
| `get_item_sources` | `GET /items/{id}/sources` | read |
| `link_item_source` / `unlink_item_source` | `POST` \| `DELETE /items/{id}/sources/...` | mutate |
| `get_asset` | `GET /assets/{id}` | read (metadata only) |
| `link_item_asset` / `unlink_item_asset` | `POST` \| `DELETE /items/{id}/assets/{id}` | mutate |
| `archive_asset` / `restore_asset` | `POST /assets/{id}/archive` \| `/restore` | mutate |
| `delete_asset_permanently` | `DELETE /assets/{id}` | **destructive** |

### Deliberately not exposed

- **Processor lease operations** (`POST /captures/{id}/claim`,
  `/fail`) — these exist so the bounded local processor can safely report a
  durable failure under a lease *it* holds. An MCP client never holds that
  lease; exposing them would let a client fence out or corrupt the
  processor's in-flight work with no documented need.
  `apply_capture_interpretation` therefore always sends `mode="manual"`
  and never accepts a `lease_token`.
- **Raw asset upload/download** — `POST /assets` and
  `GET /assets/{id}/content` stay REST-only. This adapter never accepts an
  arbitrary filesystem path as an asset ID and never embeds raw binary
  content in a tool result; `get_asset` returns metadata only.
- **`search_items`** is a thin wrapper over `GET /items?q=...` (REST has no
  separate `/search` endpoint in this milestone); it does not search
  capture text — use `list_captures(q=...)` for that.

### Structured errors

A failed call returns `is_error=true`; the content text is a JSON object
`{"code", "message", "details"}` taken verbatim from the REST error
envelope (or `{"code": "backend_unavailable", ...}` when the API cannot be
reached at all). The MCP SDK itself prefixes a deliberately-raised tool
error's text with `Error executing tool <name>: `, so a client that wants
the structured object should parse the JSON starting at the first `{`
rather than assuming the whole string is JSON.

### Pagination, idempotency, and PATCH semantics

- Every list tool takes `cursor`/`limit` and returns `{items, next_cursor}`,
  matching REST; `limit` is bounded client-side by
  `TRACEBACK_MCP_MAX_LIST_LIMIT` in addition to REST's own bound.
- Every mutation with a REST `Idempotency-Key` equivalent accepts an
  optional `idempotency_key` argument, forwarded as that header alongside
  `X-Traceback-Client: <TRACEBACK_MCP_CLIENT_LABEL>`. Asset mutation routes
  do not support idempotency keys in REST, so their tools do not expose one.
- `update_item`'s `patch` argument and `correct_capture`'s `corrections`
  argument are JSON objects, not fixed keyword arguments, specifically so a
  field you omit stays unchanged while a field you include as `null`
  explicitly clears it — mirroring REST's PATCH semantics exactly instead
  of collapsing "omitted" and "null" into one Python `None`.

## Testing evidence

- `tests/test_mcp_tools_unit.py` — 22 unit tests against a fake REST
  client: PATCH tri-state semantics, unknown-field rejection, destructive
  `confirm` gating (verifies the fake client is never called when
  `confirm=false`), REST/network error → structured `ToolError` mapping,
  `create_capture`'s optional source-metadata fields, and `undo_action`'s
  `idempotency_key`.
- `tests/test_mcp_rest_client_unit.py` — 4 unit tests against
  `RestClient.request` with `urllib.request.urlopen` monkeypatched: a read
  timeout becomes a `BackendUnavailableError` instead of an unhandled
  `TimeoutError`, a 2xx response with a malformed JSON body becomes a
  structured `invalid_response` `RestError` without leaking the raw bytes,
  and a normal JSON/204 response still parses correctly.
- `tests/test_mcp_regressions.py` — 33 focused regression tests for two
  review fixes: `.env` resolution being independent of the process's
  current working directory (including that a real environment variable
  still overrides the file), and every resource-ID argument being rejected
  by MCP schema validation — before the tool body, and therefore before any
  REST call, ever runs — when given a path-injection-shaped or otherwise
  malformed value (`../../etc/passwd`, an embedded `?query`, a non-UUID
  string, or a non-UUID key inside `undo_action`'s `expected_versions`).
- `tests/test_mcp_acceptance.py` — 9 tests running the real FastAPI app
  under a real `uvicorn` server on a real loopback port, backed by the same
  disposable PostgreSQL database `tests/conftest.py` creates for the rest
  of the suite: full item/task lifecycle, move/relation lifecycle, capture
  creation and manual interpretation with provenance, version-conflict and
  not-found error mapping, and permanent-deletion archive-first/confirm
  gating, all over real HTTP.
- `tests/test_mcp_protocol.py` — 1 subprocess integration test: launches
  `python -m traceback_mcp` as a real child process and drives it with the
  official `mcp` client SDK (`stdio_client` + `ClientSession`) against the
  same live backend — real `initialize`, `list_tools` (checking
  annotations), and `call_tool`, including a destructive call refused for
  missing `confirm`.
- Historical MCP milestone run: `.venv/bin/pytest -q` → **123 passed** (**54** pre-existing
  backend/processor tests, verified independently with
  `pytest --collect-only` on the non-MCP test files — an earlier draft of
  this document mis-stated this as 64 — **+ 69** new MCP tests: 22 + 4 + 33
  + 9 + 1 above), against a real PostgreSQL database created and dropped by
  the existing `client` fixture. `uv lock --check` confirms `uv.lock` still
  matches `pyproject.toml` after narrowing the `mcp` version pin.

Current repository-wide validation is recorded in [backend-validation.md](backend-validation.md). The MCP `create_item` tool now also accepts a project/folder ID plus its expected version for atomic create-in-container, and `move_item` replaces the sole containment parent.

## Known limitations

- Tool functions are synchronous (`urllib`-based, like `processor.runner`);
  the MCP SDK runs them in a worker thread, so a slow/hung REST call blocks
  that one in-flight tool call but not the stdio loop itself. Given a
  single local user and loopback-only calls, this was chosen over adding an
  async HTTP dependency.
- `search_items` and `list_items(q=...)` only search item titles/content,
  matching the implemented REST surface; there is no combined
  items+captures search endpoint yet.
- `.env` is now resolved from `traceback_mcp/config.py`'s own package
  location (`Path(__file__).resolve().parent.parent / ".env"`), not the
  client's working directory, so a client that launches the adapter with a
  different cwd still finds it; only a checkout where the package itself
  has moved relative to the repository root would break this, which does
  not happen in normal installs. A real environment variable still
  overrides the `.env` file, unchanged.
- `traceback_mcp.errors` imports `ToolError` from the internal
  `mcp.server.mcpserver.exceptions` module — the SDK has no public
  re-export of it. `pyproject.toml` pins `mcp>=2.2.0,<2.3.0` (narrower than
  a plain `<3`) specifically so this adapter does not silently pick up an
  mcp release that moves or removes that internal path; widening the pin
  requires re-checking this import.
- Neither example client config has been wired into an actual Claude Code
  or Codex installation as part of this change; the protocol test
  substitutes the same subprocess invocation with explicit environment
  variables to verify wire-level correctness without touching a
  developer's global client settings.
