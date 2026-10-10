"""Safe, allowlisted reads of local image files for `insert_note_image`.

The path is canonicalized and must sit inside a configured import directory
with no symlink anywhere in it. The file is then opened by walking each path
component from an opened directory fd with `O_NOFOLLOW`, so a component
swapped for a symlink after the check cannot redirect the read; `fstat` on
the opened descriptor decides type and size, and the type is taken from the
file's magic bytes, never its extension.
"""

import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from mcp.server.mcpserver.exceptions import ToolError

MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _invalid(code: str, message: str, **details) -> ToolError:
    return ToolError(json.dumps({"code": code, "message": message, "details": details}))


def sniff_image_mime(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


def _relative_to_allowed(path: str, allowed: list[Path]) -> tuple[Path, tuple[str, ...]]:
    if not allowed:
        raise _invalid(
            "image_import_not_configured",
            "No image import directory is configured. The user must set TRACEBACK_MCP_IMAGE_IMPORT_DIRS "
            "(os.pathsep-separated directories) for the Traceback MCP server; the tool cannot change this.",
        )
    if not os.path.isabs(path):
        raise _invalid("invalid_input", "image_path must be an absolute path")
    lexical = os.path.abspath(path)
    canonical = os.path.realpath(path)
    if lexical != canonical:
        raise _invalid("invalid_image_path", "image_path must not contain symlinks or '..' segments")
    for root in allowed:
        root_real = Path(os.path.realpath(root))
        try:
            relative = Path(canonical).relative_to(root_real)
        except ValueError:
            continue
        if relative.parts:
            return root_real, relative.parts
    raise _invalid("invalid_image_path", "image_path is outside the configured image import directories")


@contextmanager
def open_import_image(path: str, allowed: list[Path]) -> Iterator[tuple[BinaryIO, int, str]]:
    """Yield `(binary_file, size, mime_type)` for a validated image, closing it afterwards."""
    root, parts = _relative_to_allowed(path, allowed)
    fds: list[int] = []
    try:
        try:
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            fds.append(directory)
            for part in parts[:-1]:
                directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
                fds.append(directory)
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
        except FileNotFoundError:
            raise _invalid("image_not_found", "No file exists at image_path") from None
        except OSError:
            raise _invalid("invalid_image_path", "image_path could not be opened safely") from None
        fds.append(file_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise _invalid("invalid_image_file", "image_path must be a regular file")
        if info.st_size == 0:
            raise _invalid("invalid_image_file", "The image file is empty")
        if info.st_size > MAX_IMAGE_BYTES:
            raise _invalid("image_too_large", f"Images must be at most {MAX_IMAGE_BYTES} bytes", size=info.st_size)
        stream = os.fdopen(file_fd, "rb")
        fds.remove(file_fd)
        with stream:
            mime = sniff_image_mime(stream.read(16))
            if mime is None:
                raise _invalid("unsupported_image_type", "Only PNG, JPEG, GIF, WebP, and AVIF images are supported")
            stream.seek(0)
            yield stream, info.st_size, mime
    finally:
        for fd in fds:
            os.close(fd)
