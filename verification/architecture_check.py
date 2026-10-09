from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def main() -> int:
    required = [
        "ARCHITECTURE.md",
        "frontend/index.html",
        "frontend/admin.html",
        "frontend/app.js",
        "frontend/nginx.conf",
        "backend/main.py",
        "backend/worker.py",
        "backend/api/projects.py",
        "backend/services/processing.py",
    ]
    for relative in required:
        assert (ROOT / relative).is_file(), f"missing architecture component: {relative}"

    compatibility_lines = (ROOT / "pindou/web.py").read_text(encoding="utf-8").splitlines()
    assert len(compatibility_lines) <= 30, "pindou/web.py must remain a small compatibility shim"
    assert not list((ROOT / "pindou/static").glob("*")), "frontend assets belong in frontend/"

    for path in (ROOT / "backend/services").glob("*.py"):
        assert "fastapi" not in imported_roots(path), f"service imports FastAPI: {path}"

    for path in (ROOT / "pindou").glob("*.py"):
        if path.name == "web.py":
            continue
        roots = imported_roots(path)
        assert "fastapi" not in roots, f"core imports FastAPI: {path}"
        assert "backend" not in roots, f"core imports backend: {path}"

    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for service in ("database:", "api:", "worker:", "frontend:"):
        assert service in compose, f"compose service missing: {service}"
    assert "PINDOU_TASK_MODE: worker" in compose, "Docker must use the independent worker mode"

    print("architecture=frontend,api,services,worker,core")
    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
