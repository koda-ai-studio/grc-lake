"""Restrict post-login navigation to a local console route."""

from urllib.parse import unquote, urlsplit

__all__ = ["console_return_path"]


def console_return_path(value: str | None) -> str:
    if not value or len(value) > 2048 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return "/console"
    try:
        parts = urlsplit(value)
    except ValueError:
        return "/console"
    path = unquote(parts.path)
    if (
        parts.scheme
        or parts.netloc
        or not (path == "/console" or path.startswith("/console/"))
        or any(char in path for char in ("\\", "%"))
        or any(ord(char) < 32 or ord(char) == 127 for char in path)
        or any(segment in {".", ".."} for segment in path.split("/"))
        or path.rstrip("/") == "/console/login"
    ):
        return "/console"
    return value
