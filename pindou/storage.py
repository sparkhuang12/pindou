from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    delete,
    event,
    func,
    inspect,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PASSWORD_ITERATIONS = 390_000
USER_STATUSES = {"active", "disabled"}
USER_ROLES = {"user", "admin"}
MESSAGE_STATUSES = {"open", "read", "resolved"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("请输入有效的邮箱地址")
    return email


def validate_password(value: str) -> None:
    if len(value) < 8:
        raise ValueError("密码至少需要 8 个字符")
    if len(value) > 128:
        raise ValueError("密码不能超过 128 个字符")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations_text),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


class Store:
    """SQLAlchemy persistence supporting SQLite locally and PostgreSQL in Docker."""

    PROJECT_FIELDS = {
        "name",
        "status",
        "source_path",
        "mask_path",
        "cutout_path",
        "stylized_path",
        "coloring_path",
        "painted_path",
        "pattern_path",
        "preview_path",
        "json_path",
        "csv_path",
        "selection_json",
        "settings_json",
        "bead_count",
        "colors_used",
        "cols",
        "rows",
        "original_filename",
        "content_type",
        "source_bytes",
        "source_width",
        "source_height",
        "storage_bytes",
    }
    ASSET_FIELDS = (
        "source_path",
        "mask_path",
        "cutout_path",
        "stylized_path",
        "coloring_path",
        "painted_path",
        "pattern_path",
        "preview_path",
        "json_path",
        "csv_path",
    )

    def __init__(
        self,
        data_dir: str | Path,
        database_url: str | None = None,
        *,
        max_projects_per_user: int = 100,
        max_storage_bytes_per_user: int = 2 * 1024 * 1024 * 1024,
        max_jobs_per_day: int = 100,
        max_concurrent_jobs_per_user: int = 2,
    ):
        self.data_dir = Path(data_dir).resolve()
        self.db_path = self.data_dir / "pindou.sqlite3"
        self.projects_dir = self.data_dir / "projects"
        self.max_projects_per_user = max_projects_per_user
        self.max_storage_bytes_per_user = max_storage_bytes_per_user
        self.max_jobs_per_day = max_jobs_per_day
        self.max_concurrent_jobs_per_user = max_concurrent_jobs_per_user
        configured_url = database_url or os.environ.get("PINDOU_DATABASE_URL", "").strip()
        self.database_url = configured_url or f"sqlite:///{self.db_path}"
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        engine_options: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if self.database_url.startswith("sqlite"):
            engine_options["connect_args"] = {"check_same_thread": False, "timeout": 20}
        self.engine: Engine = create_engine(self.database_url, **engine_options)
        if self.database_url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)
        self.metadata = MetaData()
        self._define_schema()
        self._session_secret: bytes | None = None

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def _define_schema(self) -> None:
        self.users = Table(
            "users",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("email", String(254), nullable=False, unique=True),
            Column("password_hash", Text, nullable=False),
            Column("display_name", String(48), nullable=False),
            Column("bio", String(240), nullable=False, server_default=""),
            Column("role", String(16), nullable=False, server_default="user"),
            Column("status", String(16), nullable=False, server_default="active"),
            Column("preferences_json", Text, nullable=False, server_default="{}"),
            Column("email_verified_at", Text),
            Column("last_login_at", Text),
            Column("last_login_ip", String(64)),
            Column("login_count", Integer, nullable=False, server_default="0"),
            Column("session_version", Integer, nullable=False, server_default="0"),
            Column("created_at", Text, nullable=False),
            Column("updated_at", Text, nullable=False),
        )
        self.projects = Table(
            "projects",
            self.metadata,
            Column("id", String(32), primary_key=True),
            Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            Column("name", String(80), nullable=False),
            Column("status", String(24), nullable=False, server_default="uploaded"),
            Column("source_path", Text, nullable=False),
            Column("mask_path", Text),
            Column("cutout_path", Text),
            Column("stylized_path", Text),
            Column("coloring_path", Text),
            Column("painted_path", Text),
            Column("pattern_path", Text),
            Column("preview_path", Text),
            Column("json_path", Text),
            Column("csv_path", Text),
            Column("original_filename", String(255), nullable=False, server_default=""),
            Column("content_type", String(80), nullable=False, server_default="image/png"),
            Column("source_bytes", Integer, nullable=False, server_default="0"),
            Column("source_width", Integer, nullable=False, server_default="0"),
            Column("source_height", Integer, nullable=False, server_default="0"),
            Column("storage_bytes", Integer, nullable=False, server_default="0"),
            Column("selection_json", Text, nullable=False, server_default="{}"),
            Column("settings_json", Text, nullable=False, server_default="{}"),
            Column("bead_count", Integer, nullable=False, server_default="0"),
            Column("colors_used", Integer, nullable=False, server_default="0"),
            Column("cols", Integer, nullable=False, server_default="36"),
            Column("rows", Integer, nullable=False, server_default="35"),
            Column("created_at", Text, nullable=False),
            Column("updated_at", Text, nullable=False),
        )
        self.activity_logs = Table(
            "activity_logs",
            self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("request_id", String(36), nullable=False),
            Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
            Column("action", String(80), nullable=False),
            Column("category", String(32), nullable=False, server_default="request"),
            Column("status", String(24), nullable=False, server_default="success"),
            Column("method", String(12), nullable=False, server_default=""),
            Column("path", String(500), nullable=False, server_default=""),
            Column("resource_type", String(32), nullable=False, server_default=""),
            Column("resource_id", String(64), nullable=False, server_default=""),
            Column("ip_address", String(64), nullable=False, server_default=""),
            Column("user_agent", String(500), nullable=False, server_default=""),
            Column("input_json", Text, nullable=False, server_default="{}"),
            Column("output_json", Text, nullable=False, server_default="{}"),
            Column("error_message", Text, nullable=False, server_default=""),
            Column("duration_ms", Integer, nullable=False, server_default="0"),
            Column("created_at", Text, nullable=False),
        )
        self.processing_jobs = Table(
            "processing_jobs",
            self.metadata,
            Column("id", String(32), primary_key=True),
            Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
            Column("project_id", String(32), ForeignKey("projects.id", ondelete="SET NULL")),
            Column("operation", String(40), nullable=False),
            Column("provider", String(40), nullable=False, server_default="local"),
            Column("model_name", String(120), nullable=False, server_default=""),
            Column("status", String(24), nullable=False, server_default="running"),
            Column("input_json", Text, nullable=False, server_default="{}"),
            Column("output_json", Text, nullable=False, server_default="{}"),
            Column("error_message", Text, nullable=False, server_default=""),
            Column("duration_ms", Integer, nullable=False, server_default="0"),
            Column("attempts", Integer, nullable=False, server_default="0"),
            Column("worker_id", String(120), nullable=False, server_default=""),
            Column("claimed_at", Text),
            Column("last_heartbeat_at", Text),
            Column("cancel_requested", Integer, nullable=False, server_default="0"),
            Column("started_at", Text, nullable=False),
            Column("completed_at", Text),
        )
        self.user_messages = Table(
            "user_messages",
            self.metadata,
            Column("id", String(32), primary_key=True),
            Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            Column("subject", String(100), nullable=False),
            Column("content", Text, nullable=False),
            Column("status", String(16), nullable=False, server_default="open"),
            Column("admin_note", Text, nullable=False, server_default=""),
            Column("created_at", Text, nullable=False),
            Column("updated_at", Text, nullable=False),
            Column("resolved_at", Text),
        )
        Index("idx_projects_user_updated", self.projects.c.user_id, self.projects.c.updated_at)
        Index("idx_activity_user_created", self.activity_logs.c.user_id, self.activity_logs.c.created_at)
        Index("idx_activity_action_created", self.activity_logs.c.action, self.activity_logs.c.created_at)
        Index("idx_jobs_user_started", self.processing_jobs.c.user_id, self.processing_jobs.c.started_at)
        Index("idx_messages_status_created", self.user_messages.c.status, self.user_messages.c.created_at)

    def initialize(self, *, bootstrap_admin: bool = True) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.metadata.create_all(self.engine)
        self._migrate_legacy_tables()
        if bootstrap_admin:
            self._bootstrap_admin()

    def _migrate_legacy_tables(self) -> None:
        migrations = {
            "users": {
                "role": "VARCHAR(16) NOT NULL DEFAULT 'user'",
                "status": "VARCHAR(16) NOT NULL DEFAULT 'active'",
                "preferences_json": "TEXT NOT NULL DEFAULT '{}'",
                "email_verified_at": "TEXT",
                "last_login_at": "TEXT",
                "last_login_ip": "VARCHAR(64)",
                "login_count": "INTEGER NOT NULL DEFAULT 0",
                "session_version": "INTEGER NOT NULL DEFAULT 0",
            },
            "projects": {
                "coloring_path": "TEXT",
                "painted_path": "TEXT",
                "original_filename": "VARCHAR(255) NOT NULL DEFAULT ''",
                "content_type": "VARCHAR(80) NOT NULL DEFAULT 'image/png'",
                "source_bytes": "INTEGER NOT NULL DEFAULT 0",
                "source_width": "INTEGER NOT NULL DEFAULT 0",
                "source_height": "INTEGER NOT NULL DEFAULT 0",
                "storage_bytes": "INTEGER NOT NULL DEFAULT 0",
            },
            "processing_jobs": {
                "attempts": "INTEGER NOT NULL DEFAULT 0",
                "worker_id": "VARCHAR(120) NOT NULL DEFAULT ''",
                "claimed_at": "TEXT",
                "last_heartbeat_at": "TEXT",
                "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
            },
        }
        schema_inspector = inspect(self.engine)
        with self.engine.begin() as connection:
            for table_name, fields in migrations.items():
                existing = {column["name"] for column in schema_inspector.get_columns(table_name)}
                for column_name, sql_type in fields.items():
                    if column_name not in existing:
                        connection.execute(
                            text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}")
                        )

    def _bootstrap_admin(self) -> None:
        email = os.environ.get("PINDOU_ADMIN_EMAIL", "").strip()
        password = os.environ.get("PINDOU_ADMIN_PASSWORD", "")
        if not email or not password:
            return
        normalized = normalize_email(email)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.users.c.id, self.users.c.role).where(self.users.c.email == normalized)
            ).first()
        created = row is None
        if created:
            user = self.create_user(
                normalized,
                password,
                os.environ.get("PINDOU_ADMIN_NAME", "系统管理员"),
            )
            user_id = user["id"]
        elif row[1] != "admin":
            user_id = int(row[0])
            with self.engine.begin() as connection:
                connection.execute(
                    update(self.users)
                    .where(self.users.c.id == user_id)
                    .values(role="admin", status="active", updated_at=utc_now())
                )
        if created:
            with self.engine.begin() as connection:
                connection.execute(
                    update(self.users)
                    .where(self.users.c.id == user_id)
                    .values(role="admin", updated_at=utc_now())
                )

    @property
    def session_secret(self) -> bytes:
        if self._session_secret is not None:
            return self._session_secret
        configured = os.environ.get("PINDOU_SESSION_SECRET", "").strip()
        if configured:
            self._session_secret = configured.encode("utf-8")
            return self._session_secret
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key_path = self.data_dir / ".session.key"
        if key_path.exists():
            secret = key_path.read_bytes()
        else:
            secret = secrets.token_bytes(48)
            key_path.write_bytes(secret)
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
        self._session_secret = secret
        return secret

    def create_session_token(self, user_id: int, max_age_seconds: int = 30 * 24 * 3600) -> str:
        expires_at = int(datetime.now(timezone.utc).timestamp()) + max_age_seconds
        with self.engine.begin() as connection:
            version = connection.execute(
                select(self.users.c.session_version).where(self.users.c.id == user_id)
            ).scalar_one_or_none()
        payload = f"{int(user_id)}:{int(version or 0)}:{expires_at}"
        signature = hmac.new(self.session_secret, payload.encode("utf-8"), hashlib.sha256).digest()
        raw = payload.encode("utf-8") + b":" + base64.urlsafe_b64encode(signature).rstrip(b"=")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def read_session_token(self, token: str | None) -> int | None:
        if not token:
            return None
        try:
            padded = token + "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
            user_text, version_text, expires_text, signature_text = raw.decode("ascii").split(":", 3)
            payload = f"{user_text}:{version_text}:{expires_text}"
            expected = hmac.new(self.session_secret, payload.encode("utf-8"), hashlib.sha256).digest()
            signature_padded = signature_text + "=" * (-len(signature_text) % 4)
            actual = base64.urlsafe_b64decode(signature_padded.encode("ascii"))
            if not hmac.compare_digest(actual, expected):
                return None
            if int(expires_text) < int(datetime.now(timezone.utc).timestamp()):
                return None
            with self.engine.begin() as connection:
                current_version = connection.execute(
                    select(self.users.c.session_version).where(self.users.c.id == int(user_text))
                ).scalar_one_or_none()
            if current_version is None or int(version_text) != int(current_version):
                return None
            return int(user_text)
        except (ValueError, UnicodeDecodeError, TypeError):
            return None

    def create_user(self, email: str, password: str, display_name: str) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        password_hash = hash_password(password)
        clean_name = display_name.strip() or normalized_email.split("@", 1)[0]
        if len(clean_name) > 48:
            raise ValueError("昵称不能超过 48 个字符")
        now = utc_now()
        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    insert(self.users).values(
                        email=normalized_email,
                        password_hash=password_hash,
                        display_name=clean_name,
                        bio="",
                        role="user",
                        status="active",
                        preferences_json="{}",
                        login_count=0,
                        session_version=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
                user_id = int(result.inserted_primary_key[0])
        except IntegrityError as exc:
            raise ValueError("该邮箱已经注册") from exc
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("Failed to load newly created user")
        return user

    def change_password(self, user_id: int, current_password: str, new_password: str) -> dict[str, Any]:
        validate_password(new_password)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.users.c.password_hash).where(self.users.c.id == user_id)
            ).first()
            if row is None or not verify_password(current_password, row[0]):
                raise ValueError("当前密码不正确")
            connection.execute(
                update(self.users)
                .where(self.users.c.id == user_id)
                .values(
                    password_hash=hash_password(new_password),
                    session_version=self.users.c.session_version + 1,
                    updated_at=utc_now(),
                )
            )
        return self.get_user(user_id) or {}

    def verify_user_password(self, user_id: int, password: str) -> bool:
        with self.engine.begin() as connection:
            password_hash = connection.execute(
                select(self.users.c.password_hash).where(self.users.c.id == user_id)
            ).scalar_one_or_none()
        return bool(password_hash and verify_password(password, password_hash))

    def authenticate(self, email: str, password: str, ip_address: str = "") -> dict[str, Any] | None:
        try:
            normalized_email = normalize_email(email)
        except ValueError:
            return None
        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.users).where(self.users.c.email == normalized_email)
            ).mappings().first()
            if row is None or not verify_password(password, row["password_hash"]):
                return None
            if row["status"] != "active":
                return None
            now = utc_now()
            connection.execute(
                update(self.users)
                .where(self.users.c.id == row["id"])
                .values(
                    last_login_at=now,
                    last_login_ip=ip_address[:64],
                    login_count=int(row["login_count"] or 0) + 1,
                    updated_at=now,
                )
            )
        return self.get_user(int(row["id"]))

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.users).where(self.users.c.id == user_id)
            ).mappings().first()
        return self._public_user(row) if row else None

    def update_user(self, user_id: int, display_name: str, bio: str) -> dict[str, Any]:
        clean_name = display_name.strip()
        clean_bio = bio.strip()
        if not clean_name:
            raise ValueError("昵称不能为空")
        if len(clean_name) > 48:
            raise ValueError("昵称不能超过 48 个字符")
        if len(clean_bio) > 240:
            raise ValueError("个人简介不能超过 240 个字符")
        with self.engine.begin() as connection:
            connection.execute(
                update(self.users)
                .where(self.users.c.id == user_id)
                .values(display_name=clean_name, bio=clean_bio, updated_at=utc_now())
            )
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("用户不存在")
        return user

    def create_project(
        self,
        project_id: str,
        user_id: int,
        name: str,
        source_path: Path,
        *,
        original_filename: str = "",
        content_type: str = "image/png",
        source_bytes: int = 0,
        source_width: int = 0,
        source_height: int = 0,
    ) -> dict[str, Any]:
        clean_name = name.strip()[:80] or "未命名拼豆图"
        now = utc_now()
        actual_bytes = int(source_bytes or source_path.stat().st_size)
        with self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.execute(
                    select(self.users.c.id).where(self.users.c.id == user_id).with_for_update()
                ).first()
            project_count = connection.execute(
                select(func.count(self.projects.c.id)).where(self.projects.c.user_id == user_id)
            ).scalar_one()
            storage_total = connection.execute(
                select(func.coalesce(func.sum(self.projects.c.storage_bytes), 0)).where(
                    self.projects.c.user_id == user_id
                )
            ).scalar_one()
            if int(project_count or 0) >= self.max_projects_per_user:
                raise ValueError("已达到项目数量上限")
            if int(storage_total or 0) + actual_bytes > self.max_storage_bytes_per_user:
                raise ValueError("已达到账户存储空间上限")
            connection.execute(
                insert(self.projects).values(
                    id=project_id,
                    user_id=user_id,
                    name=clean_name,
                    status="uploaded",
                    source_path=str(source_path.resolve()),
                    original_filename=original_filename[:255],
                    content_type=content_type[:80],
                    source_bytes=actual_bytes,
                    source_width=int(source_width),
                    source_height=int(source_height),
                    storage_bytes=actual_bytes,
                    selection_json="{}",
                    settings_json="{}",
                    bead_count=0,
                    colors_used=0,
                    cols=36,
                    rows=35,
                    created_at=now,
                    updated_at=now,
                )
            )
        project = self.get_project(project_id, user_id)
        if project is None:
            raise RuntimeError("Failed to load newly created project")
        return project

    def rename_project(self, project_id: str, user_id: int, name: str) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("项目名称不能为空")
        if len(clean_name) > 80:
            raise ValueError("项目名称不能超过 80 个字符")
        with self.engine.begin() as connection:
            result = connection.execute(
                update(self.projects)
                .where(and_(self.projects.c.id == project_id, self.projects.c.user_id == user_id))
                .values(name=clean_name, updated_at=utc_now())
            )
            if result.rowcount == 0:
                raise ValueError("项目不存在")
        return self.get_project(project_id, user_id) or {}

    def duplicate_project(self, project_id: str, user_id: int, name: str = "") -> dict[str, Any]:
        source = self.get_project(project_id, user_id)
        if source is None:
            raise ValueError("项目不存在")
        new_id = uuid.uuid4().hex
        source_dir = self.projects_dir / str(user_id) / project_id
        if not source_dir.is_dir():
            raise ValueError("项目文件不存在")
        target_dir = self.project_directory(user_id, new_id)
        try:
            if source_dir.is_dir():
                shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
            now = utc_now()
            values = {
                field: source.get(field)
                for field in self.PROJECT_FIELDS
                if field not in {"name", "status", "updated_at", "storage_bytes"}
            }
            values.update(
                id=new_id,
                user_id=user_id,
                name=(name.strip()[:80] or f"{source['name']} 副本"),
                status=source["status"],
                storage_bytes=0,
                created_at=now,
                updated_at=now,
            )
            for field in self.ASSET_FIELDS:
                if source.get(field):
                    values[field] = str(target_dir / Path(str(source[field])).name)
            with self.engine.begin() as connection:
                project_count = connection.execute(
                    select(func.count(self.projects.c.id)).where(self.projects.c.user_id == user_id)
                ).scalar_one()
                storage_total = connection.execute(
                    select(func.coalesce(func.sum(self.projects.c.storage_bytes), 0)).where(
                        self.projects.c.user_id == user_id
                    )
                ).scalar_one()
                copied_bytes = sum(
                    path.stat().st_size for path in target_dir.rglob("*") if path.is_file()
                )
                if int(project_count or 0) >= self.max_projects_per_user:
                    raise ValueError("已达到项目数量上限")
                if int(storage_total or 0) + copied_bytes > self.max_storage_bytes_per_user:
                    raise ValueError("已达到账户存储空间上限")
                values["storage_bytes"] = copied_bytes
                connection.execute(insert(self.projects).values(**values))
            return self.get_project(new_id, user_id) or {}
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

    def list_projects(self, user_id: int) -> list[dict[str, Any]]:
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(self.projects)
                .where(self.projects.c.user_id == user_id)
                .order_by(self.projects.c.updated_at.desc())
            ).mappings().all()
        return [self._project_dict(row) for row in rows]

    def get_project(self, project_id: str, user_id: int) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.projects).where(
                    and_(self.projects.c.id == project_id, self.projects.c.user_id == user_id)
                )
            ).mappings().first()
        return self._project_dict(row) if row else None

    def get_project_admin(self, project_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.projects).where(self.projects.c.id == project_id)
            ).mappings().first()
        return self._project_dict(row) if row else None

    def update_project(self, project_id: str, user_id: int, **fields: Any) -> dict[str, Any]:
        if not fields:
            project = self.get_project(project_id, user_id)
            if project is None:
                raise ValueError("项目不存在")
            return project
        unknown = set(fields) - self.PROJECT_FIELDS
        if unknown:
            raise ValueError(f"Unsupported project fields: {', '.join(sorted(unknown))}")
        values = dict(fields)
        values["updated_at"] = utc_now()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(self.projects)
                .where(and_(self.projects.c.id == project_id, self.projects.c.user_id == user_id))
                .values(**values)
            )
            if result.rowcount == 0:
                raise ValueError("项目不存在")
        project = self.get_project(project_id, user_id)
        if project is None:
            raise ValueError("项目不存在")
        storage_bytes = self._project_storage_bytes(project)
        if storage_bytes != project["storage_bytes"]:
            with self.engine.begin() as connection:
                connection.execute(
                    update(self.projects)
                    .where(self.projects.c.id == project_id)
                    .values(storage_bytes=storage_bytes)
                )
            project["storage_bytes"] = storage_bytes
        return project

    def delete_project(self, project_id: str, user_id: int) -> dict[str, Any] | None:
        project = self.get_project(project_id, user_id)
        if project is None:
            return None
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.projects).where(
                    and_(self.projects.c.id == project_id, self.projects.c.user_id == user_id)
                )
            )
        return project

    def delete_user(self, user_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(self.users).where(self.users.c.id == user_id))

    def cancel_project_jobs(self, project_id: str, user_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(self.processing_jobs)
                .where(
                    and_(
                        self.processing_jobs.c.project_id == project_id,
                        self.processing_jobs.c.user_id == user_id,
                        self.processing_jobs.c.status == "queued",
                    )
                )
                .values(status="failed", error_message="项目已删除", completed_at=utc_now())
            )
            connection.execute(
                update(self.processing_jobs)
                .where(
                    and_(
                        self.processing_jobs.c.project_id == project_id,
                        self.processing_jobs.c.user_id == user_id,
                        self.processing_jobs.c.status == "running",
                    )
                )
                .values(cancel_requested=1)
            )

    def count_admins(self) -> int:
        with self.engine.begin() as connection:
            return int(
                connection.execute(
                    select(func.count(self.users.c.id)).where(
                        and_(self.users.c.role == "admin", self.users.c.status == "active")
                    )
                ).scalar_one()
                or 0
            )

    def project_directory(self, user_id: int, project_id: str) -> Path:
        directory = self.projects_dir / str(user_id) / project_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def user_dashboard(self, user_id: int) -> dict[str, int]:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(
                    func.count(self.projects.c.id).label("projects"),
                    func.coalesce(func.sum(self.projects.c.storage_bytes), 0).label("storage_bytes"),
                    func.coalesce(func.sum(self.projects.c.bead_count), 0).label("beads"),
                ).where(self.projects.c.user_id == user_id)
            ).mappings().one()
            activity_count = connection.execute(
                select(func.count(self.activity_logs.c.id)).where(
                    self.activity_logs.c.user_id == user_id
                )
            ).scalar_one()
        return {
            "projects": int(row["projects"] or 0),
            "storage_bytes": int(row["storage_bytes"] or 0),
            "beads": int(row["beads"] or 0),
            "activities": int(activity_count or 0),
        }

    def record_activity(
        self,
        *,
        user_id: int | None,
        action: str,
        category: str = "request",
        status: str = "success",
        request_id: str | None = None,
        method: str = "",
        path: str = "",
        resource_type: str = "",
        resource_id: str = "",
        ip_address: str = "",
        user_agent: str = "",
        input_data: Any = None,
        output_data: Any = None,
        error_message: str = "",
        duration_ms: int = 0,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.activity_logs).values(
                    request_id=(request_id or uuid.uuid4().hex)[:36],
                    user_id=user_id,
                    action=action[:80],
                    category=category[:32],
                    status=status[:24],
                    method=method[:12],
                    path=path[:500],
                    resource_type=resource_type[:32],
                    resource_id=resource_id[:64],
                    ip_address=ip_address[:64],
                    user_agent=user_agent[:500],
                    input_json=_json_dump(input_data),
                    output_json=_json_dump(output_data),
                    error_message=error_message[:4000],
                    duration_ms=max(0, int(duration_ms)),
                    created_at=utc_now(),
                )
            )

    def list_activity(
        self,
        *,
        user_id: int | None = None,
        action: str = "",
        status: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(
                self.activity_logs,
                self.users.c.email.label("user_email"),
                self.users.c.display_name.label("user_name"),
            )
            .select_from(
                self.activity_logs.outerjoin(
                    self.users, self.activity_logs.c.user_id == self.users.c.id
                )
            )
            .order_by(self.activity_logs.c.created_at.desc())
            .limit(min(max(limit, 1), 500))
            .offset(max(offset, 0))
        )
        conditions = []
        if user_id is not None:
            conditions.append(self.activity_logs.c.user_id == user_id)
        if action:
            conditions.append(self.activity_logs.c.action.ilike(f"%{action[:80]}%"))
        if status:
            conditions.append(self.activity_logs.c.status == status)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        with self.engine.begin() as connection:
            rows = connection.execute(stmt).mappings().all()
        return [self._activity_dict(row) for row in rows]

    def start_job(
        self,
        user_id: int,
        project_id: str,
        operation: str,
        *,
        provider: str = "local",
        model_name: str = "",
        input_data: Any = None,
        status: str = "running",
    ) -> str:
        job_id = uuid.uuid4().hex
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.processing_jobs).values(
                    id=job_id,
                    user_id=user_id,
                    project_id=project_id,
                    operation=operation[:40],
                    provider=provider[:40],
                    model_name=model_name[:120],
                    status=status[:24],
                    input_json=_json_dump(input_data),
                    output_json="{}",
                    error_message="",
                    duration_ms=0,
                    started_at=utc_now(),
                    last_heartbeat_at=None,
                    cancel_requested=0,
                )
            )
        return job_id

    def enqueue_job(
        self,
        user_id: int,
        project_id: str,
        operation: str,
        *,
        provider: str = "local",
        model_name: str = "",
        input_data: Any = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        with self.engine.begin() as connection:
            project_lock = select(self.projects.c.id).where(
                and_(self.projects.c.id == project_id, self.projects.c.user_id == user_id)
            )
            if self.engine.dialect.name == "postgresql":
                project_lock = project_lock.with_for_update()
            if connection.execute(project_lock).first() is None:
                raise ValueError("项目不存在")
            active = connection.execute(
                select(self.processing_jobs.c.id).where(
                    and_(
                        self.processing_jobs.c.project_id == project_id,
                        self.processing_jobs.c.status.in_(("queued", "running")),
                    )
                ).limit(1)
            ).first()
            if active is not None:
                raise ValueError("该项目已有处理任务，请等待任务完成")
            concurrent = connection.execute(
                select(func.count(self.processing_jobs.c.id)).where(
                    and_(
                        self.processing_jobs.c.user_id == user_id,
                        self.processing_jobs.c.status.in_(("queued", "running")),
                    )
                )
            ).scalar_one()
            if int(concurrent or 0) >= self.max_concurrent_jobs_per_user:
                raise ValueError("当前已有多个处理任务，请等待任务完成")
            today_prefix = datetime.now(timezone.utc).date().isoformat()
            daily = connection.execute(
                select(func.count(self.processing_jobs.c.id)).where(
                    and_(
                        self.processing_jobs.c.user_id == user_id,
                        self.processing_jobs.c.started_at >= today_prefix,
                    )
                )
            ).scalar_one()
            if int(daily or 0) >= self.max_jobs_per_day:
                raise ValueError("今日处理次数已达上限")
            connection.execute(
                insert(self.processing_jobs).values(
                    id=job_id,
                    user_id=user_id,
                    project_id=project_id,
                    operation=operation[:40],
                    provider=provider[:40],
                    model_name=model_name[:120],
                    status="queued",
                    input_json=_json_dump(input_data),
                    output_json="{}",
                    error_message="",
                    duration_ms=0,
                    last_heartbeat_at=None,
                    cancel_requested=0,
                    started_at=utc_now(),
                )
            )
        return job_id

    def claim_next_job(self, worker_id: str) -> dict[str, Any] | None:
        """Atomically claim one queued job; PostgreSQL workers use SKIP LOCKED."""
        with self.engine.begin() as connection:
            stmt = (
                select(self.processing_jobs.c.id)
                .where(self.processing_jobs.c.status == "queued")
                .order_by(self.processing_jobs.c.started_at.asc())
                .limit(1)
            )
            if self.engine.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)
            row = connection.execute(stmt).first()
            if row is None:
                return None
            job_id = str(row[0])
            result = connection.execute(
                update(self.processing_jobs)
                .where(
                    and_(
                        self.processing_jobs.c.id == job_id,
                        self.processing_jobs.c.status == "queued",
                    )
                )
                .values(
                    status="running",
                    worker_id=worker_id[:120],
                    claimed_at=utc_now(),
                    last_heartbeat_at=utc_now(),
                    attempts=self.processing_jobs.c.attempts + 1,
                    cancel_requested=0,
                )
            )
            if result.rowcount != 1:
                return None
        return self.get_job(job_id)

    def claim_job(self, job_id: str, worker_id: str) -> dict[str, Any] | None:
        """Claim a known queued job, used by the local eager development mode."""
        with self.engine.begin() as connection:
            result = connection.execute(
                update(self.processing_jobs)
                .where(
                    and_(
                        self.processing_jobs.c.id == job_id,
                        self.processing_jobs.c.status == "queued",
                    )
                )
                .values(
                    status="running",
                    worker_id=worker_id[:120],
                    claimed_at=utc_now(),
                    last_heartbeat_at=utc_now(),
                    attempts=self.processing_jobs.c.attempts + 1,
                    cancel_requested=0,
                )
            )
            if result.rowcount != 1:
                return None
        return self.get_job(job_id)

    def requeue_stale_jobs(self, stale_after_seconds: int, *, max_attempts: int | None = None) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)).isoformat(
            timespec="seconds"
        )
        with self.engine.begin() as connection:
            conditions = [
                self.processing_jobs.c.status == "running",
                self.processing_jobs.c.cancel_requested == 0,
                or_(
                    self.processing_jobs.c.last_heartbeat_at < cutoff,
                    and_(
                        self.processing_jobs.c.last_heartbeat_at.is_(None),
                        self.processing_jobs.c.claimed_at < cutoff,
                    ),
                ),
            ]
            if max_attempts is not None:
                conditions.append(self.processing_jobs.c.attempts < max_attempts)
            result = connection.execute(
                update(self.processing_jobs)
                .where(and_(*conditions))
                .values(status="queued", worker_id="", claimed_at=None, last_heartbeat_at=None)
            )
        return int(result.rowcount or 0)

    def retry_job(self, job_id: str, *, max_attempts: int, error_message: str = "") -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(self.processing_jobs)
                .where(
                    and_(
                        self.processing_jobs.c.id == job_id,
                        self.processing_jobs.c.status == "failed",
                        self.processing_jobs.c.attempts < max_attempts,
                    )
                )
                .values(
                    status="queued",
                    worker_id="",
                    claimed_at=None,
                    last_heartbeat_at=None,
                    completed_at=None,
                    error_message=error_message[:4000],
                )
            )
        return bool(result.rowcount)

    def touch_job(self, job_id: str, worker_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(self.processing_jobs)
                .where(
                    and_(
                        self.processing_jobs.c.id == job_id,
                        self.processing_jobs.c.status == "running",
                        self.processing_jobs.c.worker_id == worker_id,
                    )
                )
                .values(last_heartbeat_at=utc_now())
            )

    def request_cancel_job(self, job_id: str, user_id: int) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.processing_jobs).where(
                    and_(self.processing_jobs.c.id == job_id, self.processing_jobs.c.user_id == user_id)
                )
            ).mappings().first()
            if row is None:
                return None
            if row["status"] == "queued":
                connection.execute(
                    update(self.processing_jobs)
                    .where(self.processing_jobs.c.id == job_id)
                    .values(
                        status="failed",
                        error_message="用户已取消任务",
                        completed_at=utc_now(),
                    )
                )
            elif row["status"] == "running":
                connection.execute(
                    update(self.processing_jobs)
                    .where(self.processing_jobs.c.id == job_id)
                    .values(cancel_requested=1)
                )
        return self.get_job(job_id, user_id=user_id)

    def is_job_cancel_requested(self, job_id: str) -> bool:
        with self.engine.begin() as connection:
            value = connection.execute(
                select(self.processing_jobs.c.cancel_requested).where(
                    self.processing_jobs.c.id == job_id
                )
            ).scalar_one_or_none()
        return bool(value)

    def get_job(self, job_id: str, *, user_id: int | None = None) -> dict[str, Any] | None:
        stmt = select(self.processing_jobs).where(self.processing_jobs.c.id == job_id)
        if user_id is not None:
            stmt = stmt.where(self.processing_jobs.c.user_id == user_id)
        with self.engine.begin() as connection:
            row = connection.execute(stmt).mappings().first()
        if row is None:
            return None
        return {
            **dict(row),
            "input": _json_load(row["input_json"], {}),
            "output": _json_load(row["output_json"], {}),
        }

    def finish_job(
        self,
        job_id: str,
        *,
        status: str,
        output_data: Any = None,
        error_message: str = "",
        duration_ms: int = 0,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(self.processing_jobs)
                .where(self.processing_jobs.c.id == job_id)
                .values(
                    status=status[:24],
                    output_json=_json_dump(output_data),
                    error_message=error_message[:4000],
                    duration_ms=max(0, int(duration_ms)),
                    completed_at=utc_now(),
                    last_heartbeat_at=None,
                )
            )

    def list_jobs(self, *, user_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        stmt = (
            select(
                self.processing_jobs,
                self.users.c.email.label("user_email"),
                self.projects.c.name.label("project_name"),
            )
            .select_from(
                self.processing_jobs.outerjoin(
                    self.users, self.processing_jobs.c.user_id == self.users.c.id
                ).outerjoin(
                    self.projects, self.processing_jobs.c.project_id == self.projects.c.id
                )
            )
            .order_by(self.processing_jobs.c.started_at.desc())
            .limit(min(max(limit, 1), 500))
        )
        if user_id is not None:
            stmt = stmt.where(self.processing_jobs.c.user_id == user_id)
        with self.engine.begin() as connection:
            rows = connection.execute(stmt).mappings().all()
        return [
            {
                **dict(row),
                "input": _json_load(row["input_json"], {}),
                "output": _json_load(row["output_json"], {}),
            }
            for row in rows
        ]

    def create_message(self, user_id: int, subject: str, content: str) -> dict[str, Any]:
        clean_subject = subject.strip()[:100]
        clean_content = content.strip()
        if not clean_subject:
            raise ValueError("请填写消息标题")
        if not clean_content:
            raise ValueError("请填写消息内容")
        if len(clean_content) > 2000:
            raise ValueError("消息内容不能超过 2000 个字符")
        message_id = uuid.uuid4().hex
        now = utc_now()
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.user_messages).values(
                    id=message_id,
                    user_id=user_id,
                    subject=clean_subject,
                    content=clean_content,
                    status="open",
                    admin_note="",
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get_message(message_id, user_id=user_id) or {}

    def get_message(self, message_id: str, *, user_id: int | None = None) -> dict[str, Any] | None:
        stmt = select(self.user_messages).where(self.user_messages.c.id == message_id)
        if user_id is not None:
            stmt = stmt.where(self.user_messages.c.user_id == user_id)
        with self.engine.begin() as connection:
            row = connection.execute(stmt).mappings().first()
        return dict(row) if row else None

    def list_messages(
        self,
        *,
        user_id: int | None = None,
        status: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(
                self.user_messages,
                self.users.c.email.label("user_email"),
                self.users.c.display_name.label("user_name"),
            )
            .select_from(
                self.user_messages.join(
                    self.users, self.user_messages.c.user_id == self.users.c.id
                )
            )
            .order_by(self.user_messages.c.created_at.desc())
            .limit(min(max(limit, 1), 500))
        )
        conditions = []
        if user_id is not None:
            conditions.append(self.user_messages.c.user_id == user_id)
        if status:
            conditions.append(self.user_messages.c.status == status)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        with self.engine.begin() as connection:
            rows = connection.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def update_message_admin(self, message_id: str, status: str, admin_note: str) -> dict[str, Any]:
        if status not in MESSAGE_STATUSES:
            raise ValueError("消息状态无效")
        now = utc_now()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(self.user_messages)
                .where(self.user_messages.c.id == message_id)
                .values(
                    status=status,
                    admin_note=admin_note.strip()[:2000],
                    updated_at=now,
                    resolved_at=now if status == "resolved" else None,
                )
            )
            if result.rowcount == 0:
                raise ValueError("消息不存在")
        return self.get_message(message_id) or {}

    def admin_overview(self) -> dict[str, int]:
        with self.engine.begin() as connection:
            users = connection.execute(select(func.count(self.users.c.id))).scalar_one()
            projects = connection.execute(select(func.count(self.projects.c.id))).scalar_one()
            storage = connection.execute(
                select(func.coalesce(func.sum(self.projects.c.storage_bytes), 0))
            ).scalar_one()
            activities = connection.execute(
                select(func.count(self.activity_logs.c.id))
            ).scalar_one()
            failed = connection.execute(
                select(func.count(self.activity_logs.c.id)).where(
                    self.activity_logs.c.status == "failed"
                )
            ).scalar_one()
            messages = connection.execute(
                select(func.count(self.user_messages.c.id)).where(
                    self.user_messages.c.status != "resolved"
                )
            ).scalar_one()
            model_jobs = connection.execute(
                select(func.count(self.processing_jobs.c.id)).where(
                    self.processing_jobs.c.provider == "model"
                )
            ).scalar_one()
        return {
            "users": int(users or 0),
            "projects": int(projects or 0),
            "storage_bytes": int(storage or 0),
            "activities": int(activities or 0),
            "failed_requests": int(failed or 0),
            "open_messages": int(messages or 0),
            "model_jobs": int(model_jobs or 0),
        }

    def list_admin_users(
        self,
        *,
        query: str = "",
        status: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(
                self.users,
                func.count(self.projects.c.id).label("project_count"),
                func.coalesce(func.sum(self.projects.c.storage_bytes), 0).label("storage_bytes"),
            )
            .select_from(
                self.users.outerjoin(self.projects, self.users.c.id == self.projects.c.user_id)
            )
            .group_by(*list(self.users.c))
            .order_by(self.users.c.created_at.desc())
            .limit(min(max(limit, 1), 500))
            .offset(max(offset, 0))
        )
        conditions = []
        if query:
            needle = f"%{query.strip()[:100]}%"
            conditions.append(
                or_(self.users.c.email.ilike(needle), self.users.c.display_name.ilike(needle))
            )
        if status:
            conditions.append(self.users.c.status == status)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        with self.engine.begin() as connection:
            rows = connection.execute(stmt).mappings().all()
        return [
            {
                **self._public_user(row),
                "project_count": int(row["project_count"] or 0),
                "storage_bytes": int(row["storage_bytes"] or 0),
            }
            for row in rows
        ]

    def update_user_admin(self, user_id: int, *, role: str, status: str) -> dict[str, Any]:
        if role not in USER_ROLES:
            raise ValueError("用户角色无效")
        if status not in USER_STATUSES:
            raise ValueError("用户状态无效")
        current = self.get_user(user_id)
        if current is None:
            raise ValueError("用户不存在")
        if current["role"] == "admin" and current["status"] == "active" and (
            role != "admin" or status != "active"
        ) and self.count_admins() <= 1:
            raise ValueError("不能停用或降级最后一个管理员")
        with self.engine.begin() as connection:
            result = connection.execute(
                update(self.users)
                .where(self.users.c.id == user_id)
                .values(role=role, status=status, updated_at=utc_now())
            )
            if result.rowcount == 0:
                raise ValueError("用户不存在")
        user = self.get_user(user_id)
        if user is None:
            raise ValueError("用户不存在")
        return user

    def list_admin_projects(self, *, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        stmt = (
            select(
                self.projects,
                self.users.c.email.label("user_email"),
                self.users.c.display_name.label("user_name"),
            )
            .select_from(self.projects.join(self.users, self.projects.c.user_id == self.users.c.id))
            .order_by(self.projects.c.updated_at.desc())
            .limit(min(max(limit, 1), 500))
        )
        if query:
            needle = f"%{query.strip()[:100]}%"
            stmt = stmt.where(
                or_(
                    self.projects.c.name.ilike(needle),
                    self.users.c.email.ilike(needle),
                    self.users.c.display_name.ilike(needle),
                )
            )
        with self.engine.begin() as connection:
            rows = connection.execute(stmt).mappings().all()
        return [
            {
                **self._project_dict(row),
                "user_email": row["user_email"],
                "user_name": row["user_name"],
            }
            for row in rows
        ]

    def _project_storage_bytes(self, project: Mapping[str, Any]) -> int:
        paths = {project.get(field) for field in self.ASSET_FIELDS if project.get(field)}
        total = 0
        for value in paths:
            try:
                path = Path(str(value)).resolve()
                if path.is_relative_to(self.data_dir) and path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total

    @staticmethod
    def _public_user(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "email": row["email"],
            "display_name": row["display_name"],
            "bio": row["bio"],
            "role": row.get("role") or "user",
            "status": row.get("status") or "active",
            "preferences": _json_load(row.get("preferences_json"), {}),
            "email_verified_at": row.get("email_verified_at"),
            "last_login_at": row.get("last_login_at"),
            "last_login_ip": row.get("last_login_ip"),
            "login_count": int(row.get("login_count") or 0),
            "created_at": row["created_at"],
            "updated_at": row.get("updated_at"),
        }

    def _project_dict(self, row: Mapping[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data["selection"] = _json_load(data.pop("selection_json", "{}"), {})
        data["settings"] = _json_load(data.pop("settings_json", "{}"), {})
        for field in self.ASSET_FIELDS:
            data[field] = data.get(field) or None
        for field in (
            "source_bytes",
            "source_width",
            "source_height",
            "storage_bytes",
            "bead_count",
            "colors_used",
            "cols",
            "rows",
        ):
            data[field] = int(data.get(field) or 0)
        return data

    @staticmethod
    def _activity_dict(row: Mapping[str, Any]) -> dict[str, Any]:
        data = dict(row)
        data["input"] = _json_load(data.pop("input_json", "{}"), {})
        data["output"] = _json_load(data.pop("output_json", "{}"), {})
        return data
