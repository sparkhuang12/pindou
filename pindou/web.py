"""Compatibility entry point for installations using ``pindou.web``.

The HTTP application now lives in the modular :mod:`backend` package. New
code must import ``backend.main:app`` directly; this module remains so older
commands and integrations keep working during the migration.
"""

from backend.main import app, main
from backend.state import store

__all__ = ["app", "main", "store"]


if __name__ == "__main__":
    main()
