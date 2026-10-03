# Inline note images from Claude Code

Status: planned. The web editor already inserts uploaded images into note Markdown. The local
Traceback MCP adapter currently exposes asset metadata and linking, but no binary upload tool.

## Goal

A user can tell Claude Code: “Put `/path/to/diagram.png` after the second paragraph of my
Architecture note.” Claude Code finds the note and calls one Traceback MCP tool. The image
appears at that position in the note body. No shell `curl`, bearer token handling, or manual
asset ID is needed. The tool returns the note ID, new version, and asset ID, not image bytes.

## Local MCP tool

Add `insert_note_image(note_id, image_path, expected_version, alt_text?, after_text?,
idempotency_key?)` to `traceback_mcp/tools/assets.py` and register it as a mutation in
`traceback_mcp/server.py`.

- `image_path` is a path on the machine running the **stdio MCP server**, not an image pasted
  into Claude's conversation. Resolve it to a regular file. Reject symlinks, directories,
  device files, zero-byte files, and files over 20 MB. Accept only PNG, JPEG, GIF, WebP, and
  AVIF after checking the actual file type, not just the extension or declared MIME type.
- Limit reads to explicitly configured image import directories. Canonicalize the path and
  verify it remains inside one of them before opening it; prevent symlink races with an
  opened file descriptor and `fstat`. Document a simple local setting for adding a directory.
  Do not allow the MCP caller to change the allowlist.
- Require `get_item`'s current `expected_version`. Confirm it is a note. If `after_text` is
  supplied, require exactly one match in the current `content_md`; otherwise return an
  ambiguity error. Without it, append the image at the end. The tool inserts the same
  `![alt](/api/v1/assets/<id>/content)` syntax as the web editor, escaping Markdown alt text.
- Add a bounded, streaming binary upload method to `RestClient` for `POST /api/v1/assets`.
  Keep the token in the adapter; never expose it in tool arguments, responses, or logs.
  Upload over the configured loopback API only. Do not base64-encode image bytes into the
  MCP call or return them to Claude.
- Link the returned asset to the note, then patch its Markdown using the new version. Return
  structured partial failure details if upload, link, or patch fails. On a version conflict,
  do not retry with a newer version or overwrite concurrent edits. Where safe, unlink or
  archive an asset created by this call if the final patch fails.
- Use a stable idempotency key for retries. The current asset upload and link routes do not
  support idempotency; add server-side operation tracking or idempotency to those routes
  before claiming a retry cannot duplicate an image.

## Security and privacy

- This tool is **local stdio only**. Do not register a filesystem-path tool on the planned
  remote MCP endpoint: a path there would refer to the server, and a remote caller must not
  read arbitrary server files.
- The image bytes go from the local MCP process to the local Traceback API and asset store.
  The MCP response contains only IDs and metadata. Claude may already have received the
  image if the user pasted it into Claude Code separately; this tool does not send bytes back.
- Add tests for path traversal, symlinks, file replacement while opening, MIME mismatch,
  oversized input, conflicting note versions, ambiguous placement, partial failure, and
  retry behavior. Include an MCP protocol test proving the new tool is registered locally
  and absent from the remote catalog.

## Phone and hosted Traceback

The path-based tool cannot work from Claude's phone app: its remote MCP call runs away from
the phone and cannot read a phone-local image path. For that workflow, use an authenticated
upload in the hosted Traceback web UI, then let remote MCP place the resulting asset ID in a
note; or design a separate, short-lived upload handoff. Keep this separate from the local
Claude Code tool.

## Acceptance check

With Traceback running, place a local PNG in an allowed directory. In Claude Code, ask it
to insert that file after a unique sentence in a known note. Verify the image renders at
that position in the web preview, the note has one linked asset, and repeating the same
tool call with the same idempotency key does not create another asset or image reference.
