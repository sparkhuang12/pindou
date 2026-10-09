from __future__ import annotations

from typing import Any


def serialize_project(project: dict[str, Any], *, admin: bool = False) -> dict[str, Any]:
    asset_fields = {
        "source": "source_path",
        "mask": "mask_path",
        "cutout": "cutout_path",
        "stylized": "stylized_path",
        "painted": "painted_path",
        "pattern": "pattern_path",
        "preview": "preview_path",
    }
    asset_prefix = "/api/admin/projects" if admin else "/api/projects"
    assets = {
        name: f"{asset_prefix}/{project['id']}/assets/{name}?v={project['updated_at']}"
        for name, field in asset_fields.items()
        if project.get(field)
    }
    downloads = {
        kind: f"/api/projects/{project['id']}/download/{kind}"
        for kind, field in {
            "png": "pattern_path",
            "json": "json_path",
            "csv": "csv_path",
        }.items()
        if project.get(field)
    }
    payload = {
        "id": project["id"],
        "name": project["name"],
        "status": project["status"],
        "selection": project["selection"],
        "settings": project["settings"],
        "bead_count": project["bead_count"],
        "colors_used": project["colors_used"],
        "cols": project["cols"],
        "rows": project["rows"],
        "has_coloring": bool(project.get("coloring_path")),
        "original_filename": project.get("original_filename", ""),
        "content_type": project.get("content_type", ""),
        "source_bytes": project.get("source_bytes", 0),
        "source_width": project.get("source_width", 0),
        "source_height": project.get("source_height", 0),
        "storage_bytes": project.get("storage_bytes", 0),
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
        "assets": assets,
        "downloads": downloads,
    }
    if admin:
        payload["user_id"] = project["user_id"]
        if "user_email" in project:
            payload["user_email"] = project["user_email"]
            payload["user_name"] = project["user_name"]
    return payload


def serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "project_id": job.get("project_id"),
        "operation": job["operation"],
        "provider": job["provider"],
        "model_name": job["model_name"],
        "status": job["status"],
        "error_message": job["error_message"],
        "duration_ms": job["duration_ms"],
        "attempts": job.get("attempts", 0),
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
        "output": job.get("output", {}),
        "cancel_requested": bool(job.get("cancel_requested", 0)),
    }
