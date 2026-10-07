"""Production HTTP entrypoint that honors the hosting platform's PORT."""

from __future__ import annotations

import os

import uvicorn


def resolve_port(value: str | None) -> int:
    if value is None or not value.strip():
        return 8000
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError("PORT must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise ValueError("PORT must be between 1 and 65535")
    return port


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - container must listen outside loopback
        port=resolve_port(os.getenv("PORT")),
    )


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    main()
