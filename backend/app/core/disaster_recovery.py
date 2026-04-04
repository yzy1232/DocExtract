"""Disaster detection and emergency recovery utilities."""

import asyncio
import logging
import mimetypes
import re
from datetime import datetime, timezone
from typing import Any

import pymysql
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cache import close_redis, get_redis
from app.core.init_defaults import (
    ensure_default_llm_system_config,
    ensure_default_roles_and_admin,
    mark_system_bootstrap_completed,
)
from app.core.storage import ensure_buckets, storage
from app.database import AsyncSessionLocal, create_tables, drop_tables, engine
from app.models.document import Document, DocumentFormat, DocumentStatus
from app.models.extraction import ExtractionTask  # noqa: F401
from app.models.system import LLMConfig, SystemConfig  # noqa: F401
from app.models.template import Template  # noqa: F401
from app.models.user import Role, User  # noqa: F401

logger = logging.getLogger("app.disaster_recovery")

REQUIRED_TABLES = {
    "users",
    "roles",
    "user_roles",
    "system_configs",
    "llm_configs",
    "templates",
    "documents",
    "extraction_tasks",
}

RECOVERABLE_DOC_KEY_RE = re.compile(
    r"^documents/(?P<doc_id>[0-9a-fA-F-]{36})/original(?P<ext>\.[^/]+)$"
)

WEAK_PASSWORDS = {
    "",
    "123456",
    "12345678",
    "123456789",
    "admin",
    "admin123",
    "password",
    "root",
    "root123",
    "docpassword",
    "qwerty",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _severity_rank(level: str) -> int:
    return {"none": 0, "info": 1, "warning": 2, "critical": 3}.get(level, 0)


def _merge_severity(current: str, candidate: str) -> str:
    if _severity_rank(candidate) > _severity_rank(current):
        return candidate
    return current


def _normalize_redis_role(raw: Any) -> str:
    role = str(raw or "unknown").strip().lower()
    if role == "slave":
        return "replica"
    return role


def _guess_document_format(ext: str) -> DocumentFormat:
    ext = ext.lower()
    mapping = {
        ".pdf": DocumentFormat.PDF,
        ".docx": DocumentFormat.DOCX,
        ".xlsx": DocumentFormat.XLSX,
        ".txt": DocumentFormat.TXT,
        ".md": DocumentFormat.TXT,
    }
    if ext in mapping:
        return mapping[ext]
    if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
        return DocumentFormat.IMAGE
    return DocumentFormat.UNKNOWN


def _guess_mime_type(ext: str) -> str:
    ext = ext.lower()
    if ext == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    mime_type, _ = mimetypes.guess_type(f"file{ext}")
    return mime_type or "application/octet-stream"


async def _fetch_table_names() -> set[str]:
    async with engine.connect() as conn:
        if conn.dialect.name == "mysql":
            query = text(
                """
                SELECT TABLE_NAME
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                """
            )
        elif conn.dialect.name == "postgresql":
            query = text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = current_schema()
                """
            )
        else:
            query = text("SELECT name FROM sqlite_master WHERE type='table'")

        result = await conn.execute(query)
        return {str(name) for name in result.scalars().all()}


async def _check_database_state(db: AsyncSession | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "connected": False,
        "table_count": 0,
        "missing_tables": [],
        "superuser_count": None,
        "bootstrap_completed": None,
        "error": None,
    }

    own_session = False
    session = db
    try:
        if session is None:
            own_session = True
            session = AsyncSessionLocal()

        await session.execute(text("SELECT 1"))
        state["connected"] = True

        table_names = await _fetch_table_names()
        state["table_count"] = len(table_names)
        state["missing_tables"] = sorted(REQUIRED_TABLES - table_names)

        if "users" in table_names:
            superuser_count = await session.execute(
                select(func.count(User.id)).where(User.is_superuser.is_(True))
            )
            state["superuser_count"] = int(superuser_count.scalar() or 0)

        if "system_configs" in table_names:
            bootstrap_cfg = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == "system_bootstrap_done")
            )
            marker = bootstrap_cfg.scalar_one_or_none()
            state["bootstrap_completed"] = bool(marker and str(marker) == "1")
    except Exception as exc:
        state["error"] = str(exc)
    finally:
        if own_session and session is not None:
            await session.close()

    return state


async def _check_redis_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "connected": False,
        "role": "unknown",
        "is_replica": None,
        "error": None,
    }

    try:
        redis = await get_redis()
        await redis.ping()
        state["connected"] = True

        info = await redis.info(section="replication")
        role = _normalize_redis_role(info.get("role"))
        state["role"] = role
        state["is_replica"] = role == "replica"
    except Exception as exc:
        state["error"] = str(exc)

    return state


def _collect_credential_risks() -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []

    db_password = (settings.DB_PASSWORD or "").strip()
    if db_password.lower() in WEAK_PASSWORDS:
        risks.append(
            {
                "level": "warning",
                "code": "weak_db_password",
                "message": "Database password appears weak. Rotate credentials immediately.",
                "auto_fixable": False,
            }
        )

    admin_password = (settings.DEFAULT_ADMIN_PASSWORD or "").strip()
    if admin_password.lower() in WEAK_PASSWORDS:
        risks.append(
            {
                "level": "warning",
                "code": "weak_default_admin_password",
                "message": "Default admin password appears weak. Change it after recovery.",
                "auto_fixable": False,
            }
        )

    if not (settings.REDIS_PASSWORD or "").strip():
        risks.append(
            {
                "level": "warning",
                "code": "redis_password_empty",
                "message": "Redis password is empty. Configure REDIS_PASSWORD.",
                "auto_fixable": False,
            }
        )

    return risks


async def _scan_storage_recovery_candidates(scan_limit: int) -> dict[str, Any]:
    state: dict[str, Any] = {
        "checked": False,
        "bucket": settings.STORAGE_BUCKET_DOCUMENTS,
        "scan_limit": scan_limit,
        "scanned_objects": 0,
        "recoverable_documents": 0,
        "error": None,
    }

    try:
        objects = await asyncio.to_thread(
            storage.list_objects,
            settings.STORAGE_BUCKET_DOCUMENTS,
            "documents/",
            True,
            scan_limit,
        )
        state["checked"] = True
        state["scanned_objects"] = len(objects)

        recoverable = 0
        for obj in objects:
            key = str(obj.get("object_name") or "")
            if RECOVERABLE_DOC_KEY_RE.match(key):
                recoverable += 1
        state["recoverable_documents"] = recoverable
    except Exception as exc:
        state["error"] = str(exc)

    return state


async def detect_disaster_state(
    db: AsyncSession | None = None,
    detailed: bool = True,
) -> dict[str, Any]:
    """Detect high-risk disaster conditions in database and redis."""

    scan_limit = int(getattr(settings, "DISASTER_RECOVERY_SCAN_LIMIT", 5000) or 5000)
    scan_limit = max(100, min(scan_limit, 50000))

    database_state = await _check_database_state(db)
    redis_state = await _check_redis_state()

    risk_items: list[dict[str, Any]] = []
    severity = "none"

    if not database_state.get("connected"):
        risk_items.append(
            {
                "level": "critical",
                "code": "database_unavailable",
                "message": "Database is unavailable.",
                "auto_fixable": False,
            }
        )
        severity = _merge_severity(severity, "critical")
    else:
        missing_tables = database_state.get("missing_tables") or []
        if missing_tables:
            risk_items.append(
                {
                    "level": "critical",
                    "code": "database_tables_missing",
                    "message": "Core database tables are missing.",
                    "details": missing_tables,
                    "auto_fixable": True,
                }
            )
            severity = _merge_severity(severity, "critical")

        if database_state.get("superuser_count") == 0:
            risk_items.append(
                {
                    "level": "critical",
                    "code": "superuser_missing",
                    "message": "No superuser account found.",
                    "auto_fixable": True,
                }
            )
            severity = _merge_severity(severity, "critical")

    if not redis_state.get("connected"):
        risk_items.append(
            {
                "level": "warning",
                "code": "redis_unavailable",
                "message": "Redis is unavailable.",
                "auto_fixable": False,
            }
        )
        severity = _merge_severity(severity, "warning")
    elif redis_state.get("is_replica"):
        risk_items.append(
            {
                "level": "critical",
                "code": "redis_is_replica",
                "message": "Redis is running as replica. It should be promoted to master.",
                "auto_fixable": True,
            }
        )
        severity = _merge_severity(severity, "critical")

    for risk in _collect_credential_risks():
        risk_items.append(risk)
        severity = _merge_severity(severity, str(risk.get("level") or "warning"))

    storage_state = {
        "checked": False,
        "bucket": settings.STORAGE_BUCKET_DOCUMENTS,
        "scan_limit": scan_limit,
        "scanned_objects": 0,
        "recoverable_documents": 0,
        "error": None,
    }

    if detailed:
        storage_state = await _scan_storage_recovery_candidates(scan_limit)

    return {
        "checked_at": _utc_now_iso(),
        "severity": severity,
        "has_critical": any(item.get("level") == "critical" for item in risk_items),
        "database": database_state,
        "redis": redis_state,
        "storage": storage_state,
        "risk_items": risk_items,
        "recommendation": "run_emergency_repair" if risk_items else "system_healthy",
    }


async def _repair_redis(
    reset_data: bool,
    promote_to_master: bool,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "success": False,
        "requested": {
            "reset_data": bool(reset_data),
            "promote_to_master": bool(promote_to_master),
        },
        "before": {},
        "after": {},
        "actions": [],
        "errors": [],
    }

    try:
        redis = await get_redis()
        await redis.ping()

        before_info = await redis.info(section="replication")
        before_role = _normalize_redis_role(before_info.get("role"))
        detail["before"] = {"role": before_role}

        if promote_to_master and before_role == "replica":
            await redis.execute_command("REPLICAOF", "NO", "ONE")
            detail["actions"].append("replicaof_no_one")

        if reset_data:
            try:
                await redis.flushall()
                detail["actions"].append("flushall")
            except Exception as flush_exc:
                detail["errors"].append(f"flushall_failed: {flush_exc}")
                await redis.flushdb()
                detail["actions"].append("flushdb")

        after_info = await redis.info(section="replication")
        after_role = _normalize_redis_role(after_info.get("role"))
        detail["after"] = {"role": after_role}
        detail["success"] = True
    except Exception as exc:
        detail["errors"].append(str(exc))

    return detail


async def _ensure_database_schema_exists() -> dict[str, Any]:
    """Create target schema when MySQL database is missing."""

    detail: dict[str, Any] = {
        "dialect": engine.dialect.name,
        "database": settings.DB_NAME,
        "status": "skipped",
        "error": None,
    }

    if engine.dialect.name != "mysql":
        return detail

    db_name = (settings.DB_NAME or "").strip()
    if not db_name:
        detail["status"] = "error"
        detail["error"] = "DB_NAME is empty"
        return detail

    safe_db_name = db_name.replace("`", "``")

    def _create_database() -> None:
        conn = pymysql.connect(
            host=settings.DB_HOST,
            port=int(settings.DB_PORT),
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            charset="utf8mb4",
            autocommit=True,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{safe_db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_create_database)
        detail["status"] = "ok"
    except Exception as exc:
        detail["status"] = "error"
        detail["error"] = str(exc)

    return detail


async def recover_documents_from_storage(
    db: AsyncSession,
    scan_limit: int,
) -> dict[str, Any]:
    """Rebuild minimum document rows from object storage keys."""

    scan_limit = max(100, min(int(scan_limit or 5000), 50000))

    summary: dict[str, Any] = {
        "scan_limit": scan_limit,
        "scanned_objects": 0,
        "candidate_documents": 0,
        "recovered_documents": 0,
        "skipped_existing": 0,
        "errors": [],
    }

    try:
        objects = await asyncio.to_thread(
            storage.list_objects,
            settings.STORAGE_BUCKET_DOCUMENTS,
            "documents/",
            True,
            scan_limit,
        )
    except Exception as exc:
        summary["errors"].append(f"list_objects_failed: {exc}")
        return summary

    summary["scanned_objects"] = len(objects)

    candidates: list[dict[str, Any]] = []
    for item in objects:
        key = str(item.get("object_name") or "")
        match = RECOVERABLE_DOC_KEY_RE.match(key)
        if not match:
            continue
        candidates.append(
            {
                "doc_id": match.group("doc_id"),
                "ext": (match.group("ext") or "").lower(),
                "object_name": key,
                "size": int(item.get("size") or 0),
                "etag": item.get("etag"),
                "last_modified": item.get("last_modified"),
            }
        )

    summary["candidate_documents"] = len(candidates)
    if not candidates:
        return summary

    existing_ids_result = await db.execute(select(Document.id))
    existing_ids = set(existing_ids_result.scalars().all())

    for candidate in candidates:
        doc_id = candidate["doc_id"]
        if doc_id in existing_ids:
            summary["skipped_existing"] += 1
            continue

        ext = candidate["ext"]
        fallback_name = f"recovered_{doc_id}{ext}"
        created_at = candidate.get("last_modified")
        if isinstance(created_at, datetime) and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        document = Document(
            id=doc_id,
            owner_id=None,
            name=fallback_name,
            display_name=fallback_name,
            format=_guess_document_format(ext),
            mime_type=_guess_mime_type(ext),
            file_size=candidate["size"],
            file_hash=candidate.get("etag") if len(str(candidate.get("etag") or "")) == 64 else None,
            storage_path=candidate["object_name"],
            storage_bucket=settings.STORAGE_BUCKET_DOCUMENTS,
            status=DocumentStatus.UPLOADED,
            tags=["recovered"],
            created_at=created_at or datetime.now(timezone.utc),
        )
        db.add(document)
        existing_ids.add(doc_id)
        summary["recovered_documents"] += 1

        if summary["recovered_documents"] % 200 == 0:
            await db.flush()

    await db.flush()
    return summary


async def soft_restart_runtime() -> dict[str, Any]:
    """Reload runtime dependencies without terminating the process."""

    result: dict[str, Any] = {
        "database": "unknown",
        "redis": "unknown",
        "storage": "unknown",
        "errors": [],
    }

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        result["database"] = "ok"
    except Exception as exc:
        result["database"] = "error"
        result["errors"].append(f"database_check_failed: {exc}")

    try:
        await close_redis()
        redis = await get_redis()
        await redis.ping()
        result["redis"] = "ok"
    except Exception as exc:
        result["redis"] = "error"
        result["errors"].append(f"redis_reload_failed: {exc}")

    try:
        await asyncio.to_thread(ensure_buckets)
        result["storage"] = "ok"
    except Exception as exc:
        result["storage"] = "error"
        result["errors"].append(f"storage_reload_failed: {exc}")

    return result


async def run_emergency_repair(
    rebuild_database: bool = True,
    rebuild_redis: bool = True,
    recover_documents: bool = True,
    promote_redis_to_master: bool = True,
    restart_runtime: bool = True,
    dry_run: bool = False,
    scan_limit: int | None = None,
) -> dict[str, Any]:
    """Execute emergency recovery workflow."""

    started_at = _utc_now_iso()
    effective_scan_limit = int(scan_limit or settings.DISASTER_RECOVERY_SCAN_LIMIT)
    effective_scan_limit = max(100, min(effective_scan_limit, 50000))

    report: dict[str, Any] = {
        "started_at": started_at,
        "dry_run": bool(dry_run),
        "options": {
            "rebuild_database": bool(rebuild_database),
            "rebuild_redis": bool(rebuild_redis),
            "recover_documents": bool(recover_documents),
            "promote_redis_to_master": bool(promote_redis_to_master),
            "restart_runtime": bool(restart_runtime),
            "scan_limit": effective_scan_limit,
        },
        "steps": [],
    }

    report["before"] = await detect_disaster_state(detailed=False)

    if dry_run:
        report["after"] = report["before"]
        report["completed_at"] = _utc_now_iso()
        report["success"] = True
        return report

    if rebuild_database:
        db_step: dict[str, Any] = {
            "name": "rebuild_database",
            "status": "pending",
        }
        try:
            ensure_schema_detail = await _ensure_database_schema_exists()
            db_step["detail"] = {"ensure_database_schema": ensure_schema_detail}
            if ensure_schema_detail.get("status") == "error":
                raise RuntimeError(
                    f"ensure_database_schema_failed: {ensure_schema_detail.get('error')}"
                )

            await drop_tables()
            await create_tables()
            await ensure_default_roles_and_admin()
            await ensure_default_llm_system_config()
            await mark_system_bootstrap_completed()
            db_step["status"] = "ok"
        except Exception as exc:
            db_step["status"] = "error"
            db_step["error"] = str(exc)
            logger.exception("Rebuild database failed")
        report["steps"].append(db_step)

        if recover_documents and db_step["status"] == "ok":
            recover_step: dict[str, Any] = {
                "name": "recover_documents_from_storage",
                "status": "pending",
            }
            try:
                async with AsyncSessionLocal() as session:
                    detail = await recover_documents_from_storage(session, effective_scan_limit)
                    await session.commit()
                recover_step["status"] = "ok"
                recover_step["detail"] = detail
            except Exception as exc:
                recover_step["status"] = "error"
                recover_step["error"] = str(exc)
                logger.exception("Recover documents from storage failed")
            report["steps"].append(recover_step)
    else:
        ensure_step: dict[str, Any] = {
            "name": "ensure_database_baseline",
            "status": "pending",
        }
        try:
            ensure_schema_detail = await _ensure_database_schema_exists()
            ensure_step["detail"] = {"ensure_database_schema": ensure_schema_detail}
            if ensure_schema_detail.get("status") == "error":
                raise RuntimeError(
                    f"ensure_database_schema_failed: {ensure_schema_detail.get('error')}"
                )

            await create_tables()
            await ensure_default_roles_and_admin()
            await ensure_default_llm_system_config()
            await mark_system_bootstrap_completed()
            ensure_step["status"] = "ok"
        except Exception as exc:
            ensure_step["status"] = "error"
            ensure_step["error"] = str(exc)
            logger.exception("Ensure database baseline failed")
        report["steps"].append(ensure_step)

    if rebuild_redis or promote_redis_to_master:
        redis_step: dict[str, Any] = {
            "name": "repair_redis",
            "status": "pending",
        }
        redis_detail = await _repair_redis(
            reset_data=bool(rebuild_redis),
            promote_to_master=bool(promote_redis_to_master),
        )
        redis_step["detail"] = redis_detail
        redis_step["status"] = "ok" if redis_detail.get("success") else "error"
        report["steps"].append(redis_step)

    if restart_runtime:
        restart_step: dict[str, Any] = {
            "name": "soft_restart_runtime",
            "status": "pending",
        }
        restart_detail = await soft_restart_runtime()
        restart_step["detail"] = restart_detail
        restart_step["status"] = "ok" if not restart_detail.get("errors") else "warning"
        report["steps"].append(restart_step)

    report["after"] = await detect_disaster_state(detailed=False)
    report["completed_at"] = _utc_now_iso()

    has_error_step = any(step.get("status") == "error" for step in report["steps"])
    has_critical_after = bool(report.get("after", {}).get("has_critical"))
    report["success"] = (not has_error_step) and (not has_critical_after)

    return report


async def run_startup_disaster_detection() -> dict[str, Any]:
    """Run auto detection on startup and perform safe auto-fixes when configured."""

    if not settings.AUTO_DISASTER_DETECT:
        return {
            "checked_at": _utc_now_iso(),
            "enabled": False,
            "message": "AUTO_DISASTER_DETECT is disabled",
        }

    actions: list[dict[str, Any]] = []
    report = await detect_disaster_state(detailed=False)

    if report.get("redis", {}).get("is_replica") and settings.AUTO_FIX_REDIS_REPLICA:
        logger.warning("Redis is replica on startup, trying to promote to master")
        redis_fix = await _repair_redis(reset_data=False, promote_to_master=True)
        actions.append({"action": "promote_redis_to_master", "result": redis_fix})
        report = await detect_disaster_state(detailed=False)

    database_state = report.get("database", {}) or {}
    database_connected = bool(database_state.get("connected"))
    missing_tables = database_state.get("missing_tables") or []
    should_auto_rebuild_db = (not database_connected) or bool(missing_tables)
    if should_auto_rebuild_db and settings.AUTO_REBUILD_ON_TABLE_LOSS:
        if not database_connected:
            logger.error("Database is unavailable on startup, auto rebuild is enabled")
        else:
            logger.error("Missing core tables on startup, auto rebuild is enabled")

        rebuild_report = await run_emergency_repair(
            rebuild_database=True,
            rebuild_redis=False,
            recover_documents=True,
            promote_redis_to_master=False,
            restart_runtime=False,
            dry_run=False,
        )
        actions.append({"action": "auto_rebuild_database", "result": rebuild_report})
        report = await detect_disaster_state(detailed=False)

    report["startup_actions"] = actions
    return report
