from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    session_cookie: str = "pindou_session"
    max_upload_bytes: int = 20 * 1024 * 1024
    max_image_side: int = 4096
    max_image_pixels: int = 40_000_000
    task_mode: str = "eager"
    worker_poll_seconds: float = 0.75
    worker_stale_seconds: int = 900
    max_projects_per_user: int = 100
    max_storage_bytes_per_user: int = 2 * 1024 * 1024 * 1024
    max_jobs_per_day: int = 100
    max_concurrent_jobs_per_user: int = 2
    max_job_attempts: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        task_mode = os.environ.get("PINDOU_TASK_MODE", "eager").strip().lower()
        if task_mode not in {"eager", "worker"}:
            raise RuntimeError("PINDOU_TASK_MODE must be 'eager' or 'worker'")
        return cls(
            data_dir=Path(os.environ.get("PINDOU_DATA_DIR", "data")),
            task_mode=task_mode,
            worker_poll_seconds=max(
                0.1,
                float(os.environ.get("PINDOU_WORKER_POLL_SECONDS", "0.75")),
            ),
            worker_stale_seconds=max(
                60,
                int(os.environ.get("PINDOU_WORKER_STALE_SECONDS", "900")),
            ),
            max_projects_per_user=max(
                1,
                int(os.environ.get("PINDOU_MAX_PROJECTS_PER_USER", "100")),
            ),
            max_storage_bytes_per_user=max(
                1,
                int(os.environ.get("PINDOU_MAX_STORAGE_BYTES_PER_USER", str(2 * 1024**3))),
            ),
            max_jobs_per_day=max(1, int(os.environ.get("PINDOU_MAX_JOBS_PER_DAY", "100"))),
            max_concurrent_jobs_per_user=max(
                1,
                int(os.environ.get("PINDOU_MAX_CONCURRENT_JOBS_PER_USER", "2")),
            ),
            max_job_attempts=max(1, int(os.environ.get("PINDOU_MAX_JOB_ATTEMPTS", "3"))),
        )


settings = Settings.from_env()
