from __future__ import annotations

import io
import os
from pathlib import Path
import sys
import tempfile
import asyncio

import httpx
from PIL import Image, ImageDraw


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def sample_image_bytes() -> bytes:
    image = Image.new("RGB", (300, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 35, 230, 215), fill=(75, 61, 92))
    draw.rectangle((80, 175, 220, 265), fill=(202, 58, 113))
    draw.ellipse((108, 92, 136, 120), fill=(244, 242, 237))
    draw.ellipse((164, 92, 192, 120), fill=(244, 242, 237))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def run_web_flow() -> None:
    with tempfile.TemporaryDirectory(prefix="pindou-web-test-") as temp_dir:
        os.environ["PINDOU_DATA_DIR"] = temp_dir
        os.environ["PINDOU_SESSION_SECRET"] = "verification-only-session-secret"
        os.environ.pop("PINDOU_DATABASE_URL", None)
        os.environ.pop("PINDOU_MODEL_API_URL", None)
        os.environ.pop("PINDOU_ADMIN_EMAIL", None)
        os.environ.pop("PINDOU_ADMIN_PASSWORD", None)

        from pindou.web import app, store

        store.initialize()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            print("stage=health", flush=True)
            assert (await client.get("/api/health")).json() == {"status": "ok"}
            assert (await client.get("/")).status_code == 404
            assert (await client.get("/api/projects")).status_code == 401

            print("stage=register", flush=True)
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": "maker@example.com",
                    "password": "correct-horse-battery",
                    "display_name": "林小豆",
                },
            )
            assert response.status_code == 200, response.text
            maker = response.json()["user"]
            maker_id = maker["id"]
            assert maker["email"] == "maker@example.com"
            assert maker["role"] == "user"
            assert maker["status"] == "active"
            assert (await client.get("/api/admin/overview")).status_code == 403

            print("stage=upload", flush=True)
            response = await client.post(
                "/api/projects",
                data={"name": "测试角色"},
                files={"image": ("sample.png", sample_image_bytes(), "image/png")},
            )
            assert response.status_code == 201, response.text
            project = response.json()["project"]
            project_id = project["id"]
            assert project["status"] == "uploaded"
            assert (await client.get(project["assets"]["source"])).status_code == 200

            print("stage=extract", flush=True)
            response = await client.post(
                f"/api/projects/{project_id}/extract",
                json={"x": 0.12, "y": 0.06, "width": 0.76, "height": 0.86},
            )
            assert response.status_code == 200, response.text
            project = response.json()["project"]
            assert response.json()["job"]["status"] == "completed"
            assert project["status"] == "extracted"
            assert "cutout" in project["assets"]

            print("stage=mask-refine", flush=True)
            response = await client.post(
                f"/api/projects/{project_id}/mask/refine",
                json={
                    "keep": [{"x": 0.5, "y": 0.5}],
                    "remove": [{"x": 0.02, "y": 0.02}],
                    "radius": 4,
                },
            )
            assert response.status_code == 200, response.text
            project = response.json()["project"]
            assert project["status"] == "extracted"

            print("stage=stylize", flush=True)
            response = await client.post(
                f"/api/projects/{project_id}/stylize",
                json={
                    "provider": "local",
                    "prompt": "",
                    "pixel_resolution": 48,
                    "color_count": 12,
                },
            )
            assert response.status_code == 200, response.text
            project = response.json()["project"]
            assert project["status"] == "stylized"

            print("stage=coloring", flush=True)
            palette_response = await client.get("/api/palette")
            assert palette_response.status_code == 200
            assert len(palette_response.json()["colors"]) == 221
            response = await client.post(
                f"/api/projects/{project_id}/coloring",
                json={
                    "cols": 24,
                    "rows": 22,
                    "coverage": 0.3,
                    "padding": 0.04,
                    "smooth_cells": 0,
                    "source": "stylized",
                    "palette_codes": ["D6", "D9", "E5", "H7", "H10"],
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            project = payload["project"]
            coloring = payload["coloring"]
            assert project["status"] == "coloring"
            assert project["has_coloring"] is True
            assert "painted" in project["assets"]
            assert coloring["cols"] == 24 and coloring["rows"] == 22
            occupied = [
                (row, col)
                for row in range(coloring["rows"])
                for col in range(coloring["cols"])
                if coloring["mask"][row][col]
            ]
            assert occupied
            first_row, first_col = occupied[0]
            coloring["cells"][first_row][first_col] = "#ff0000"
            response = await client.put(
                f"/api/projects/{project_id}/coloring",
                json={"cells": coloring["cells"]},
            )
            assert response.status_code == 200, response.text
            assert response.json()["coloring"]["cells"][first_row][first_col] == "#ff0000"
            saved = await client.get(f"/api/projects/{project_id}/coloring")
            assert saved.status_code == 200
            assert saved.json()["coloring"]["mask"] == coloring["mask"]
            assert (await client.get(project["assets"]["painted"])).status_code == 200
            ai_response = await client.post(
                f"/api/projects/{project_id}/coloring/ai",
                json={"prompt": "使用紫色系"},
            )
            assert ai_response.status_code == 400

            print("stage=pattern", flush=True)
            response = await client.post(
                f"/api/projects/{project_id}/pattern",
                json={
                    "cols": 24,
                    "rows": 22,
                    "coverage": 0.3,
                    "padding": 0.04,
                    "smooth_cells": 0,
                    "source": "painted",
                    "palette_codes": ["D6", "D9", "E5", "H7", "H10"],
                },
            )
            assert response.status_code == 200, response.text
            project = response.json()["project"]
            assert project["status"] == "completed"
            assert project["bead_count"] > 0
            assert 0 < project["colors_used"] <= 5
            assert set(response.json()["counts"]).issubset({"D6", "D9", "E5", "H7", "H10"})
            assert (await client.get(project["downloads"]["png"])).status_code == 200
            json_download = await client.get(project["downloads"]["json"])
            assert json_download.status_code == 200
            assert json_download.json()["source_image"] == "painted.png"
            assert (await client.get(project["downloads"]["csv"])).status_code == 200

            print("stage=profile", flush=True)
            response = await client.put(
                "/api/profile",
                json={"display_name": "林小豆", "bio": "喜欢紫色系拼豆。"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["user"]["bio"] == "喜欢紫色系拼豆。"

            print("stage=account-history", flush=True)
            usage_response = await client.get("/api/account/usage")
            assert usage_response.status_code == 200
            usage = usage_response.json()["usage"]
            assert usage["projects"] == 1
            assert usage["storage_bytes"] > 0
            assert usage["beads"] == project["bead_count"]
            activity_response = await client.get("/api/activity")
            assert activity_response.status_code == 200
            assert activity_response.json()["activities"]
            message_response = await client.post(
                "/api/messages",
                json={"subject": "建议增加收藏", "content": "希望可以收藏常用色号。"},
            )
            assert message_response.status_code == 201, message_response.text
            message = message_response.json()["message"]
            message_id = message["id"]
            assert message["status"] == "open"
            assert len((await client.get("/api/messages")).json()["messages"]) == 1

            print("stage=logout", flush=True)
            assert (await client.post("/api/auth/logout")).status_code == 200
            assert (await client.get("/api/auth/me")).status_code == 401

            print("stage=ownership", flush=True)
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": "other@example.com",
                    "password": "another-secure-password",
                    "display_name": "另一位用户",
                },
            )
            assert response.status_code == 200, response.text
            other = response.json()["user"]
            other_id = other["id"]
            assert (await client.get(f"/api/projects/{project_id}")).status_code == 404
            assert (await client.get(project["assets"]["source"])).status_code == 404
            assert (await client.post("/api/auth/logout")).status_code == 200

            print("stage=login", flush=True)
            response = await client.post(
                "/api/auth/login",
                json={"email": "maker@example.com", "password": "correct-horse-battery"},
            )
            assert response.status_code == 200, response.text
            assert len((await client.get("/api/projects")).json()["projects"]) == 1

            print("stage=admin", flush=True)
            store.update_user_admin(maker_id, role="admin", status="active")

            overview_response = await client.get("/api/admin/overview")
            assert overview_response.status_code == 200, overview_response.text
            overview = overview_response.json()["overview"]
            assert overview["users"] == 2
            assert overview["projects"] == 1
            assert overview["open_messages"] == 1

            users_response = await client.get("/api/admin/users", params={"query": "maker"})
            assert users_response.status_code == 200
            assert users_response.json()["users"][0]["id"] == maker_id

            detail_response = await client.get(f"/api/admin/users/{maker_id}")
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert detail["usage"]["projects"] == 1
            assert detail["projects"][0]["id"] == project_id
            assert detail["jobs"]
            assert detail["messages"][0]["id"] == message_id

            projects_response = await client.get("/api/admin/projects")
            assert projects_response.status_code == 200
            admin_project = projects_response.json()["projects"][0]
            assert admin_project["user_email"] == "maker@example.com"
            assert (
                await client.get(admin_project["assets"]["source"])
            ).status_code == 200

            jobs_response = await client.get("/api/admin/jobs", params={"user_id": maker_id})
            assert jobs_response.status_code == 200
            jobs = jobs_response.json()["jobs"]
            assert {job["operation"] for job in jobs}.issuperset(
                {"extract", "stylize", "create_coloring", "generate_pattern"}
            )
            assert all(isinstance(job["input"], dict) for job in jobs)
            assert all(isinstance(job["output"], dict) for job in jobs)

            messages_response = await client.get("/api/admin/messages", params={"status": "open"})
            assert messages_response.status_code == 200
            assert messages_response.json()["messages"][0]["content"] == "希望可以收藏常用色号。"
            resolve_response = await client.put(
                f"/api/admin/messages/{message_id}",
                json={"status": "resolved", "admin_note": "已加入产品规划。"},
            )
            assert resolve_response.status_code == 200, resolve_response.text
            assert resolve_response.json()["message"]["status"] == "resolved"

            activity_response = await client.get("/api/admin/activity")
            assert activity_response.status_code == 200
            activities = activity_response.json()["activities"]
            assert any(item["action"] == "project.upload" for item in activities)
            assert any(item["category"] == "request" for item in activities)

            self_update = await client.put(
                f"/api/admin/users/{maker_id}",
                json={"role": "user", "status": "active"},
            )
            assert self_update.status_code == 400
            disable_response = await client.put(
                f"/api/admin/users/{other_id}",
                json={"role": "user", "status": "disabled"},
            )
            assert disable_response.status_code == 200
            assert disable_response.json()["user"]["status"] == "disabled"

            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as disabled_client:
                disabled_login = await disabled_client.post(
                    "/api/auth/login",
                    json={"email": "other@example.com", "password": "another-secure-password"},
                )
                assert disabled_login.status_code == 401

            print("stage=delete", flush=True)
            assert (await client.delete(f"/api/projects/{project_id}")).status_code == 200
            assert (await client.get("/api/projects")).json()["projects"] == []

        print(
            "web_flow=auth,upload,extract,stylize,coloring,pattern,download,profile,"
            "history,messages,ownership,admin,audit,jobs,delete"
        )
        print("status=ok")


def main() -> int:
    asyncio.run(run_web_flow())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
