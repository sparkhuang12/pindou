from __future__ import annotations

from pindou.storage import Store

from .config import settings


store = Store(
    settings.data_dir,
    max_projects_per_user=settings.max_projects_per_user,
    max_storage_bytes_per_user=settings.max_storage_bytes_per_user,
    max_jobs_per_day=settings.max_jobs_per_day,
    max_concurrent_jobs_per_user=settings.max_concurrent_jobs_per_user,
)
