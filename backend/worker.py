from __future__ import annotations

import asyncio
import logging

from .config import settings
from .services.jobs import execute_job, worker_identity
from .state import store


logger = logging.getLogger("pindou.worker")


async def run_worker() -> None:
    store.initialize(bootstrap_admin=False)
    identity = worker_identity()
    recovered = store.requeue_stale_jobs(
        settings.worker_stale_seconds, max_attempts=settings.max_job_attempts
    )
    logger.info("worker_started identity=%s", identity)
    if recovered:
        logger.warning("stale_jobs_requeued count=%s", recovered)
    while True:
        recovered = store.requeue_stale_jobs(
            settings.worker_stale_seconds, max_attempts=settings.max_job_attempts
        )
        if recovered:
            logger.warning("stale_jobs_requeued count=%s", recovered)
        job = store.claim_next_job(identity)
        if job is None:
            await asyncio.sleep(settings.worker_poll_seconds)
            continue
        try:
            await execute_job(job)
            logger.info("job_completed id=%s operation=%s", job["id"], job["operation"])
        except Exception as exc:
            logger.exception("job_failed id=%s operation=%s", job["id"], job["operation"])
            non_retryable = any(
                marker in str(exc) for marker in ("用户已取消任务", "项目不存在或已被删除")
            )
            if not non_retryable and store.retry_job(job["id"], max_attempts=settings.max_job_attempts):
                logger.warning("job_requeued id=%s attempt=%s", job["id"], job["attempts"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
