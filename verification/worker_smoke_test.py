from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path
import sys
import tempfile

import httpx
from PIL import Image, ImageDraw


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def sample_image_bytes() -> bytes:
    image = Image.new("RGB", (180, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((35, 20, 145, 150), fill=(116, 79, 150))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def run_worker_flow() -> None:
    with tempfile.TemporaryDirectory(prefix="pindou-worker-test-") as temp_dir:
        os.environ["PINDOU_DATA_DIR"] = temp_dir
        os.environ["PINDOU_SESSION_SECRET"] = "worker-verification-session-secret"
        os.environ["PINDOU_TASK_MODE"] = "worker"
        os.environ.pop("PINDOU_DATABASE_URL", None)
        os.environ.pop("PINDOU_ADMIN_EMAIL", None)
        os.environ.pop("PINDOU_ADMIN_PASSWORD", None)

        from backend.main import app
        from backend.services.jobs import execute_job
        from backend.state import store

        store.initialize()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": "worker@example.com",
                    "password": "worker-test-password",
                    "display_name": "Worker 测试",
                },
            )
            assert response.status_code == 200, response.text
            user_id = response.json()["user"]["id"]

            response = await client.post(
                "/api/projects",
                data={"name": "异步测试"},
                files={"image": ("worker.png", sample_image_bytes(), "image/png")},
            )
            assert response.status_code == 201, response.text
            project_id = response.json()["project"]["id"]

            response = await client.post(
                f"/api/projects/{project_id}/extract",
                json={"x": 0.1, "y": 0.05, "width": 0.8, "height": 0.85},
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["job"]["id"]
            assert response.json()["job"]["status"] == "queued"

            queued = await client.get(f"/api/jobs/{job_id}")
            assert queued.status_code == 200
            assert queued.json()["job"]["status"] == "queued"

            claimed = store.claim_next_job("verification-worker")
            assert claimed is not None and claimed["id"] == job_id
            await execute_job(claimed)

            completed = await client.get(f"/api/jobs/{job_id}")
            assert completed.status_code == 200
            payload = completed.json()
            assert payload["job"]["status"] == "completed"
            assert payload["project"]["status"] == "extracted"
            assert payload["project"]["assets"]["cutout"]
            assert store.get_job(job_id, user_id=user_id)["attempts"] == 1

        print("worker_flow=enqueue,claim,execute,poll")
        print("status=ok")


def main() -> int:
    asyncio.run(run_worker_flow())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
