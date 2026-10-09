from __future__ import annotations

from pathlib import Path

from fastapi import Response


def file_response(path: Path, media_type: str, *, filename: str = "") -> Response:
    headers = {
        "Cache-Control": "no-store",
        "Content-Length": str(path.stat().st_size),
    }
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=path.read_bytes(), media_type=media_type, headers=headers)
