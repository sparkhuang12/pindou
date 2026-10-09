from __future__ import annotations

import io
import os
import time

import httpx
from PIL import Image, ImageDraw


def sample_image_bytes() -> bytes:
    image = Image.new("RGB", (220, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((45, 25, 175, 185), fill=(111, 76, 150))
    draw.rectangle((65, 150, 155, 205), fill=(210, 67, 130))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> int:
    base_url = os.environ.get("PINDOU_E2E_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=base_url, trust_env=False, timeout=20) as client:
        assert "豆格 Pindou" in client.get("/").text
        assert client.get("/admin").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/health").json() == {"status": "ok"}

        response = client.post(
            "/api/auth/register",
            json={
                "email": "docker-worker@example.com",
                "password": "docker-worker-password",
                "display_name": "Docker Worker",
            },
        )
        assert response.status_code == 200, response.text
        response = client.post(
            "/api/projects",
            data={"name": "Compose 异步测试"},
            files={"image": ("compose.png", sample_image_bytes(), "image/png")},
        )
        assert response.status_code == 201, response.text
        project_id = response.json()["project"]["id"]

        response = client.post(
            f"/api/projects/{project_id}/extract",
            json={"x": 0.1, "y": 0.05, "width": 0.8, "height": 0.9},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["job"]["id"]

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = client.get(f"/api/jobs/{job_id}")
            assert result.status_code == 200, result.text
            payload = result.json()
            if payload["job"]["status"] == "completed":
                assert payload["job"]["attempts"] == 1
                assert payload["project"]["status"] == "extracted"
                assert client.get(payload["project"]["assets"]["cutout"]).status_code == 200
                print("docker_e2e=frontend,proxy,api,postgres,worker,shared-volume")
                print("status=ok")
                return 0
            if payload["job"]["status"] == "failed":
                raise AssertionError(payload["job"]["error_message"])
            time.sleep(0.5)
    raise AssertionError("background worker did not finish within 60 seconds")


if __name__ == "__main__":
    raise SystemExit(main())
