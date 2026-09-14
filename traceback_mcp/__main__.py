"""Stdio entrypoint: `python -m traceback_mcp`.

Keeps stdout protocol-clean for stdio JSON-RPC framing: logging goes to
stderr only, and nothing here ever logs the bearer token or raw capture
content. Configuration is environment-only (see `traceback_mcp.config`);
this file never starts a background service and never falls back to a
non-loopback or hosted backend.
"""

import logging
import sys

from traceback_mcp.server import build_server


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s traceback_mcp: %(message)s")
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
