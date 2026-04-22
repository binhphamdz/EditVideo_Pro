import base64
import csv
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import requests
from PIL import Image
from ai_model_registry import (
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PROVIDER,
    get_ai_models_catalog,
    get_kie_endpoint,
    normalize_ai_model,
    normalize_ai_provider,
)

from paths import (
    BASE_PATH,
    DEFAULT_PROFILE,
    ensure_profile_structure,
    get_all_profiles,
    get_excel_log_file,
    get_export_dir,
    get_profile_dir,
    get_profile_project_dir,
    get_projects_list_file,
    get_projects_root,
    get_shopee_csv_file,
    sanitize_profile_name,
    set_active_profile,
)
from config_manager import FARM_DB_FILE, ensure_system_data_dir, load_config as load_system_config, save_config as save_system_config
from shopee_export import delete_shopee_jobs, load_shopee_jobs, normalize_shopee_product_link
from tab2_modules.ai_services import get_director_timeline, get_transcription
from tab2_modules.video_engine import render_faceless_video

SYSTEM_DATA_DIR = ensure_system_data_dir()
LEGACY_USERS_FILE = os.path.join(BASE_PATH, "web_users.json")
USERS_FILE = os.path.join(SYSTEM_DATA_DIR, "web_users.json")
AUTH_DB_FILE = FARM_DB_FILE
_RUNTIME_LOCK = threading.Lock()
_RENDER_LOCK = threading.Lock()
_AUTH_DB_LOCK = threading.Lock()
_AUTH_DB_READY = False
_WEB_JOBS: Dict[str, Dict[str, Any]] = {}
_RENDER_SEMAPHORE: Optional[threading.Semaphore] = None
_RENDER_MAX_THREADS: int = 1

_TRANSITION_OPTIONS: List[Dict[str, str]] = [
    {"key": "fade", "label": "⬜ Mờ dần (Fade)"},
    {"key": "slide_left", "label": "⬅️ Trượt Trái"},
    {"key": "slide_right", "label": "➡️ Trượt Phải"},
    {"key": "slide_up", "label": "⬆️ Trượt Lên"},
    {"key": "slide_down", "label": "⬇️ Trượt Xuống"},
    {"key": "wipe_left", "label": "⬅️ Quét Trái"},
    {"key": "wipe_right", "label": "➡️ Quét Phải"},
    {"key": "hlslice", "label": "🔀 Vụt Ngang TikTok"},
    {"key": "zoom_in", "label": "🔍 Phóng To"},
]
_MANAGER_HEADERS = ["Ngày Tạo", "Tên Project", "File Voice", "Đường Dẫn", "Trạng Thái"]
_DEFAULT_SCRIPT_PROMPT = """Viết lại kịch bản TikTok 60s từ dữ liệu được cung cấp theo giọng reviewer chân thật, dứt khoát và dễ lồng tiếng.
- Viết thành một đoạn hoàn chỉnh, mượt, không đánh số.
- Ưu tiên câu mở đầu gây chú ý và dẫn tự nhiên vào lợi ích sản phẩm.
- Không dùng các từ quá sáo rỗng hoặc trẻ con như nha, nhé, nè.
- Kết thúc bằng lời chốt rõ ràng, uy tín."""
_TELEGRAM_GUIDE_STEPS = [
    "Mở Telegram và tìm BotFather.",
    "Nhắn /newbot để tạo bot mới.",
    "Đặt tên hiển thị cho bot điều khiển.",
    "Đặt username cho bot, bắt buộc kết thúc bằng bot.",
    "Copy token BotFather trả về và dán vào cấu hình web.",
    "Mở chính bot vừa tạo và nhắn /start để bắt đầu dùng.",
]
_TELEGRAM_COMMANDS: List[Dict[str, str]] = [
    {"command": "/help", "description": "Mở bảng hướng dẫn và danh sách lệnh điều khiển."},
    {"command": "/projects", "description": "Xem project và bật hoặc đóng băng nhanh bằng số thứ tự."},
    {"command": "/account", "description": "Đổi workspace hoặc tài khoản đang điều khiển."},
    {"command": "/renameaccount", "description": "Đổi tên workspace hiện tại."},
    {"command": "/menu", "description": "Chạy một project để làm video."},
    {"command": "/multimenu", "description": "Chạy nhiều project cùng lúc."},
    {"command": "/autobatch", "description": "Chạy random hàng loạt nhiều project."},
    {"command": "/files", "description": "Vào kho video đã xuất và xem trạng thái."},
    {"command": "/icloud", "description": "Đồng bộ video mới sang iCloud."},
    {"command": "/clean", "description": "Dọn video cũ trên iCloud."},
    {"command": "/web", "description": "Bật hoặc tắt trạm web nội bộ."},
]


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _normalize_username(username: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(username or "").strip().lower())
    return cleaned.strip("._-")


def _load_user_db() -> Dict[str, Any]:
    for path in (USERS_FILE, LEGACY_USERS_FILE):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def _save_user_db(data: Dict[str, Any]) -> None:
    for path in (USERS_FILE, LEGACY_USERS_FILE):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data or {}, handle, indent=4, ensure_ascii=False)
        except Exception:
            pass


def _get_auth_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(AUTH_DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_auth_db() -> None:
    global _AUTH_DB_READY
    if _AUTH_DB_READY:
        return

    with _AUTH_DB_LOCK:
        if _AUTH_DB_READY:
            return
        conn = _get_auth_connection()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        full_name TEXT DEFAULT '',
                        password_hash TEXT NOT NULL,
                        role TEXT DEFAULT 'employee',
                        requested_role TEXT DEFAULT 'employee',
                        approved INTEGER DEFAULT 0,
                        is_active INTEGER DEFAULT 1,
                        can_use_phone INTEGER DEFAULT 0,
                        can_use_autopost INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT '',
                        approved_at TEXT DEFAULT '',
                        approved_by TEXT DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_workspaces (
                        username TEXT NOT NULL,
                        workspace_name TEXT NOT NULL,
                        PRIMARY KEY (username, workspace_name)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workspaces (
                        workspace_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        folder_path TEXT NOT NULL,
                        created_at TEXT DEFAULT '',
                        created_by TEXT DEFAULT '',
                        owner_username TEXT DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_workspace_access (
                        user_id TEXT NOT NULL,
                        workspace_id INTEGER NOT NULL,
                        PRIMARY KEY (user_id, workspace_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS render_jobs (
                        job_id TEXT PRIMARY KEY,
                        job_type TEXT DEFAULT 'render-real',
                        profile_name TEXT NOT NULL,
                        project_id TEXT DEFAULT '',
                        project_name TEXT DEFAULT '',
                        voice_names TEXT DEFAULT '[]',
                        status TEXT DEFAULT 'pending',
                        progress INTEGER DEFAULT 0,
                        status_text TEXT DEFAULT '',
                        queue_position INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT '',
                        started_at TEXT DEFAULT '',
                        finished_at TEXT DEFAULT '',
                        created_by TEXT DEFAULT '',
                        error_message TEXT DEFAULT '',
                        logs TEXT DEFAULT '[]'
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS login_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL,
                        ip_address TEXT DEFAULT '',
                        user_agent TEXT DEFAULT '',
                        login_time TEXT DEFAULT '',
                        success INTEGER DEFAULT 1
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_login_logs_username ON login_logs (username)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_login_logs_time ON login_logs (login_time DESC)"
                )
                for statement in (
                    "ALTER TABLE users ADD COLUMN can_use_phone INTEGER DEFAULT 0",
                    "ALTER TABLE users ADD COLUMN can_use_autopost INTEGER DEFAULT 0",
                ):
                    try:
                        conn.execute(statement)
                    except Exception:
                        pass
        finally:
            conn.close()

        _sync_workspace_registry()
        _migrate_legacy_users_to_auth_db()
        _sync_workspace_registry()
        _AUTH_DB_READY = True


def _sync_workspace_registry() -> None:
    conn = _get_auth_connection()
    try:
        with conn:
            existing_profiles = [sanitize_profile_name(name) for name in get_all_profiles()]
            for profile_name in existing_profiles:
                if not profile_name:
                    continue
                folder_path = get_profile_dir(profile_name)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO workspaces (name, folder_path, created_at, created_by, owner_username)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (profile_name, folder_path, _now_text(), "system", ""),
                )

            try:
                legacy_rows = conn.execute(
                    "SELECT username, workspace_name FROM user_workspaces ORDER BY username COLLATE NOCASE"
                ).fetchall()
            except Exception:
                legacy_rows = []

            for row in legacy_rows:
                workspace_name = sanitize_profile_name(row["workspace_name"])
                if not workspace_name:
                    continue
                folder_path = get_profile_dir(workspace_name)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO workspaces (name, folder_path, created_at, created_by, owner_username)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (workspace_name, folder_path, _now_text(), row["username"] or "system", row["username"] or ""),
                )
                ws_row = conn.execute("SELECT workspace_id FROM workspaces WHERE name = ?", (workspace_name,)).fetchone()
                if ws_row and row["username"]:
                    conn.execute(
                        "INSERT OR IGNORE INTO user_workspace_access (user_id, workspace_id) VALUES (?, ?)",
                        (_normalize_username(row["username"]), int(ws_row["workspace_id"])),
                    )
    finally:
        conn.close()


def _migrate_legacy_users_to_auth_db() -> None:
    # Only run migration ONCE — check sentinel in DB
    conn = _get_auth_connection()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'legacy_migrated'").fetchone()
        if row:
            return  # Already migrated, skip
    except Exception:
        # meta table might not exist yet — create it
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()

    legacy_users = _load_user_db()
    if not legacy_users:
        # Mark migrated even if no users to import
        _mark_legacy_migrated()
        return

    default_profile = ""
    try:
        config = load_app_config()
        default_profile = sanitize_profile_name(config.get("active_profile", "") or "")
    except Exception:
        default_profile = ""
    if not default_profile:
        profiles = get_all_profiles()
        default_profile = profiles[0] if profiles else DEFAULT_PROFILE

    conn = _get_auth_connection()
    try:
        with conn:
            for raw in legacy_users.values():
                if not isinstance(raw, dict):
                    continue
                username = _normalize_username(raw.get("username") or raw.get("id") or "")
                if not username:
                    continue
                role = "admin" if str(raw.get("role", "employee") or "employee").strip().lower() == "admin" else "employee"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO users (
                        id, username, full_name, password_hash, role, requested_role,
                        approved, is_active, can_use_phone, can_use_autopost, created_at, approved_at, approved_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        username,
                        str(raw.get("full_name", "") or username),
                        str(raw.get("password_hash", "") or _hash_password("admin123" if username == "admin" else "1234")),
                        role,
                        str(raw.get("requested_role", role) or role),
                        1 if raw.get("approved", False) else 0,
                        1 if raw.get("is_active", True) else 0,
                        1 if role == "admin" or _coerce_bool(raw.get("can_use_phone", False)) else 0,
                        1 if role == "admin" or _coerce_bool(raw.get("can_use_autopost", False)) else 0,
                        str(raw.get("created_at", "") or _now_text()),
                        str(raw.get("approved_at", "") or ""),
                        str(raw.get("approved_by", "") or ""),
                    ),
                )

                assigned = raw.get("assigned_workspaces") or raw.get("workspaces") or []
                if isinstance(assigned, str):
                    assigned = [assigned]
                if role != "admin" and not assigned:
                    assigned = [default_profile] if default_profile else []

                for workspace_name in assigned:
                    sanitized = sanitize_profile_name(workspace_name)
                    if sanitized:
                        folder_path = get_profile_dir(sanitized)
                        conn.execute(
                            "INSERT OR IGNORE INTO workspaces (name, folder_path, created_at, created_by, owner_username) VALUES (?, ?, ?, ?, ?)",
                            (sanitized, folder_path, _now_text(), username, username),
                        )
                        conn.execute(
                            "INSERT OR IGNORE INTO user_workspaces (username, workspace_name) VALUES (?, ?)",
                            (username, sanitized),
                        )
                        ws_row = conn.execute("SELECT workspace_id FROM workspaces WHERE name = ?", (sanitized,)).fetchone()
                        if ws_row:
                            conn.execute(
                                "INSERT OR IGNORE INTO user_workspace_access (user_id, workspace_id) VALUES (?, ?)",
                                (username, int(ws_row["workspace_id"])),
                            )
    finally:
        conn.close()

    _mark_legacy_migrated()


def _mark_legacy_migrated() -> None:
    conn = _get_auth_connection()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('legacy_migrated', ?)", (_now_text(),))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        salt, digest = str(encoded or "").split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return secrets.compare_digest(check, digest)


def _fetch_user_row(username: str) -> Optional[Dict[str, Any]]:
    _ensure_auth_db()
    user_key = _normalize_username(username)
    if not user_key:
        return None
    conn = _get_auth_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (user_key,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _fetch_user_workspaces(username: str) -> List[str]:
    _ensure_auth_db()
    user_key = _normalize_username(username)
    if not user_key:
        return []
    conn = _get_auth_connection()
    try:
        rows = conn.execute(
            """
            SELECT w.name
            FROM user_workspace_access a
            JOIN workspaces w ON w.workspace_id = a.workspace_id
            WHERE a.user_id = ?
            ORDER BY w.name COLLATE NOCASE
            """,
            (user_key,),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT workspace_name AS name FROM user_workspaces WHERE username = ? ORDER BY workspace_name COLLATE NOCASE",
                (user_key,),
            ).fetchall()
    finally:
        conn.close()

    existing_profiles = set(get_all_profiles())
    items: List[str] = []
    for row in rows:
        name = sanitize_profile_name(row["name"])
        if name in existing_profiles and name not in items:
            items.append(name)
    return items


def get_user_allowed_workspaces(username: str) -> List[str]:
    row = _fetch_user_row(username)
    if not row:
        return []
    role = str(row.get("role", "employee") or "employee").strip().lower()
    if role == "admin":
        return get_all_profiles()
    return _fetch_user_workspaces(username)


def resolve_user_profile_access(username: str, requested_profile: Optional[str] = None) -> str:
    user = get_user_by_username(username)
    if not user:
        raise PermissionError("Tài khoản đăng nhập không hợp lệ.")

    if user.get("role") == "admin":
        target = sanitize_profile_name(requested_profile or load_app_config().get("active_profile", "") or DEFAULT_PROFILE)
        return target

    allowed = get_user_allowed_workspaces(username)
    if not allowed:
        raise PermissionError("Tài khoản này chưa được admin cấp workspace nào.")

    if requested_profile:
        target = sanitize_profile_name(requested_profile)
        if target not in allowed:
            raise PermissionError("403 Không có quyền truy cập workspace này.")
        return target

    return allowed[0]


def set_user_workspace_access(username: str, workspaces: Optional[List[str]] = None) -> Dict[str, Any]:
    _ensure_auth_db()
    _sync_workspace_registry()
    user_key = _normalize_username(username)
    row = _fetch_user_row(user_key)
    if not row:
        raise ValueError("Không tìm thấy tài khoản để cấp workspace.")
    if str(row.get("role", "employee") or "employee").strip().lower() == "admin":
        return _public_user_row(row) or {}

    existing_profiles = set(get_all_profiles())
    unique_workspaces: List[str] = []
    for name in list(workspaces or []):
        workspace_name = sanitize_profile_name(name)
        if workspace_name in existing_profiles and workspace_name not in unique_workspaces:
            unique_workspaces.append(workspace_name)

    conn = _get_auth_connection()
    try:
        with conn:
            conn.execute("DELETE FROM user_workspaces WHERE username = ?", (user_key,))
            conn.execute("DELETE FROM user_workspace_access WHERE user_id = ?", (user_key,))
            for workspace_name in unique_workspaces:
                conn.execute(
                    "INSERT OR IGNORE INTO user_workspaces (username, workspace_name) VALUES (?, ?)",
                    (user_key, workspace_name),
                )
                ws_row = conn.execute("SELECT workspace_id FROM workspaces WHERE name = ?", (workspace_name,)).fetchone()
                if ws_row:
                    conn.execute(
                        "INSERT OR IGNORE INTO user_workspace_access (user_id, workspace_id) VALUES (?, ?)",
                        (user_key, int(ws_row["workspace_id"])),
                    )
    finally:
        conn.close()
    _sync_user_db_backup()
    return get_user_by_username(user_key) or {}


def _public_user_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None
    username = _normalize_username(row.get("username", "") or row.get("id", "") or "")
    role = str(row.get("role", "employee") or "employee")
    assigned = get_all_profiles() if role == "admin" else _fetch_user_workspaces(username)
    can_use_phone = True if role == "admin" else bool(row.get("can_use_phone", 0))
    can_use_autopost = True if role == "admin" else bool(row.get("can_use_autopost", 0))
    # Count completed render jobs for this user
    completed_videos = 0
    try:
        rconn = _get_auth_connection()
        r = rconn.execute(
            "SELECT COUNT(*) FROM render_jobs WHERE created_by=? AND status='done'", (username,)
        ).fetchone()
        completed_videos = int(r[0]) if r else 0
        rconn.close()
    except Exception:
        pass
    return {
        "id": str(row.get("id", username) or username),
        "username": username,
        "full_name": str(row.get("full_name", "") or ""),
        "role": role,
        "requested_role": str(row.get("requested_role", row.get("role", "employee")) or "employee"),
        "approved": bool(row.get("approved", 0)),
        "is_active": bool(row.get("is_active", 1)),
        "can_use_phone": can_use_phone,
        "can_use_autopost": can_use_autopost,
        "created_at": str(row.get("created_at", "") or ""),
        "approved_at": str(row.get("approved_at", "") or ""),
        "approved_by": str(row.get("approved_by", "") or ""),
        "assigned_workspaces": assigned,
        "completed_videos": completed_videos,
    }


def record_login_log(username: str, ip_address: str, user_agent: str = "", success: bool = True) -> None:
    """Ghi lại lịch sử đăng nhập vào bảng login_logs."""
    _ensure_auth_db()
    try:
        conn = _get_auth_connection()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO login_logs (username, ip_address, user_agent, login_time, success) VALUES (?, ?, ?, ?, ?)",
                    (
                        _normalize_username(username),
                        str(ip_address or "")[:128],
                        str(user_agent or "")[:256],
                        _now_text(),
                        1 if success else 0,
                    ),
                )
        finally:
            conn.close()
    except Exception:
        pass


def get_login_logs(username: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    """Trả về lịch sử đăng nhập. Nếu username=None thì lấy tất cả (admin)."""
    _ensure_auth_db()
    try:
        conn = _get_auth_connection()
        try:
            if username:
                rows = conn.execute(
                    "SELECT username, ip_address, user_agent, login_time, success FROM login_logs WHERE username = ? ORDER BY login_time DESC LIMIT ?",
                    (_normalize_username(username), int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT username, ip_address, user_agent, login_time, success FROM login_logs ORDER BY login_time DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            return [
                {
                    "username": str(r["username"] or ""),
                    "ip_address": str(r["ip_address"] or ""),
                    "user_agent": str(r["user_agent"] or ""),
                    "login_time": str(r["login_time"] or ""),
                    "success": bool(r["success"]),
                }
                for r in rows
            ]
        finally:
            conn.close()
    except Exception:
        return []


def ensure_default_admin_user() -> Dict[str, Any]:
    _ensure_auth_db()
    conn = _get_auth_connection()
    try:
        existing = _fetch_user_row("admin") or {}
        existing_hash = str(existing.get("password_hash", "") or "")
        should_reset_default = (not existing_hash) or _verify_password("admin123", existing_hash)
        admin_hash = _hash_password("1") if should_reset_default else existing_hash

        with conn:
            conn.execute("UPDATE users SET role = 'employee', requested_role = 'employee' WHERE username <> 'admin'")
            conn.execute(
                """
                INSERT INTO users (
                    id, username, full_name, password_hash, role, requested_role,
                    approved, is_active, can_use_phone, can_use_autopost, created_at, approved_at, approved_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    full_name = excluded.full_name,
                    role = 'admin',
                    requested_role = 'admin',
                    approved = 1,
                    is_active = 1,
                    can_use_phone = 1,
                    can_use_autopost = 1,
                    approved_at = excluded.approved_at,
                    approved_by = CASE WHEN users.approved_by IS NULL OR users.approved_by = '' THEN excluded.approved_by ELSE users.approved_by END
                """,
                (
                    "admin",
                    "admin",
                    str(existing.get("full_name", "") or "Quản trị hệ thống"),
                    admin_hash or _hash_password("1"),
                    "admin",
                    "admin",
                    1,
                    1,
                    1,
                    1,
                    str(existing.get("created_at", "") or _now_text()),
                    _now_text(),
                    str(existing.get("approved_by", "") or "system"),
                ),
            )
            if should_reset_default:
                conn.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (admin_hash or _hash_password("1"),))
    finally:
        conn.close()

    _sync_user_db_backup()
    return get_user_by_username("admin") or {}


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    _ensure_auth_db()
    row = _fetch_user_row(username)
    return _public_user_row(row)


def user_has_feature_access(username: str, feature_name: str) -> bool:
    user = get_user_by_username(username)
    if not user:
        return False
    if str(user.get("role", "employee") or "employee") == "admin":
        return True
    feature_key = str(feature_name or "").strip().lower()
    if feature_key == "phone":
        return bool(user.get("can_use_phone", False))
    if feature_key in {"autopost", "shopee"}:
        return bool(user.get("can_use_autopost", False))
    return False


def list_web_users(limit: int = 200) -> List[Dict[str, Any]]:
    ensure_default_admin_user()
    conn = _get_auth_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC, username COLLATE NOCASE LIMIT ?",
            (max(1, int(limit or 200)),),
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            if not row:
                continue
            item = _public_user_row(dict(row))
            if item:
                items.append(item)
        return items
    finally:
        conn.close()


def _sync_user_db_backup() -> None:
    conn = _get_auth_connection()
    try:
        rows = conn.execute("SELECT * FROM users ORDER BY username COLLATE NOCASE").fetchall()
        snapshot = {}
        for row in rows:
            item = _public_user_row(dict(row)) or {}
            username = item.get("username")
            if username:
                snapshot[username] = item
        _save_user_db(snapshot)
    finally:
        conn.close()


def register_web_user(full_name: str, username: str, password: str, requested_role: str = "employee") -> Dict[str, Any]:
    ensure_default_admin_user()
    user_key = _normalize_username(username)
    if len(user_key) < 3:
        raise ValueError("Tên đăng nhập cần từ 3 ký tự trở lên.")
    if not str(password or ""):
        raise ValueError("Mật khẩu không được để trống.")
    if user_key == "admin":
        raise ValueError("Tài khoản admin đã được hệ thống tạo sẵn, không thể đăng ký thêm.")

    if _fetch_user_row(user_key):
        raise ValueError("Tên đăng nhập này đã tồn tại.")

    role = "employee"
    conn = _get_auth_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO users (
                    id, username, full_name, password_hash, role, requested_role,
                    approved, is_active, can_use_phone, can_use_autopost, created_at, approved_at, approved_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_key,
                    user_key,
                    str(full_name or user_key).strip() or user_key,
                    _hash_password(password),
                    role,
                    role,
                    0,
                    1,
                    0,
                    0,
                    _now_text(),
                    "",
                    "",
                ),
            )
    finally:
        conn.close()
    _sync_user_db_backup()
    return get_user_by_username(user_key) or {}


def authenticate_web_user(username: str, password: str) -> Dict[str, Any]:
    ensure_default_admin_user()
    row = _fetch_user_row(username)
    if not isinstance(row, dict):
        raise PermissionError("Sai tên đăng nhập hoặc mật khẩu.")
    if not bool(row.get("is_active", 1)):
        raise PermissionError("Tài khoản này đang bị khóa.")
    if not _verify_password(password, str(row.get("password_hash", "") or "")):
        raise PermissionError("Sai tên đăng nhập hoặc mật khẩu.")
    if not bool(row.get("approved", 0)):
        raise PermissionError("Tài khoản đang chờ admin duyệt nên chưa đăng nhập được.")
    return _public_user_row(row) or {}


def update_web_user(
    username: str,
    actor_username: str,
    approved: Optional[bool] = None,
    is_active: Optional[bool] = None,
    role: Optional[str] = None,
    can_use_phone: Optional[bool] = None,
    can_use_autopost: Optional[bool] = None,
) -> Dict[str, Any]:
    ensure_default_admin_user()
    user_key = _normalize_username(username)
    actor_key = _normalize_username(actor_username)
    row = _fetch_user_row(user_key)

    if not row:
        raise ValueError("Không tìm thấy tài khoản cần cập nhật.")

    next_role = "admin" if user_key == "admin" else "employee"
    next_approved = bool(row.get("approved", 0))
    next_is_active = bool(row.get("is_active", 1))
    next_can_use_phone = True if user_key == "admin" else bool(row.get("can_use_phone", 0))
    next_can_use_autopost = True if user_key == "admin" else bool(row.get("can_use_autopost", 0))

    if role is not None and user_key != "admin":
        next_role = "employee"
    if approved is not None:
        next_approved = bool(approved)
    if is_active is not None:
        if user_key == actor_key and not bool(is_active):
            raise ValueError("Không thể tự khóa chính tài khoản đang dùng.")
        next_is_active = bool(is_active)
    if user_key != "admin" and can_use_phone is not None:
        next_can_use_phone = bool(can_use_phone)
    if user_key != "admin" and can_use_autopost is not None:
        next_can_use_autopost = bool(can_use_autopost)

    conn = _get_auth_connection()
    try:
        with conn:
            conn.execute(
                """
                UPDATE users
                SET role = ?,
                    requested_role = ?,
                    approved = ?,
                    is_active = ?,
                    can_use_phone = ?,
                    can_use_autopost = ?,
                    approved_at = ?,
                    approved_by = ?
                WHERE username = ?
                """,
                (
                    next_role,
                    next_role,
                    1 if next_approved else 0,
                    1 if next_is_active else 0,
                    1 if next_can_use_phone else 0,
                    1 if next_can_use_autopost else 0,
                    _now_text() if next_approved else str(row.get("approved_at", "") or ""),
                    actor_key or "admin",
                    user_key,
                ),
            )

        check_conn = _get_auth_connection()
        try:
            count_row = check_conn.execute(
                "SELECT COUNT(*) AS total FROM users WHERE role = 'admin' AND approved = 1 AND is_active = 1"
            ).fetchone()
            active_admin_count = int((count_row["total"] if count_row else 0) or 0)
        finally:
            check_conn.close()

        if active_admin_count <= 0:
            raise ValueError("Hệ thống cần ít nhất 1 tài khoản admin đang hoạt động.")
    finally:
        conn.close()

    _sync_user_db_backup()

    # Auto-create workspace for newly approved non-admin users
    was_approved_before = bool(row.get("approved", 0))
    if next_approved and user_key != "admin":
        # Chỉ tạo nếu chưa có workspace trùng tên username
        conn_check = _get_auth_connection()
        try:
            ws_row = conn_check.execute("SELECT workspace_id FROM workspaces WHERE name = ?", (user_key,)).fetchone()
        finally:
            conn_check.close()
        if not ws_row:
            try:
                create_workspace_entry(user_key, actor_key, user_key)
            except Exception as _ws_err:
                print(f"[AutoCreateWorkspace] Bỏ qua: {_ws_err}")
        else:
            # Workspace đã tồn tại → đảm bảo user vẫn có quyền truy cập
            conn_grant = _get_auth_connection()
            try:
                with conn_grant:
                    conn_grant.execute(
                        "INSERT OR IGNORE INTO user_workspace_access (user_id, workspace_id) VALUES (?, ?)",
                        (user_key, int(ws_row["workspace_id"])),
                    )
                    conn_grant.execute(
                        "INSERT OR IGNORE INTO user_workspaces (username, workspace_name) VALUES (?, ?)",
                        (user_key, user_key),
                    )
            finally:
                conn_grant.close()

    return get_user_by_username(user_key) or {}


def update_current_user_profile(username: str, full_name: Optional[str] = None) -> Dict[str, Any]:
    ensure_default_admin_user()
    user_key = _normalize_username(username)
    row = _fetch_user_row(user_key)
    if not row:
        raise ValueError("Không tìm thấy tài khoản.")

    clean_name = str(full_name or row.get("full_name", user_key) or user_key).strip() or user_key
    conn = _get_auth_connection()
    try:
        with conn:
            conn.execute("UPDATE users SET full_name = ? WHERE username = ?", (clean_name, user_key))
    finally:
        conn.close()

    _sync_user_db_backup()
    return get_user_by_username(user_key) or {}


def change_current_user_password(username: str, current_password: str, new_password: str) -> Dict[str, Any]:
    ensure_default_admin_user()
    user_key = _normalize_username(username)
    row = _fetch_user_row(user_key)
    if not row:
        raise ValueError("Không tìm thấy tài khoản.")
    if not _verify_password(current_password, str(row.get("password_hash", "") or "")):
        raise ValueError("Mật khẩu hiện tại chưa đúng.")
    if not str(new_password or ""):
        raise ValueError("Mật khẩu mới không được để trống.")

    conn = _get_auth_connection()
    try:
        with conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (_hash_password(new_password), user_key))
    finally:
        conn.close()

    _sync_user_db_backup()
    return get_user_by_username(user_key) or {}


def load_app_config() -> Dict[str, Any]:
    try:
        return load_system_config()
    except Exception:
        return {}


def save_app_config(config: Dict[str, Any]) -> None:
    try:
        save_system_config(config or {})
    except Exception:
        pass


def _mask_secret(value: str, keep: int = 6) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= keep * 2:
        return "*" * len(raw)
    return f"{raw[:keep]}{'*' * (len(raw) - keep * 2)}{raw[-keep:]}"


def _get_telegram_stats(profile_name: Optional[str] = None) -> Dict[str, int]:
    target_profile = ensure_active_profile(profile_name)
    total = 0
    today = 0
    done = 0
    pending = 0
    today_str = time.strftime("%d/%m/%Y")
    csv_path = get_excel_log_file(target_profile)
    if os.path.isfile(csv_path):
        try:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                next(reader, None)
                for row in reader:
                    if not row or len(row) < 4:
                        continue
                    total += 1
                    if str(row[0] or "").startswith(today_str):
                        today += 1
                    status_text = str(row[4] if len(row) > 4 else "Chưa chuyển" or "Chưa chuyển")
                    if "Đã" in status_text:
                        done += 1
                    else:
                        pending += 1
        except Exception:
            pass
    return {"total": total, "today": today, "done": done, "pending": pending}


def get_telegram_center_data(profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    config = load_app_config()
    token = str(config.get("telegram_bot_token", "") or "").strip()
    return {
        "ok": True,
        "profile_name": target_profile,
        "token": token,
        "token_masked": _mask_secret(token),
        "token_configured": bool(token),
        "status_label": "Đã cấu hình token" if token else "Chưa cấu hình token",
        "guide_steps": list(_TELEGRAM_GUIDE_STEPS),
        "commands": list(_TELEGRAM_COMMANDS),
        "stats": _get_telegram_stats(target_profile),
        "note": "Web đang quản lý cấu hình Telegram và hiển thị bộ lệnh theo logic bot_telegram.py hiện có.",
    }


def save_telegram_center_settings(profile_name: Optional[str] = None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = settings or {}
    config = load_app_config()
    if payload.get("telegram_bot_token") is not None:
        config["telegram_bot_token"] = str(payload.get("telegram_bot_token") or "").strip()
    save_app_config(config)
    return get_telegram_center_data(profile_name)


def get_saved_active_profile() -> str:
    config = load_app_config()
    saved_profile = sanitize_profile_name(config.get("active_profile", "") or DEFAULT_PROFILE)
    profiles = get_all_profiles()

    if saved_profile in profiles:
        return saved_profile
    if profiles:
        return profiles[0]
    return DEFAULT_PROFILE


def ensure_active_profile(profile_name: Optional[str] = None) -> str:
    with _RUNTIME_LOCK:
        target_profile = sanitize_profile_name(profile_name or get_saved_active_profile())
        set_active_profile(target_profile)
        config = load_app_config()
        config["active_profile"] = target_profile
        save_app_config(config)
        return target_profile


def list_workspaces(username: Optional[str] = None, active_profile: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_auth_db()
    _sync_workspace_registry()
    conn = _get_auth_connection()
    user = get_user_by_username(username or "") if username else None
    current = sanitize_profile_name(active_profile or "")

    try:
        if user and user.get("role") != "admin":
            rows = conn.execute(
                """
                SELECT w.name, w.folder_path, w.created_at, w.created_by, w.owner_username
                FROM user_workspace_access a
                JOIN workspaces w ON w.workspace_id = a.workspace_id
                WHERE a.user_id = ?
                ORDER BY w.name COLLATE NOCASE
                """,
                (_normalize_username(username or ""),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, folder_path, created_at, created_by, owner_username FROM workspaces ORDER BY name COLLATE NOCASE"
            ).fetchall()
    finally:
        conn.close()

    items: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        profile_name = sanitize_profile_name(row["name"])
        if not profile_name or profile_name in seen:
            continue
        seen.add(profile_name)
        items.append(
            {
                "name": profile_name,
                "is_active": profile_name == current,
                "folder_path": str(row["folder_path"] or ""),
                "created_at": str(row["created_at"] or ""),
                "created_by": str(row["created_by"] or ""),
                "owner_username": str(row["owner_username"] or ""),
            }
        )

    if not current and items:
        items[0]["is_active"] = True
    return items


def create_workspace_entry(workspace_name: str, creator_username: str, owner_username: Optional[str] = None) -> Dict[str, Any]:
    _ensure_auth_db()
    clean_name = sanitize_profile_name(workspace_name)
    if len(clean_name) < 3:
        raise ValueError("Tên workspace cần từ 3 ký tự trở lên.")

    creator_key = _normalize_username(creator_username)
    owner_key = _normalize_username(owner_username or creator_username)
    if not _fetch_user_row(owner_key):
        owner_key = creator_key

    _sync_workspace_registry()
    conn = _get_auth_connection()
    try:
        exists = conn.execute("SELECT workspace_id FROM workspaces WHERE name = ?", (clean_name,)).fetchone()
        if exists:
            raise ValueError("Workspace này đã tồn tại rồi.")

        folder_path = ensure_profile_structure(clean_name)
        with conn:
            conn.execute(
                "INSERT INTO workspaces (name, folder_path, created_at, created_by, owner_username) VALUES (?, ?, ?, ?, ?)",
                (clean_name, folder_path, _now_text(), creator_key, owner_key),
            )
            ws_row = conn.execute("SELECT workspace_id FROM workspaces WHERE name = ?", (clean_name,)).fetchone()
            if ws_row:
                conn.execute(
                    "INSERT OR IGNORE INTO user_workspace_access (user_id, workspace_id) VALUES (?, ?)",
                    (owner_key, int(ws_row["workspace_id"])),
                )
            conn.execute(
                "INSERT OR IGNORE INTO user_workspaces (username, workspace_name) VALUES (?, ?)",
                (owner_key, clean_name),
            )
    finally:
        conn.close()

    _sync_user_db_backup()
    return {
        "ok": True,
        "workspace": clean_name,
        "owner_username": owner_key,
        "items": list_workspaces(creator_key, clean_name),
    }


def delete_workspace_entry(workspace_name: str, actor_username: str) -> Dict[str, Any]:
    _ensure_auth_db()
    clean_name = sanitize_profile_name(workspace_name)
    if not clean_name:
        raise ValueError("Không tìm thấy workspace cần xóa.")

    actor = get_user_by_username(actor_username)
    if not actor or actor.get("role") != "admin":
        raise PermissionError("Chỉ admin mới được xóa workspace.")

    conn = _get_auth_connection()
    try:
        row = conn.execute("SELECT workspace_id, folder_path FROM workspaces WHERE name = ?", (clean_name,)).fetchone()
        if not row:
            raise ValueError("Workspace này không còn tồn tại.")

        folder_path = str(row["folder_path"] or "")
        workspace_id = int(row["workspace_id"])
        with conn:
            conn.execute("DELETE FROM user_workspace_access WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM user_workspaces WHERE workspace_name = ?", (clean_name,))
            conn.execute("DELETE FROM workspaces WHERE workspace_id = ?", (workspace_id,))
    finally:
        conn.close()

    if folder_path and os.path.isdir(folder_path):
        shutil.rmtree(folder_path, ignore_errors=True)

    _sync_user_db_backup()
    return {
        "ok": True,
        "deleted_workspace": clean_name,
        "items": list_workspaces(actor_username),
    }


def rename_workspace_entry(old_name: str, new_name: str, actor_username: str) -> Dict[str, Any]:
    _ensure_auth_db()
    clean_old = sanitize_profile_name(old_name)
    clean_new = sanitize_profile_name(new_name)
    if not clean_old:
        raise ValueError("Workspace cũ không hợp lệ.")
    if len(clean_new) < 3:
        raise ValueError("Tên workspace mới cần từ 3 ký tự trở lên.")
    if clean_old == clean_new:
        raise ValueError("Tên mới trùng với tên cũ.")

    actor_key = _normalize_username(actor_username)
    actor = get_user_by_username(actor_key)
    if not actor:
        raise PermissionError("Không xác định được người thực hiện.")

    conn = _get_auth_connection()
    try:
        ws_row = conn.execute("SELECT workspace_id, folder_path, owner_username FROM workspaces WHERE name = ?", (clean_old,)).fetchone()
        if not ws_row:
            raise ValueError("Workspace cũ không tồn tại.")

        # Only admin or owner can rename
        if actor.get("role") != "admin" and _normalize_username(ws_row["owner_username"] or "") != actor_key:
            raise PermissionError("Chỉ admin hoặc chủ sở hữu mới được đổi tên workspace.")

        exists = conn.execute("SELECT workspace_id FROM workspaces WHERE name = ?", (clean_new,)).fetchone()
        if exists:
            raise ValueError(f"Workspace '{clean_new}' đã tồn tại rồi.")

        old_folder = str(ws_row["folder_path"] or "")
        new_folder = os.path.join(os.path.dirname(old_folder), clean_new) if old_folder else get_profile_dir(clean_new)

        # Rename folder on disk
        if old_folder and os.path.isdir(old_folder):
            os.rename(old_folder, new_folder)
        else:
            ensure_profile_structure(clean_new)

        workspace_id = int(ws_row["workspace_id"])
        with conn:
            conn.execute("UPDATE workspaces SET name = ?, folder_path = ? WHERE workspace_id = ?", (clean_new, new_folder, workspace_id))
            conn.execute("UPDATE user_workspaces SET workspace_name = ? WHERE workspace_name = ?", (clean_new, clean_old))
    finally:
        conn.close()

    _sync_user_db_backup()
    return {
        "ok": True,
        "old_name": clean_old,
        "new_name": clean_new,
        "items": list_workspaces(actor_key, clean_new),
    }


def delete_web_user(username: str, actor_username: str) -> Dict[str, Any]:
    ensure_default_admin_user()
    user_key = _normalize_username(username)
    actor_key = _normalize_username(actor_username)
    if user_key == "admin":
        raise ValueError("Không thể xóa tài khoản admin mặc định.")

    row = _fetch_user_row(user_key)
    if not row:
        raise ValueError("Không tìm thấy nhân viên cần xóa.")
    actor = get_user_by_username(actor_key)
    if not actor or actor.get("role") != "admin":
        raise PermissionError("Chỉ admin mới được xóa nhân viên.")

    conn = _get_auth_connection()
    transferred_workspaces: List[str] = []
    try:
        with conn:
            owned_rows = conn.execute("SELECT workspace_id, name FROM workspaces WHERE owner_username = ?", (user_key,)).fetchall()
            for owned in owned_rows:
                transferred_name = sanitize_profile_name(owned["name"])
                if transferred_name:
                    transferred_workspaces.append(transferred_name)
                conn.execute(
                    "UPDATE workspaces SET owner_username = 'admin' WHERE workspace_id = ?",
                    (int(owned["workspace_id"]),),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO user_workspaces (username, workspace_name) VALUES (?, ?)",
                    ("admin", transferred_name),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO user_workspace_access (user_id, workspace_id) VALUES (?, ?)",
                    ("admin", int(owned["workspace_id"])),
                )

            conn.execute("DELETE FROM user_workspace_access WHERE user_id = ?", (user_key,))
            conn.execute("DELETE FROM user_workspaces WHERE username = ?", (user_key,))
            conn.execute("DELETE FROM users WHERE username = ?", (user_key,))
    finally:
        conn.close()

    _sync_user_db_backup()
    return {
        "ok": True,
        "deleted_username": user_key,
        "transferred_workspaces": transferred_workspaces,
        "items": list_web_users(),
    }


def switch_workspace(profile_name: str, username: Optional[str] = None) -> Dict[str, Any]:
    active = resolve_user_profile_access(username or "admin", profile_name)
    with _RUNTIME_LOCK:
        set_active_profile(active)
    return {
        "ok": True,
        "active_profile": active,
        "summary": get_workspace_summary(active),
    }


def _read_projects_file(profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    project_file = get_projects_list_file(target_profile)
    try:
        with open(project_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def list_projects(profile_name: Optional[str] = None) -> List[Dict[str, Any]]:
    target_profile = ensure_active_profile(profile_name)
    projects = _read_projects_file(target_profile)
    rows: List[Dict[str, Any]] = []

    for project_id, meta in projects.items():
        meta = meta or {}
        rows.append(
            {
                "id": str(project_id),
                "name": str(meta.get("name", "") or project_id),
                "status": str(meta.get("status", "active") or "active"),
                "created_at": str(meta.get("created_at", "") or ""),
                "profile_name": target_profile,
            }
        )

    rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return rows


def _write_projects_file(profile_name: str, data: Dict[str, Any]) -> None:
    target_profile = ensure_active_profile(profile_name)
    project_file = get_projects_list_file(target_profile)
    backup_file = project_file.replace(".json", "_backup.json")
    os.makedirs(os.path.dirname(project_file), exist_ok=True)

    if os.path.exists(project_file) and os.path.getsize(project_file) > 0:
        try:
            shutil.copy2(project_file, backup_file)
        except Exception:
            pass

    with open(project_file, "w", encoding="utf-8") as handle:
        json.dump(data or {}, handle, indent=4, ensure_ascii=False)


def create_project_entry(project_name: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    clean_name = str(project_name or "").strip()
    if not clean_name:
        raise ValueError("Bác chưa nhập tên project mới.")

    projects = _read_projects_file(target_profile)
    if any(str((meta or {}).get("name", "") or "").strip().casefold() == clean_name.casefold() for meta in projects.values()):
        raise ValueError("Project này đã tồn tại trong tài khoản hiện tại.")

    project_id = time.strftime("%Y%m%d%H%M%S")
    while project_id in projects:
        time.sleep(1)
        project_id = time.strftime("%Y%m%d%H%M%S")

    projects[project_id] = {
        "name": clean_name,
        "created_at": time.time(),
        "status": "active",
    }
    _write_projects_file(target_profile, projects)

    project_dir = get_profile_project_dir(project_id, target_profile)
    for folder_name in ("Broll", "Broll_Trash", "Voices"):
        os.makedirs(os.path.join(project_dir, folder_name), exist_ok=True)

    _save_project_data(project_id, target_profile, _default_project_data())
    return {
        "ok": True,
        "project_id": project_id,
        "profile_name": target_profile,
        "items": list_projects(target_profile),
    }


def rename_project_entry(project_id: str, project_name: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    clean_name = str(project_name or "").strip()
    if not project_id:
        raise ValueError("Chưa chọn project để đổi tên.")
    if not clean_name:
        raise ValueError("Tên project mới đang trống.")

    projects = _read_projects_file(target_profile)
    if project_id not in projects:
        raise ValueError("Không tìm thấy project cần đổi tên.")

    for other_id, meta in projects.items():
        if other_id == project_id:
            continue
        existing_name = str((meta or {}).get("name", "") or "").strip()
        if existing_name.casefold() == clean_name.casefold():
            raise ValueError("Đã có project khác trùng tên này.")

    meta = projects.get(project_id, {}) or {}
    meta["name"] = clean_name
    projects[project_id] = meta
    _write_projects_file(target_profile, projects)
    return {
        "ok": True,
        "project_id": project_id,
        "profile_name": target_profile,
        "items": list_projects(target_profile),
    }


def set_project_status_entry(project_id: str, status: Optional[str] = None, profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    if not project_id:
        raise ValueError("Chưa chọn project để đổi trạng thái.")

    projects = _read_projects_file(target_profile)
    if project_id not in projects:
        raise ValueError("Không tìm thấy project cần cập nhật.")

    meta = projects.get(project_id, {}) or {}
    current_status = str(meta.get("status", "active") or "active").strip().lower()
    next_status = str(status or "").strip().lower()
    if next_status not in ("active", "disabled"):
        next_status = "disabled" if current_status != "disabled" else "active"

    meta["status"] = next_status
    projects[project_id] = meta
    _write_projects_file(target_profile, projects)
    return {
        "ok": True,
        "project_id": project_id,
        "status": next_status,
        "profile_name": target_profile,
        "items": list_projects(target_profile),
    }


def delete_project_entry(project_id: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    if not project_id:
        raise ValueError("Chưa chọn project để xóa.")

    projects = _read_projects_file(target_profile)
    if project_id not in projects:
        raise ValueError("Không tìm thấy project cần xóa.")

    projects.pop(project_id, None)
    _write_projects_file(target_profile, projects)
    shutil.rmtree(os.path.join(get_projects_root(target_profile), str(project_id)), ignore_errors=True)
    return {
        "ok": True,
        "profile_name": target_profile,
        "items": list_projects(target_profile),
    }


def move_project_to_profile_web(project_id: str, target_profile: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    source_profile = ensure_active_profile(profile_name)
    target_profile = sanitize_profile_name(target_profile or "")

    if not project_id:
        raise ValueError("Chưa chọn project để chuyển tài khoản.")
    if not target_profile:
        raise ValueError("Chưa chọn tài khoản đích.")
    if target_profile == source_profile:
        raise ValueError("Không thể chuyển project vào chính tài khoản hiện tại.")

    source_projects = _read_projects_file(source_profile)
    if project_id not in source_projects:
        raise ValueError("Không tìm thấy project cần chuyển.")

    meta = source_projects.get(project_id, {}) or {}
    project_name = str(meta.get("name", "") or project_id).strip()
    target_projects = _read_projects_file(target_profile)

    for existing_meta in target_projects.values():
        existing_name = str((existing_meta or {}).get("name", "") or "").strip()
        if existing_name.casefold() == project_name.casefold():
            raise ValueError(f"Tài khoản đích đã có project trùng tên: {project_name}")

    source_dir = os.path.join(get_projects_root(source_profile), str(project_id))
    target_dir = os.path.join(get_projects_root(target_profile), str(project_id))
    if not os.path.exists(source_dir):
        raise ValueError("Không tìm thấy thư mục project để chuyển.")
    if os.path.exists(target_dir):
        raise ValueError("Tài khoản đích đã có sẵn thư mục project cùng mã này.")

    shutil.move(source_dir, target_dir)
    source_projects.pop(project_id, None)
    target_projects[project_id] = meta
    _write_projects_file(source_profile, source_projects)
    _write_projects_file(target_profile, target_projects)

    return {
        "ok": True,
        "profile_name": source_profile,
        "target_profile": target_profile,
        "items": list_projects(source_profile),
    }


def list_project_voices(project_id: str, profile_name: Optional[str] = None) -> List[str]:
    target_profile = ensure_active_profile(profile_name)
    project_dir = get_profile_project_dir(project_id, target_profile)
    voice_dir = os.path.join(project_dir, "Voices")
    if not os.path.isdir(voice_dir):
        return []

    voice_names = [
        item for item in os.listdir(voice_dir)
        if item.lower().endswith((".mp3", ".wav", ".m4a")) and os.path.isfile(os.path.join(voice_dir, item))
    ]
    voice_names.sort()
    return voice_names


def _read_text_file_safe(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return ""


def _write_text_file_safe(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(str(content or ""))


def _clean_multiline_text(raw: str) -> str:
    return "\n".join([line.strip() for line in str(raw or "").splitlines() if line.strip()])


def _format_srt_time(seconds: float) -> str:
    total = max(0.0, float(seconds or 0.0))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    millis = int(round((total - int(total)) * 1000))
    if millis >= 1000:
        secs += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _segments_to_srt_text(segments: List[Dict[str, Any]]) -> str:
    rows: List[str] = []
    for index, item in enumerate(segments or [], start=1):
        text = re.sub(r"\s+", " ", str(item.get("text", "") or "")).strip()
        if not text:
            continue
        start = _format_srt_time(float(item.get("start", 0.0) or 0.0))
        end = _format_srt_time(float(item.get("end", item.get("start", 0.0)) or 0.0))
        rows.append(f"{index}\n{start} --> {end}\n{text}\n")
    return "\n".join(rows).strip()


def _timeline_text_to_srt_text(raw_text: str) -> str:
    items: List[Dict[str, Any]] = []
    pattern = re.compile(r"\[\s*([0-9]+(?:\.[0-9]+)?)s\s*-\s*([0-9]+(?:\.[0-9]+)?)s\s*\]:\s*(.+)")
    for line in str(raw_text or "").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        start, end, text = match.groups()
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if text:
            items.append({"start": float(start), "end": float(end), "text": text})
    return _segments_to_srt_text(items)


def _get_subtitle_video_dir(project_id: str, profile_name: str) -> str:
    folder = os.path.join(get_profile_project_dir(project_id, profile_name), "Subtitle_Videos")
    os.makedirs(folder, exist_ok=True)
    return folder


def _get_subtitle_output_dir(project_id: str, profile_name: str) -> str:
    folder = os.path.join(get_profile_project_dir(project_id, profile_name), "Subtitle_Output")
    os.makedirs(folder, exist_ok=True)
    return folder


def _collect_subtitle_video_items(project_id: str, profile_name: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    video_exts = (".mp4", ".mov", ".avi", ".mkv", ".webm")
    upload_dir = _get_subtitle_video_dir(project_id, profile_name)
    broll_dir = os.path.join(get_profile_project_dir(project_id, profile_name), "Broll")
    export_dir = get_export_dir(profile_name)

    def add_items(folder: str, source_key: str, source_label: str) -> None:
        if not os.path.isdir(folder):
            return
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(video_exts):
                continue
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            items.append({
                "key": f"{source_key}:{name}",
                "name": name,
                "source": source_key,
                "source_label": source_label,
            })

    add_items(upload_dir, "upload", "Video đã tải lên")
    add_items(broll_dir, "broll", "Broll trong project")
    add_items(export_dir, "export", "Video xuất xưởng")
    return items


def _resolve_subtitle_source_path(project_id: str, profile_name: str, source_key: str) -> str:
    raw = str(source_key or "").strip()
    if not raw:
        raise ValueError("Chưa chọn nguồn video để bóc phụ đề.")
    if ":" in raw:
        source_type, file_name = raw.split(":", 1)
    else:
        source_type, file_name = "upload", raw
    file_name = _safe_name(file_name)
    project_dir = get_profile_project_dir(project_id, profile_name)
    if source_type == "broll":
        path = os.path.join(project_dir, "Broll", file_name)
    elif source_type == "export":
        path = os.path.join(get_export_dir(profile_name), file_name)
    else:
        path = os.path.join(_get_subtitle_video_dir(project_id, profile_name), file_name)
    if not os.path.exists(path):
        raise ValueError("Không tìm thấy video đã chọn để bóc phụ đề.")
    return path


def _transcribe_audio_to_srt(audio_path: str, display_name: str, config: Dict[str, Any]) -> str:
    mode = str(config.get("boc_bang_mode", "groq") or "groq").strip().lower()
    if mode == "ohfree":
        from googleapiclient.http import MediaFileUpload
        from tab2_modules.ai_services import _merge_related_short_segments, _words_to_base_segments, get_drive_service

        base_path = str(config.get("app_base_path", BASE_PATH) or BASE_PATH)
        client_secret = str(config.get("client_secret", "") or "").strip() or os.path.join(base_path, "client_secret.json")
        cookie = str(config.get("ohfree_cookie", "") or "").strip()
        if not os.path.exists(client_secret):
            raise ValueError(f"Thiếu file client_secret.json cho chế độ OhFree: {client_secret}")
        if not cookie:
            raise ValueError("Chưa có Cookie OhFree nên chưa thể bóc phụ đề theo tab 6.")

        file_id = None
        drive_service = get_drive_service(client_secret, base_path)
        try:
            file = drive_service.files().create(
                body={"name": f"subtitle_{int(time.time())}_{_safe_name(display_name)}.mp3", "parents": ["1K3iG8kCf8BEGYps9Q1pXWShuukGsEgas"]},
                media_body=MediaFileUpload(audio_path, mimetype="audio/mpeg"),
                fields="id",
            ).execute()
            file_id = file.get("id")
            drive_service.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"}).execute()
            drive_link = f"https://drive.google.com/file/d/{file_id}/view?usp=drive_link"
            res = requests.post(
                "https://tts.ohfree.me/api/mp3-to-text",
                headers={"User-Agent": "Mozilla/5.0", "Cookie": cookie},
                files={"url": (None, drive_link)},
                timeout=300,
            )
            if res.status_code != 200:
                raise ValueError(f"OhFree từ chối phụ đề: {res.text[:200]}")
            payload = res.json() or {}
            if not payload.get("success"):
                raise ValueError(f"OhFree báo lỗi: {payload.get('message', 'Không rõ nguyên nhân')}")
            words_list = (payload.get("data") or {}).get("words", []) or []
            if not words_list:
                raise ValueError("OhFree không trả về words để tạo SRT.")
            segments = _merge_related_short_segments(_words_to_base_segments(words_list), target_min=4.0, target_max=6.0)
            return _segments_to_srt_text(segments)
        finally:
            if file_id:
                try:
                    drive_service.files().delete(fileId=file_id).execute()
                except Exception:
                    pass

    groq_key = str(config.get("groq_key", "") or "").strip()
    if not groq_key:
        raise ValueError("Chưa cấu hình Groq key nên chưa bóc được phụ đề nhanh.")
    with open(audio_path, "rb") as handle:
        res = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {groq_key}"},
            files={"file": (os.path.basename(audio_path), handle)},
            data={"model": "whisper-large-v3", "language": "vi", "response_format": "verbose_json"},
            timeout=180,
        )
    if res.status_code != 200:
        raise ValueError(f"Groq báo lỗi khi bóc phụ đề: {res.text[:200]}")
    raw_segments = (res.json() or {}).get("segments", []) or []
    segments = []
    for item in raw_segments:
        text = re.sub(r"\s+", " ", str(item.get("text", "") or "")).strip()
        if text:
            segments.append({
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", 0.0) or 0.0),
                "text": text,
            })
    return _segments_to_srt_text(segments)


def _transcribe_video_to_srt(video_path: str, display_name: str, config: Dict[str, Any]) -> str:
    import tempfile
    from moviepy.editor import VideoFileClip

    temp_audio = os.path.join(tempfile.gettempdir(), f"temp_{uuid.uuid4().hex[:8]}.mp3")
    try:
        clip = VideoFileClip(video_path)
        if clip.audio is None:
            clip.close()
            raise ValueError("Video này không có audio để bóc phụ đề.")
        clip.audio.write_audiofile(temp_audio, logger=None)
        clip.close()
        return _transcribe_audio_to_srt(temp_audio, display_name, config)
    finally:
        if os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
            except Exception:
                pass


def get_subtitle_studio_data(project_id: str, profile_name: Optional[str] = None, voice_name: str = "") -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    if not project_id:
        return {"ok": False, "message": "Chưa chọn project.", "voices": [], "subtitle_text": "", "video_items": []}

    config = load_app_config()
    voices = list_project_voices(project_id, target_profile)
    video_items = _collect_subtitle_video_items(project_id, target_profile)
    project_data = _load_project_data(project_id, target_profile)
    voice_cache = project_data.setdefault("voice_srt_cache", {})
    video_cache = project_data.setdefault("subtitle_video_cache", {})

    selected_voice = str(voice_name or project_data.get("subtitle_selected_voice", "") or "").strip()
    if selected_voice and selected_voice not in voices:
        selected_voice = ""
    if not selected_voice and voices:
        selected_voice = voices[0]

    selected_video = str(project_data.get("subtitle_selected_video", "") or "").strip()
    known_video_keys = {item.get("key", "") for item in video_items}
    if selected_video and selected_video not in known_video_keys:
        selected_video = ""
    if not selected_video and video_items:
        selected_video = str(video_items[0].get("key", "") or "")

    source_type = str(project_data.get("subtitle_source_type", "voice") or "voice").strip().lower()
    if source_type not in {"voice", "video"}:
        source_type = "voice"

    subtitle_text = ""
    if source_type == "video" and selected_video:
        subtitle_text = str(video_cache.get(selected_video, "") or "")
    elif selected_voice:
        subtitle_text = str(voice_cache.get(selected_voice, "") or "")

    project_data["subtitle_selected_voice"] = selected_voice
    project_data["subtitle_selected_video"] = selected_video
    project_data["subtitle_source_type"] = source_type
    _save_project_data(project_id, target_profile, project_data)

    return {
        "ok": True,
        "project_id": project_id,
        "profile_name": target_profile,
        "voices": voices,
        "selected_voice": selected_voice,
        "video_items": video_items,
        "selected_video": selected_video,
        "source_type": source_type,
        "subtitle_text": subtitle_text,
        "output_file": os.path.basename(str(project_data.get("subtitle_last_output", "") or "")),
        "cached_count": len([name for name, text in voice_cache.items() if str(text or "").strip()]) + len([name for name, text in video_cache.items() if str(text or "").strip()]),
        "settings": {
            "boc_bang_mode": str(config.get("boc_bang_mode", "groq") or "groq"),
            "client_secret": str(config.get("client_secret", "") or ""),
            "ohfree_cookie": str(config.get("ohfree_cookie", "") or ""),
            "ohfree_cookie_set": bool(str(config.get("ohfree_cookie", "") or "").strip()),
        },
        "message": "Đã nạp studio phụ đề." if voices or video_items else "Project này chưa có voice hoặc video nào cho tab 6.",
    }


def save_uploaded_subtitle_videos(project_id: str, files: List[tuple[str, bytes]], profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    if not project_id:
        raise ValueError("Chưa chọn project để tải video lên tab phụ đề.")
    video_dir = _get_subtitle_video_dir(project_id, target_profile)
    saved: List[str] = []
    for file_name, content in files:
        clean_name = _safe_name(file_name)
        if not clean_name.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
            continue
        with open(os.path.join(video_dir, clean_name), "wb") as handle:
            handle.write(content)
        saved.append(clean_name)
    return {"ok": True, "saved": saved, "items": _collect_subtitle_video_items(project_id, target_profile)}


def save_subtitle_studio_data(
    project_id: str,
    voice_name: str,
    subtitle_text: str,
    profile_name: Optional[str] = None,
    source_type: str = "voice",
    source_name: str = "",
) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    if not project_id:
        raise ValueError("Chưa chọn project cho tab phụ đề.")

    clean_source_type = "video" if str(source_type or "voice").strip().lower() == "video" else "voice"
    source_key = str(source_name or voice_name or "").strip()
    if not source_key:
        raise ValueError("Chưa chọn nguồn phụ đề để lưu.")

    project_data = _load_project_data(project_id, target_profile)
    voice_cache = project_data.setdefault("voice_srt_cache", {})
    video_cache = project_data.setdefault("subtitle_video_cache", {})
    clean_text = str(subtitle_text or "").strip()

    if clean_source_type == "video":
        video_cache[source_key] = clean_text
        project_data["subtitle_selected_video"] = source_key
        project_data["subtitle_source_type"] = "video"
        base_name = os.path.splitext(source_key.split(":", 1)[-1])[0]
    else:
        clean_voice = str(voice_name or source_key).strip()
        voice_cache[clean_voice] = clean_text
        project_data["subtitle_selected_voice"] = clean_voice
        project_data["subtitle_source_type"] = "voice"
        base_name = os.path.splitext(clean_voice)[0]

    output_dir = _get_subtitle_output_dir(project_id, target_profile)
    output_file = os.path.join(output_dir, f"{_safe_name(base_name or 'subtitle')}.srt")
    _write_text_file_safe(output_file, clean_text)
    project_data["subtitle_last_output"] = output_file
    if clean_text and not str(project_data.get("script_source", "") or "").strip():
        project_data["script_source"] = clean_text
    _save_project_data(project_id, target_profile, project_data)
    return {"ok": True, "source_type": clean_source_type, "source_name": source_key, "subtitle_text": clean_text, "output_file": os.path.basename(output_file)}


def generate_subtitle_for_web(
    project_id: str,
    voice_name: str,
    profile_name: Optional[str] = None,
    source_type: str = "voice",
    source_name: str = "",
) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    if not project_id:
        raise ValueError("Chưa chọn project để bóc phụ đề.")

    config = load_app_config()
    config["app_base_path"] = BASE_PATH
    clean_source_type = "video" if str(source_type or "voice").strip().lower() == "video" else "voice"

    if clean_source_type == "video":
        video_key = str(source_name or voice_name or "").strip()
        video_path = _resolve_subtitle_source_path(project_id, target_profile, video_key)
        subtitle_text = _transcribe_video_to_srt(video_path, os.path.basename(video_path), config)
        return save_subtitle_studio_data(project_id, "", subtitle_text, target_profile, source_type="video", source_name=video_key)

    clean_voice = str(voice_name or source_name or "").strip()
    if not clean_voice:
        raise ValueError("Chưa chọn file voice cần bóc phụ đề.")
    voice_path = os.path.join(get_profile_project_dir(project_id, target_profile), "Voices", clean_voice)
    if not os.path.exists(voice_path):
        raise ValueError("Không tìm thấy file voice đã chọn.")

    subtitle_text = _transcribe_audio_to_srt(voice_path, clean_voice, config)
    return save_subtitle_studio_data(project_id, clean_voice, subtitle_text, target_profile, source_type="voice", source_name=clean_voice)


def _script_campaign_root(profile_name: Optional[str] = None) -> str:
    target_profile = ensure_active_profile(profile_name)
    preferred = os.path.join(get_profile_dir(target_profile), "Kho_Kich_Ban")
    legacy = os.path.join(BASE_PATH, "Workspace_Data", "Kho_Kich_Ban")
    if os.path.isdir(legacy):
        os.makedirs(legacy, exist_ok=True)
        return legacy
    os.makedirs(preferred, exist_ok=True)
    return preferred


def _clean_campaign_name(name: str) -> str:
    cleaned = "".join(ch for ch in str(name or "") if ch.isalnum() or ch in (" ", "_", "-"))
    return cleaned.strip().replace(" ", "_")[:80].strip("_")


def _campaign_file_name(name: str) -> str:
    base = _safe_name(str(name or "").strip())
    if not base:
        base = f"KB_{int(time.time())}"
    if not base.startswith("KB_"):
        base = f"KB_{base}"
    if not base.lower().endswith(".txt"):
        base += ".txt"
    return base


def list_script_campaigns(profile_name: Optional[str] = None) -> List[str]:
    root = _script_campaign_root(profile_name)
    items = [name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name))]
    items.sort(key=lambda item: os.path.getmtime(os.path.join(root, item)), reverse=True)
    return items


def create_script_campaign_folder(folder_name: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    clean_name = _clean_campaign_name(folder_name)
    if not clean_name:
        raise ValueError("Tên chiến dịch không hợp lệ.")
    folder = os.path.join(_script_campaign_root(profile_name), clean_name)
    os.makedirs(folder, exist_ok=True)
    _write_text_file_safe(os.path.join(folder, "global_keys.txt"), "")
    _write_text_file_safe(os.path.join(folder, "product_info.txt"), "")
    return get_script_studio_data("", profile_name, folder_name=clean_name)


def delete_script_campaign_folder(folder_name: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    clean_name = _clean_campaign_name(folder_name)
    if not clean_name:
        raise ValueError("Chưa chọn chiến dịch để xóa.")
    target = os.path.join(_script_campaign_root(profile_name), clean_name)
    if not os.path.isdir(target):
        raise ValueError("Không tìm thấy chiến dịch cần xóa.")
    shutil.rmtree(target, ignore_errors=True)
    return {"ok": True, "campaigns": list_script_campaigns(profile_name)}


def delete_script_campaign_file(folder_name: str, file_name: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    clean_folder = _clean_campaign_name(folder_name)
    if not clean_folder:
        raise ValueError("Chưa chọn chiến dịch.")
    clean_file = _campaign_file_name(file_name)
    folder = os.path.join(_script_campaign_root(profile_name), clean_folder)
    orig_path = os.path.join(folder, clean_file)
    spun_path = os.path.join(folder, f"spun_{clean_file.replace('KB_', '').replace('.txt', '')}.txt")
    if os.path.exists(orig_path):
        os.remove(orig_path)
    if os.path.exists(spun_path):
        os.remove(spun_path)
    return get_script_studio_data("", profile_name, folder_name=clean_folder)


def _call_kie_chat(api_key: str, prompt: str, temperature: float = 0.3) -> str:
    clean_key = str(api_key or "").strip()
    if not clean_key:
        raise ValueError("Chưa cấu hình Kie key trong hệ thống nên chưa chạy được tab kịch bản AI.")
    model_id = normalize_ai_model(load_app_config().get("ai_model", DEFAULT_AI_MODEL), "kie")
    endpoint = get_kie_endpoint(model_id) or "https://api.kie.ai/gemini-2.5-flash/v1/chat/completions"
    response = requests.post(
        endpoint,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {clean_key}"},
        json={
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(temperature or 0.3),
        },
        timeout=180,
    )
    if response.status_code != 200:
        raise ValueError(f"Kie AI báo lỗi: {response.text[:300]}")
    return str((((response.json() or {}).get("choices") or [{}])[0].get("message") or {}).get("content", "") or "").strip()


def get_script_studio_data(
    project_id: str,
    profile_name: Optional[str] = None,
    folder_name: str = "",
    file_name: str = "",
) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    config = load_app_config()
    campaigns = list_script_campaigns(target_profile)
    selected_campaign = _clean_campaign_name(folder_name) if folder_name else ""
    if selected_campaign and selected_campaign not in campaigns:
        selected_campaign = ""
    if not selected_campaign and campaigns:
        selected_campaign = campaigns[0]

    files: List[Dict[str, Any]] = []
    selected_file = _campaign_file_name(file_name) if file_name else ""
    original_text = ""
    spun_text = ""
    product_info = ""
    keys_text = ""
    urls_text = ""
    selected_hook = ""

    if selected_campaign:
        folder = os.path.join(_script_campaign_root(target_profile), selected_campaign)
        file_names = sorted(
            [name for name in os.listdir(folder) if name.startswith("KB_") and name.endswith(".txt")],
            key=lambda name: os.path.getmtime(os.path.join(folder, name)),
            reverse=True,
        )
        files = [
            {
                "name": name,
                "has_spun": os.path.exists(os.path.join(folder, f"spun_{name.replace('KB_', '').replace('.txt', '')}.txt")),
            }
            for name in file_names
        ]
        if selected_file and selected_file not in file_names:
            selected_file = ""
        if not selected_file and file_names:
            selected_file = file_names[0]
        product_info = _read_text_file_safe(os.path.join(folder, "product_info.txt"))
        keys_text = _read_text_file_safe(os.path.join(folder, "global_keys.txt"))
        urls_text = _read_text_file_safe(os.path.join(folder, "pending_urls.txt"))
        selected_hook = _read_text_file_safe(os.path.join(folder, "selected_hook.txt")).strip()
        if selected_file:
            original_text = _read_text_file_safe(os.path.join(folder, selected_file))
            spun_text = _read_text_file_safe(os.path.join(folder, f"spun_{selected_file.replace('KB_', '').replace('.txt', '')}.txt"))

    project_data = _load_project_data(project_id, target_profile) if project_id else _default_project_data()
    project_keys = project_data.get("script_keys", []) or []
    if isinstance(project_keys, list) and not keys_text:
        keys_text = "\n".join(str(item).strip() for item in project_keys if str(item).strip())

    source_text = original_text or str(project_data.get("script_source", "") or "")
    output_text = spun_text or str(project_data.get("script_output", "") or "")
    if not product_info:
        product_info = str(project_data.get("script_product_info", "") or "")

    selected_hook = str(selected_hook or project_data.get("script_selected_hook", "") or "").strip()
    if not selected_hook:
        key_lines = [line.strip() for line in str(keys_text or "").splitlines() if line.strip()]
        selected_hook = key_lines[0] if key_lines else ""

    return {
        "ok": True,
        "project_id": project_id,
        "profile_name": target_profile,
        "campaigns": campaigns,
        "selected_campaign": selected_campaign,
        "files": files,
        "selected_file": selected_file,
        "source_text": source_text,
        "original_text": original_text or source_text,
        "product_info": product_info,
        "keys_text": keys_text,
        "selected_hook": selected_hook,
        "prompt": str(config.get("tab7_prompt", project_data.get("script_prompt", _DEFAULT_SCRIPT_PROMPT)) or _DEFAULT_SCRIPT_PROMPT),
        "output_text": output_text,
        "urls_text": urls_text,
        "use_ytdlp": bool(config.get("tab7_use_ytdlp", True)),
        "threads": max(1, min(10, int(config.get("tab7_threads", 3) or 3))),
        "boc_bang_mode": str(config.get("tab7_boc_bang_mode", config.get("boc_bang_mode", "ohfree")) or "ohfree"),
        "kie_key": str(config.get("kie_key", "") or ""),
        "message": "Đã nạp trạm kịch bản." if selected_campaign or project_id else "Chưa có chiến dịch nào cho tab 7.",
    }


def save_script_studio_data(
    project_id: str,
    profile_name: Optional[str] = None,
    source_text: str = "",
    product_info: str = "",
    keys_text: str = "",
    prompt: str = "",
    output_text: str = "",
    folder_name: str = "",
    file_name: str = "",
    urls_text: str = "",
    use_ytdlp: Optional[bool] = None,
    threads: Optional[int] = None,
    boc_bang_mode: str = "",
    kie_key: str = "",
    selected_hook: str = "",
) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    config = load_app_config()
    if prompt is not None:
        config["tab7_prompt"] = str(prompt or "").strip() or _DEFAULT_SCRIPT_PROMPT
    if use_ytdlp is not None:
        config["tab7_use_ytdlp"] = bool(use_ytdlp)
    if threads is not None:
        config["tab7_threads"] = max(1, min(10, int(threads or 3)))
    if boc_bang_mode:
        config["tab7_boc_bang_mode"] = "ohfree" if str(boc_bang_mode).strip().lower() == "ohfree" else "groq"
    if kie_key is not None and str(kie_key or "").strip():
        config["kie_key"] = str(kie_key or "").strip()
    save_app_config(config)

    clean_campaign = _clean_campaign_name(folder_name)
    selected_file = _campaign_file_name(file_name) if file_name else ""
    final_hook = str(selected_hook or "").strip()
    if not final_hook:
        key_lines = [line.strip() for line in str(keys_text or "").splitlines() if line.strip()]
        final_hook = key_lines[0] if key_lines else ""
    if clean_campaign:
        folder = os.path.join(_script_campaign_root(target_profile), clean_campaign)
        os.makedirs(folder, exist_ok=True)
        _write_text_file_safe(os.path.join(folder, "product_info.txt"), _clean_multiline_text(product_info))
        _write_text_file_safe(os.path.join(folder, "global_keys.txt"), _clean_multiline_text(keys_text))
        _write_text_file_safe(os.path.join(folder, "pending_urls.txt"), _clean_multiline_text(urls_text))
        _write_text_file_safe(os.path.join(folder, "selected_hook.txt"), final_hook)
        if not selected_file and (str(source_text or "").strip() or str(output_text or "").strip()):
            # Lấy username TikTok từ URL đầu tiên trong urls_text
            import re as _re, random as _random
            _tiktok_username = ""
            _url_match = _re.search(r'tiktok\.com/@([A-Za-z0-9_.]+)', str(urls_text or ""))
            if _url_match:
                _tiktok_username = _url_match.group(1)[:20]
            # Lấy vài chữ đầu của kịch bản
            _script_preview = ""
            _raw_script = str(output_text or source_text or "").strip()
            if _raw_script:
                _words = _re.sub(r'[^\w\s]', '', _raw_script).split()
                _script_preview = "_".join(_words[:4]) if _words else ""
                _script_preview = _script_preview[:30]
            _rand_suffix = _random.randint(1000000000, 9999999999)
            _parts = [p for p in [_tiktok_username, _script_preview] if p]
            _base_name = "_".join(_parts) if _parts else "Manual"
            selected_file = f"KB_{_base_name}_{_rand_suffix}.txt"
        if selected_file and str(source_text or "").strip():
            _write_text_file_safe(os.path.join(folder, selected_file), str(source_text or "").strip())
        if selected_file and str(output_text or "").strip():
            spun_name = f"spun_{selected_file.replace('KB_', '').replace('.txt', '')}.txt"
            _write_text_file_safe(os.path.join(folder, spun_name), str(output_text or "").strip())

    if project_id:
        project_data = _load_project_data(project_id, target_profile)
        if source_text is not None:
            project_data["script_source"] = str(source_text or "").strip()
        project_data["script_product_info"] = str(product_info or "").strip()
        project_data["script_keys"] = [line.strip() for line in str(keys_text or "").splitlines() if line.strip()]
        project_data["script_prompt"] = str(prompt or "").strip() or _DEFAULT_SCRIPT_PROMPT
        project_data["script_output"] = str(output_text or "").strip()
        project_data["script_selected_hook"] = final_hook
        _save_project_data(project_id, target_profile, project_data)

    return get_script_studio_data(project_id, target_profile, folder_name=clean_campaign, file_name=selected_file)


def extract_script_assets(
    project_id: str,
    profile_name: Optional[str] = None,
    source_text: str = "",
    folder_name: str = "",
    file_name: str = "",
    kie_key: str = "",
) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    current = get_script_studio_data(project_id, target_profile, folder_name=folder_name, file_name=file_name)
    source = str(source_text or current.get("original_text", "") or current.get("source_text", "") or "").strip()
    if not source:
        project_data = _load_project_data(project_id, target_profile) if project_id else _default_project_data()
        selected_voice = str(project_data.get("subtitle_selected_voice", "") or "").strip()
        source = str((project_data.get("voice_srt_cache", {}) or {}).get(selected_voice, "") or "").strip()
    if not source:
        raise ValueError("Chưa có nội dung gốc để AI bóc key.")

    api_key = str(kie_key or current.get("kie_key", "") or load_app_config().get("kie_key", "") or "").strip()
    product_info = _call_kie_chat(api_key, f"""Phân tích voice và trích xuất THÔNG TIN SẢN PHẨM thô.\n- Mỗi ý một dòng ngắn gọn.\n- Không đánh số, không lan man.\n\nĐoạn voice:\n{source}""", temperature=0.2)
    keys_text = _call_kie_chat(api_key, f"""Phân tích voice và lấy ra đúng 10 ý chính để làm video TikTok bán hàng.\n- Mỗi key một dòng.\n- Không đánh số.\n\nĐây là đoạn voice:\n{source}""", temperature=0.3)

    extracted_keys = [line.strip() for line in str(keys_text or "").splitlines() if line.strip()]
    preserved_hook = str(current.get("selected_hook", "") or "").strip()
    if preserved_hook and preserved_hook not in extracted_keys:
        preserved_hook = ""

    result = save_script_studio_data(
        project_id,
        target_profile,
        source_text=source,
        product_info=product_info,
        keys_text=keys_text,
        prompt=str(current.get("prompt", _DEFAULT_SCRIPT_PROMPT) or _DEFAULT_SCRIPT_PROMPT),
        output_text=str(current.get("output_text", "") or ""),
        folder_name=folder_name,
        file_name=file_name,
        urls_text=str(current.get("urls_text", "") or ""),
        kie_key=api_key,
        selected_hook=preserved_hook or (extracted_keys[0] if extracted_keys else ""),
    )
    result["message"] = "AI đã bóc thông tin sản phẩm và 10 key cho tab 7."
    return result


def spin_script_web(
    project_id: str,
    profile_name: Optional[str] = None,
    source_text: str = "",
    product_info: str = "",
    keys_text: str = "",
    prompt: str = "",
    folder_name: str = "",
    file_name: str = "",
    selected_hook: str = "",
    kie_key: str = "",
) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    current = get_script_studio_data(project_id, target_profile, folder_name=folder_name, file_name=file_name)
    source = str(source_text or current.get("original_text", "") or current.get("source_text", "") or "").strip()
    if not source:
        raise ValueError("Chưa có kịch bản gốc hoặc phụ đề để xào lại.")

    final_product = str(product_info or current.get("product_info", "") or "").strip()
    final_keys = str(keys_text or current.get("keys_text", "") or "").strip()
    final_prompt = str(prompt or current.get("prompt", _DEFAULT_SCRIPT_PROMPT) or _DEFAULT_SCRIPT_PROMPT).strip() or _DEFAULT_SCRIPT_PROMPT
    chosen_hook = str(selected_hook or current.get("selected_hook", "") or "").strip()
    if not chosen_hook:
        key_lines = [line.strip() for line in final_keys.splitlines() if line.strip()]
        chosen_hook = key_lines[0] if key_lines else ""
    hook_instruction = f"\n\n--- MỆNH LỆNH TỐI CAO: DÙNG Ý SAU LÀM HOOK MỞ ĐẦU ---\n[{chosen_hook}]" if chosen_hook else ""

    user_prompt = (
        f"{final_prompt}\n\n"
        f"--- THÔNG TIN SẢN PHẨM ---\n{final_product}\n\n"
        f"--- CÁC Ý CHÍNH ---\n{final_keys}{hook_instruction}\n\n"
        f"--- KỊCH BẢN GỐC ---\n{source}"
    )
    api_key = str(kie_key or current.get("kie_key", "") or load_app_config().get("kie_key", "") or "").strip()
    output_text = _call_kie_chat(api_key, user_prompt, temperature=0.7)
    result = save_script_studio_data(
        project_id,
        target_profile,
        source_text=source,
        product_info=final_product,
        keys_text=final_keys,
        prompt=final_prompt,
        output_text=output_text,
        folder_name=folder_name,
        file_name=file_name,
        urls_text=str(current.get("urls_text", "") or ""),
        kie_key=api_key,
        selected_hook=chosen_hook,
    )
    result["message"] = "AI đã xào xong kịch bản theo đúng flow tab 7."
    return result


def start_script_scrape_job(
    profile_name: Optional[str] = None,
    folder_name: str = "",
    urls_text: str = "",
    max_workers: int = 3,
    use_ytdlp: bool = True,
    trans_mode: str = "ohfree",
    progress_callback=None,
) -> Dict[str, Any]:
    from tab7_modules.scraper import ScraperHandler

    target_profile = ensure_active_profile(profile_name)
    clean_campaign = _clean_campaign_name(folder_name)
    if not clean_campaign:
        raise ValueError("Chưa chọn hoặc tạo chiến dịch để chạy tab 7.")

    urls = [line.strip() for line in str(urls_text or "").splitlines() if "tiktok.com" in line.strip()]
    if not urls:
        raise ValueError("Chưa nhập link TikTok hợp lệ cho tab 7.")

    campaign_dir = os.path.join(_script_campaign_root(target_profile), clean_campaign)
    os.makedirs(campaign_dir, exist_ok=True)

    config = load_app_config()
    config["app_base_path"] = BASE_PATH
    config["tab7_use_ytdlp"] = bool(use_ytdlp)
    config["tab7_threads"] = max(1, min(10, int(max_workers or 3)))
    config["tab7_boc_bang_mode"] = "ohfree" if str(trans_mode or "ohfree").strip().lower() == "ohfree" else "groq"
    save_app_config(config)
    _write_text_file_safe(os.path.join(campaign_dir, "pending_urls.txt"), _clean_multiline_text(urls_text))

    job_id = uuid.uuid4().hex[:10]
    job = {
        "job_id": job_id,
        "type": "script-campaign",
        "profile_name": target_profile,
        "status": "queued",
        "progress": 0,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "campaign": clean_campaign,
        "total_items": len(urls),
        "completed_items": 0,
        "logs": [],
    }
    _WEB_JOBS[job_id] = job

    class _RootAdapter:
        def after(self, _delay, callback):
            if callable(callback):
                callback()

    class _UiAdapter:
        def __init__(self):
            self.use_ytdlp = SimpleNamespace(get=lambda: bool(use_ytdlp))
            self.boc_bang_mode = SimpleNamespace(get=lambda: config.get("tab7_boc_bang_mode", "ohfree"))
            self.main_app = SimpleNamespace(config=config, root=_RootAdapter())

        def add_log(self, msg):
            _append_job_log(job_id, msg, progress_callback=progress_callback)

        def safe_update_listbox(self):
            return None

    def worker():
        ui = _UiAdapter()
        handler = ScraperHandler(ui)
        success_count = 0
        try:
            _append_job_log(job_id, f"Bắt đầu bóc {len(urls)} link cho chiến dịch {clean_campaign}", progress=3, status="running", progress_callback=progress_callback)
            with ThreadPoolExecutor(max_workers=max(1, min(10, int(max_workers or 3)))) as executor:
                future_to_url = {
                    executor.submit(handler.process_single_url, url, idx, campaign_dir, str(config.get("ohfree_cookie", "") or "")): url
                    for idx, url in enumerate(urls)
                }
                for index, future in enumerate(as_completed(future_to_url), start=1):
                    try:
                        if future.result():
                            success_count += 1
                    except Exception as exc:
                        _append_job_log(job_id, f"Lỗi luồng tab 7: {exc}", progress_callback=progress_callback)
                    job["completed_items"] = index
                    percent = int((index / max(len(urls), 1)) * 100)
                    _append_job_log(job_id, f"Đã xử lý {index}/{len(urls)} link", progress=percent, progress_callback=progress_callback)
            _append_job_log(job_id, f"Hoàn tất tab 7: thành công {success_count}/{len(urls)} link.", progress=100, status="done", progress_callback=progress_callback)
        except Exception as exc:
            _append_job_log(job_id, f"Lỗi chạy chiến dịch tab 7: {exc}", status="error", progress_callback=progress_callback)

    threading.Thread(target=worker, daemon=True).start()
    return dict(job)


def list_rendered_videos(profile_name: Optional[str] = None, limit: int = 20) -> List[str]:
    target_profile = ensure_active_profile(profile_name)
    export_dir = get_export_dir(target_profile)
    if not os.path.isdir(export_dir):
        return []

    names = [
        item for item in os.listdir(export_dir)
        if item.lower().endswith(".mp4") and os.path.isfile(os.path.join(export_dir, item))
    ]
    names.sort(key=lambda name: os.path.getmtime(os.path.join(export_dir, name)), reverse=True)
    return names[:limit]


def list_shopee_job_rows(profile_name: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    target_profile = ensure_active_profile(profile_name)
    csv_path = get_shopee_csv_file(target_profile)
    jobs = load_shopee_jobs(csv_path=csv_path)
    return jobs[:limit]


def get_all_web_jobs(limit: int = 50, allowed_profiles: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    items = [dict(item) for item in _WEB_JOBS.values()]
    if allowed_profiles is not None:
        allowed = {sanitize_profile_name(name) for name in allowed_profiles if str(name or "").strip()}
        items = [item for item in items if sanitize_profile_name(item.get("profile_name", "") or "") in allowed]
    items.sort(key=lambda row: row.get("created_at", ""), reverse=True)
    return items[:limit]


def get_workspace_summary(profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    projects = list_projects(target_profile)
    jobs = list_shopee_job_rows(target_profile, limit=9999)
    videos = list_rendered_videos(target_profile, limit=9999)

    return {
        "profile_name": target_profile,
        "project_count": len(projects),
        "video_count": len(videos),
        "shopee_job_count": len(jobs),
        "pending_shopee_jobs": sum(1 for item in jobs if str(item.get("status", "") or "").strip() in ("", "Chưa đăng", "Chưa chuyển", "Sẵn sàng đăng")),
        "latest_videos": videos[:10],
    }


def _append_job_log(job_id: str, text: str, progress: Optional[int] = None, status: Optional[str] = None, progress_callback=None) -> None:
    job = _WEB_JOBS.get(job_id)
    if not job:
        return

    logs = job.setdefault("logs", [])
    logs.append(f"[{time.strftime('%H:%M:%S')}] {text}")
    if len(logs) > 200:
        job["logs"] = logs[-200:]

    if progress is not None:
        job["progress"] = max(0, min(100, int(progress)))
    if status:
        job["status"] = status
    job["status_text"] = text

    if progress_callback:
        progress_callback({"event": "job_progress", "job": dict(job)})


def _default_project_data() -> Dict[str, Any]:
    return {
        "videos": {},
        "trash": {},
        "timeline": [],
        "product_context": "",
        "product_name": "",
        "shopee_out_of_stock": False,
        "product_links": ["", "", "", "", "", ""],
        "voice_usage": {},
        "voice_srt_cache": {},
        "subtitle_selected_voice": "",
        "subtitle_selected_video": "",
        "subtitle_source_type": "voice",
        "subtitle_video_cache": {},
        "subtitle_last_output": "",
        "script_source": "",
        "script_product_info": "",
        "script_keys": [],
        "script_prompt": _DEFAULT_SCRIPT_PROMPT,
        "script_output": "",
    }


def _load_project_data(project_id: str, profile_name: str) -> Dict[str, Any]:
    data_file = os.path.join(get_profile_project_dir(project_id, profile_name), "project_data.json")
    if not os.path.exists(data_file):
        return _default_project_data()
    try:
        with open(data_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else _default_project_data()
    except Exception:
        return _default_project_data()


def _save_project_data(project_id: str, profile_name: str, data: Dict[str, Any]) -> None:
    data_file = os.path.join(get_profile_project_dir(project_id, profile_name), "project_data.json")
    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)


def _build_broll_text(project_data: Dict[str, Any], config: Dict[str, Any]) -> str:
    videos = project_data.get("videos", {}) or {}
    if not isinstance(videos, dict):
        return ""

    lines = []
    speed = float(config.get("video_speed", 1.0) or 1.0)
    for video_name, info in videos.items():
        info = info or {}
        duration = round(float(info.get("duration", 0) or 0) / max(speed, 0.1), 1)
        desc = str(info.get("description", "") or "")
        usage = int(info.get("usage_count", 0) or 0)
        lines.append(f"- File: '{video_name}' (Dài {duration}s) | Đã dùng: {usage} lần | Mô tả: {desc}")
    return "\n".join(lines) + ("\n" if lines else "")


def _update_broll_stats(project_id: str, profile_name: str, timeline: List[Dict[str, Any]]) -> None:
    project_data = _load_project_data(project_id, profile_name)
    videos = project_data.setdefault("videos", {})

    for row in timeline or []:
        picked = list(row.get("video_files", []) or [])
        if row.get("video_file") and row.get("video_file") not in picked:
            picked.append(row.get("video_file"))
        for video_name in picked:
            if video_name in videos:
                current_usage = int(videos[video_name].get("usage_count", 0) or 0)
                videos[video_name]["usage_count"] = current_usage + 1

    _save_project_data(project_id, profile_name, project_data)


def _increment_voice_usage(project_id: str, profile_name: str, voice_name: str) -> None:
    project_data = _load_project_data(project_id, profile_name)
    usage_db = project_data.setdefault("voice_usage", {})
    usage_db[voice_name] = int(usage_db.get(voice_name, 0) or 0) + 1
    _save_project_data(project_id, profile_name, project_data)


def start_mock_job(job_type: str, profile_name: Optional[str] = None, note: str = "", progress_callback=None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    job_id = uuid.uuid4().hex[:10]
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")

    job = {
        "job_id": job_id,
        "type": job_type,
        "profile_name": target_profile,
        "status": "queued",
        "progress": 0,
        "note": note,
        "created_at": created_at,
        "logs": [],
    }
    _WEB_JOBS[job_id] = job

    def worker():
        steps = [
            (10, "Đang khởi tạo job"),
            (35, "Đang nạp dữ liệu workspace"),
            (60, "Đang giả lập pipeline headless"),
            (85, "Đang hoàn tất"),
            (100, "Hoàn tất"),
        ]
        for progress, status_text in steps:
            time.sleep(0.6)
            _append_job_log(job_id, status_text, progress=progress, status="done" if progress >= 100 else "running", progress_callback=progress_callback)

    threading.Thread(target=worker, daemon=True).start()
    return dict(job)


def start_real_render_job(project_id: str, profile_name: Optional[str] = None, voice_names: Optional[List[str]] = None, progress_callback=None, created_by: str = "") -> Dict[str, Any]:
    """Validate rồi đẩy vào hàng đợi render_jobs (không chạy trực tiếp)."""
    target_profile = ensure_active_profile(profile_name)
    project_id = str(project_id or "").strip()
    projects = _read_projects_file(target_profile)

    if not project_id or project_id not in projects:
        raise ValueError("Bác chưa chọn đúng project để render.")

    available_voices = list_project_voices(project_id, target_profile)
    if voice_names:
        selected_voices = [item for item in voice_names if item in available_voices]
    else:
        selected_voices = available_voices

    if not selected_voices:
        raise ValueError("Project này chưa có file voice để render.")

    project_name = str((projects.get(project_id) or {}).get("name", project_id))

    job_dict = _enqueue_render_job(
        project_id=project_id,
        profile_name=target_profile,
        voice_names=selected_voices,
        project_name=project_name,
        created_by=created_by,
    )

    # Đảm bảo worker đang chạy
    start_render_queue_worker(progress_callback=progress_callback)

    return job_dict


def start_autopost_job(profile_name: Optional[str] = None, progress_callback=None) -> Dict[str, Any]:
    from autopost_runner import WebAutoPostRunner

    target_profile = ensure_active_profile(profile_name)
    config = load_app_config()

    selected_devices = [
        str(item or "").strip()
        for item in list(config.get("auto_post_selected_devices", []))
        if str(item or "").strip()
    ]
    if not selected_devices:
        raise ValueError("Chưa chọn thiết bị nào. Vào tab Quản Lý Điện Thoại, tick máy và bấm Lưu máy đã chọn.")

    adb_cmd = _resolve_adb_path_web()
    if not adb_cmd:
        raise FileNotFoundError("Không tìm thấy adb. Hãy cài ADB hoặc đặt adb.exe vào thư mục gốc.")

    pending_jobs = [
        item for item in list_shopee_job_rows(target_profile, limit=9999)
        if str(item.get("status", "") or "").strip() in ("", "Chưa đăng", "Chưa chuyển", "Sẵn sàng đăng")
    ]
    if not pending_jobs:
        raise ValueError("Tài khoản này chưa có job Shopee chờ đăng.")

    csv_path = get_shopee_csv_file(target_profile)
    phone_image_dir = os.path.join(BASE_PATH, "Phone_image")

    job_id = uuid.uuid4().hex[:10]
    job = {
        "job_id": job_id,
        "type": "autopost-real",
        "profile_name": target_profile,
        "status": "running",
        "progress": 5,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_items": len(pending_jobs),
        "completed_items": 0,
        "logs": [],
        "devices": selected_devices,
    }
    _WEB_JOBS[job_id] = job

    def log_cb(msg: str):
        _append_job_log(job_id, msg, progress_callback=progress_callback)

    def done_cb():
        _append_job_log(job_id, "⏹ Auto đăng hoàn tất.", progress=100, status="done", progress_callback=progress_callback)

    _append_job_log(job_id, f"🚀 Bắt đầu auto đăng trên {len(selected_devices)} máy — {len(pending_jobs)} job chờ.", progress=5, status="running", progress_callback=progress_callback)

    runner = WebAutoPostRunner(
        config=config,
        phone_image_dir=phone_image_dir,
        log_cb=log_cb,
        adb_cmd=adb_cmd,
        done_cb=done_cb,
    )
    # Store runner reference so stop endpoint can call runner.stop()
    job["_runner"] = runner

    runner.run_farm(selected_devices, csv_path)
    return {k: v for k, v in job.items() if k != "_runner"}


def get_web_job(job_id: str) -> Optional[Dict[str, Any]]:
    job = _WEB_JOBS.get(str(job_id or "").strip())
    return dict(job) if job else None


# ──────────────────────────────────────────────────────────────────────
#  RENDER JOB QUEUE  (SQLite-backed, single-worker)
# ──────────────────────────────────────────────────────────────────────
_QUEUE_WORKER_STARTED = False
_QUEUE_WORKER_LOCK = threading.Lock()
_QUEUE_CANCEL_FLAGS: Dict[str, bool] = {}          # job_id → True nếu bị hủy


def _enqueue_render_job(
    project_id: str,
    profile_name: str,
    voice_names: List[str],
    project_name: str = "",
    created_by: str = "",
) -> Dict[str, Any]:
    """Ghi 1 dòng pending vào DB, trả về dict tóm tắt + vị trí hàng đợi."""
    _ensure_auth_db()
    job_id = uuid.uuid4().hex[:10]
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_auth_connection()
    try:
        with conn:
            conn.execute(
                """INSERT INTO render_jobs
                   (job_id, job_type, profile_name, project_id, project_name,
                    voice_names, status, progress, status_text, created_at, created_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, "render-real", profile_name, project_id, project_name,
                 json.dumps(voice_names, ensure_ascii=False), "pending", 0,
                 "Đang xếp hàng chờ render", now, created_by),
            )
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM render_jobs WHERE status='pending'"
            ).fetchone()[0]
    finally:
        conn.close()

    job_dict = {
        "job_id": job_id,
        "type": "render-real",
        "profile_name": profile_name,
        "project_id": project_id,
        "project_name": project_name,
        "status": "pending",
        "progress": 0,
        "status_text": "Đang xếp hàng chờ render",
        "created_at": now,
        "queue_position": pending_count,
        "total_items": len(voice_names),
        "completed_items": 0,
        "selected_voices": voice_names,
        "logs": [],
    }
    _WEB_JOBS[job_id] = dict(job_dict)
    return job_dict


def cancel_render_job(job_id: str, actor: str = "") -> Dict[str, Any]:
    """Hủy job pending hoặc đang processing."""
    _ensure_auth_db()
    job_id = str(job_id or "").strip()
    conn = _get_auth_connection()
    try:
        row = conn.execute("SELECT status FROM render_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Không tìm thấy job này.")
        current = row["status"]
        if current in ("done", "cancelled"):
            raise ValueError(f"Job đã ở trạng thái {current}, không thể hủy.")
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with conn:
            conn.execute(
                "UPDATE render_jobs SET status='cancelled', status_text='Đã hủy', finished_at=? WHERE job_id=?",
                (now, job_id),
            )
        _QUEUE_CANCEL_FLAGS[job_id] = True
        # Cập nhật in-memory
        mem_job = _WEB_JOBS.get(job_id)
        if mem_job:
            mem_job["status"] = "cancelled"
            mem_job["status_text"] = "Đã hủy"
        return {"job_id": job_id, "status": "cancelled"}
    finally:
        conn.close()


def list_render_queue(allowed_profiles: Optional[List[str]] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Trả về danh sách render_jobs từ DB (kèm vị trí hàng đợi)."""
    _ensure_auth_db()
    conn = _get_auth_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM render_jobs ORDER BY created_at ASC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()

    items = []
    pending_idx = 0
    for row in rows:
        d = dict(row)
        d["type"] = d.pop("job_type", "render-real")
        try:
            d["selected_voices"] = json.loads(d.get("voice_names") or "[]")
        except Exception:
            d["selected_voices"] = []
        d["total_items"] = len(d["selected_voices"])
        if d["status"] == "pending":
            pending_idx += 1
            d["queue_position"] = pending_idx
        else:
            d["queue_position"] = 0
        items.append(d)

    if allowed_profiles is not None:
        allowed = {sanitize_profile_name(n) for n in allowed_profiles if str(n or "").strip()}
        items = [it for it in items if sanitize_profile_name(it.get("profile_name", "") or "") in allowed]

    items.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return items


def _update_render_job_db(job_id: str, **kwargs) -> None:
    """Cập nhật 1 row trong render_jobs (thread-safe)."""
    if not kwargs:
        return
    conn = _get_auth_connection()
    try:
        cols = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [job_id]
        with conn:
            conn.execute(f"UPDATE render_jobs SET {cols} WHERE job_id=?", vals)
    finally:
        conn.close()


def _process_single_render_job(job_row: Dict[str, Any], progress_callback=None) -> None:
    """Xử lý 1 job render (gọi bởi worker thread)."""
    job_id = job_row["job_id"]
    profile_name = job_row["profile_name"]
    project_id = job_row["project_id"]
    project_name = job_row.get("project_name", project_id)
    try:
        voice_names = json.loads(job_row.get("voice_names") or "[]")
    except Exception:
        voice_names = []

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    _update_render_job_db(job_id, status="processing", started_at=now, status_text="Đang xử lý")

    # Sync in-memory
    mem_job = _WEB_JOBS.get(job_id) or {}
    mem_job.update({
        "job_id": job_id, "type": "render-real", "profile_name": profile_name,
        "project_id": project_id, "project_name": project_name,
        "status": "processing", "progress": 0, "status_text": "Đang xử lý",
        "total_items": len(voice_names), "completed_items": 0,
        "selected_voices": voice_names, "logs": mem_job.get("logs", []),
    })
    _WEB_JOBS[job_id] = mem_job

    def _log(text, progress=None, status=None):
        if _QUEUE_CANCEL_FLAGS.get(job_id):
            raise InterruptedError("Job đã bị hủy bởi người dùng.")
        _append_job_log(job_id, text, progress=progress, status=status, progress_callback=progress_callback)
        _update_render_job_db(
            job_id,
            progress=mem_job.get("progress", 0),
            status_text=text,
            **({"status": status} if status else {}),
        )

    try:
        target_profile = ensure_active_profile(profile_name)
        config = load_app_config()
        # Merge per-workspace render config
        ws_cfg = _load_workspace_render_config(target_profile)
        for k in _WORKSPACE_RENDER_KEYS:
            if k in ws_cfg:
                config[k] = ws_cfg[k]
        config["app_base_path"] = BASE_PATH
        export_dir = get_export_dir(target_profile)
        excel_log_file = get_excel_log_file(target_profile)
        proj_dir = get_profile_project_dir(project_id, target_profile)

        _log(f"Bắt đầu render project {project_name}", progress=2, status="running")

        for index, voice_name in enumerate(voice_names, start=1):
            if _QUEUE_CANCEL_FLAGS.get(job_id):
                raise InterruptedError("Job đã bị hủy bởi người dùng.")

            base_progress = int(((index - 1) / max(len(voice_names), 1)) * 100)
            voice_path = os.path.join(proj_dir, "Voices", voice_name)
            if not os.path.exists(voice_path):
                _log(f"Bỏ qua {voice_name} vì không thấy file voice", progress=base_progress + 5)
                continue

            _log(f"[{voice_name}] Đang bóc băng", progress=base_progress + 8)
            voice_text = get_transcription(voice_path, voice_name, config.get("boc_bang_mode", "groq"), config, lambda msg: _log(msg))

            project_data = _load_project_data(project_id, target_profile)
            broll_data = project_data.get("videos", {}) or {}
            broll_text = _build_broll_text(project_data, config)

            _log(f"[{voice_name}] Đang tạo timeline AI", progress=base_progress + 28)
            timeline = get_director_timeline(voice_text, broll_text, config, lambda msg: _log(msg), voice_name)
            _update_broll_stats(project_id, target_profile, timeline)

            out_file = os.path.join(export_dir, f"[{project_name}] {os.path.splitext(voice_name)[0]}_{time.strftime('%H%M%S')}.mp4")
            _log(f"[{voice_name}] Đang render video", progress=base_progress + 55)
            render_faceless_video(voice_name, voice_path, timeline, proj_dir, project_name, config, out_file, export_dir, excel_log_file, lambda msg: _log(msg), broll_data)

            _increment_voice_usage(project_id, target_profile, voice_name)
            mem_job["completed_items"] = index
            _log(f"[{voice_name}] Render xong", progress=int((index / len(voice_names)) * 100))

        finished = time.strftime("%Y-%m-%d %H:%M:%S")
        _log(f"Hoàn tất render project {project_name}", progress=100, status="done")
        _update_render_job_db(job_id, status="done", progress=100, finished_at=finished,
                              status_text=f"Hoàn tất render project {project_name}",
                              logs=json.dumps(mem_job.get("logs", [])[-50:], ensure_ascii=False))
    except InterruptedError:
        finished = time.strftime("%Y-%m-%d %H:%M:%S")
        _log("Job đã bị hủy.", status="cancelled")
        _update_render_job_db(job_id, status="cancelled", finished_at=finished, status_text="Đã hủy")
    except Exception as exc:
        finished = time.strftime("%Y-%m-%d %H:%M:%S")
        err_msg = str(exc)
        _log(f"Lỗi render: {err_msg}", status="error")
        _update_render_job_db(job_id, status="failed", finished_at=finished,
                              error_message=err_msg, status_text=f"Lỗi: {err_msg}",
                              logs=json.dumps(mem_job.get("logs", [])[-50:], ensure_ascii=False))
    finally:
        _QUEUE_CANCEL_FLAGS.pop(job_id, None)


def _get_render_max_threads() -> int:
    """Đọc render_max_threads từ config, mặc định 1."""
    try:
        config = load_app_config()
        return max(1, min(16, int(config.get("render_max_threads") or 1)))
    except Exception:
        return 1


def _ensure_render_semaphore(max_threads: Optional[int] = None) -> threading.Semaphore:
    """Tạo hoặc cập nhật semaphore theo số luồng render."""
    global _RENDER_SEMAPHORE, _RENDER_MAX_THREADS
    target = max_threads or _get_render_max_threads()
    if _RENDER_SEMAPHORE is None or target != _RENDER_MAX_THREADS:
        _RENDER_MAX_THREADS = target
        _RENDER_SEMAPHORE = threading.Semaphore(target)
    return _RENDER_SEMAPHORE


def get_render_max_threads() -> int:
    """Public getter cho UI."""
    return _get_render_max_threads()


def _render_queue_worker(progress_callback=None) -> None:
    """Vòng lặp vô hạn: cứ 3s poll DB, dispatch lên thread pool (tối đa N luồng)."""
    while True:
        try:
            conn = _get_auth_connection()
            try:
                with conn:
                    conn.execute(
                        "UPDATE render_jobs SET status='pending', status_text='Đang xếp lại hàng (phục hồi)' "
                        "WHERE status='processing'"
                    )
            finally:
                conn.close()
            break
        except Exception:
            time.sleep(1)

    while True:
        try:
            sem = _ensure_render_semaphore()
            conn = _get_auth_connection()
            try:
                processing_count = conn.execute(
                    "SELECT COUNT(*) FROM render_jobs WHERE status='processing'"
                ).fetchone()[0]
                max_t = _RENDER_MAX_THREADS
                slots = max(0, max_t - processing_count)
                if slots <= 0:
                    time.sleep(2)
                    continue
                rows = conn.execute(
                    "SELECT * FROM render_jobs WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
                    (slots,)
                ).fetchall()
            finally:
                conn.close()

            if rows:
                for row in rows:
                    job_row = dict(row)
                    sem.acquire()
                    t = threading.Thread(
                        target=_worker_run_job,
                        args=(job_row, sem, progress_callback),
                        daemon=True,
                    )
                    t.start()
            else:
                time.sleep(3)
        except Exception as exc:
            print(f"[RenderWorker] Lỗi: {exc}")
            time.sleep(5)


def _worker_run_job(job_row: Dict[str, Any], sem: threading.Semaphore, progress_callback=None) -> None:
    """Wrapper chạy 1 job rồi release semaphore."""
    try:
        _process_single_render_job(job_row, progress_callback=progress_callback)
    finally:
        sem.release()


def start_render_queue_worker(progress_callback=None) -> None:
    """Khởi chạy worker thread (chỉ 1 lần duy nhất)."""
    global _QUEUE_WORKER_STARTED
    with _QUEUE_WORKER_LOCK:
        if _QUEUE_WORKER_STARTED:
            return
        _QUEUE_WORKER_STARTED = True
    _ensure_render_semaphore()
    t = threading.Thread(target=_render_queue_worker, args=(progress_callback,), daemon=True)
    t.start()


def _safe_name(name: str) -> str:
    return os.path.basename(str(name or "").strip())


def _ensure_project_runtime(project_id: str, profile_name: Optional[str] = None):
    target_profile = ensure_active_profile(profile_name)
    project_dir = get_profile_project_dir(project_id, target_profile)
    broll_dir = os.path.join(project_dir, "Broll")
    trash_dir = os.path.join(project_dir, "Broll_Trash")
    voice_dir = os.path.join(project_dir, "Voices")
    ref_dir = os.path.join(project_dir, "Ref_Images")
    os.makedirs(broll_dir, exist_ok=True)
    os.makedirs(trash_dir, exist_ok=True)
    os.makedirs(voice_dir, exist_ok=True)
    os.makedirs(ref_dir, exist_ok=True)
    return target_profile, project_dir, broll_dir, trash_dir, voice_dir, ref_dir


def _ensure_scene_meta(store: Dict[str, Any], vid_name: str) -> Dict[str, Any]:
    item = store.get(vid_name)
    if not isinstance(item, dict):
        item = {}
        store[vid_name] = item
    item.setdefault("description", "")
    item.setdefault("duration", 0.0)
    item.setdefault("usage_count", 0)
    item.setdefault("keep_audio", False)
    return item


def _get_video_duration(file_path: str) -> float:
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        creation_flags = 0x08000000 if os.name == "nt" else 0
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, creationflags=creation_flags)
        return round(float(out.decode("utf-8").strip()), 1)
    except Exception:
        return 0.0


def _thumb_path_for(video_dir: str, vid_name: str) -> str:
    thumb_dir = os.path.join(video_dir, ".thumbnails")
    os.makedirs(thumb_dir, exist_ok=True)
    return os.path.join(thumb_dir, f"{vid_name}.jpg")


def _preview_path_for(video_dir: str, vid_name: str) -> str:
    """Trả về đường dẫn file preview cho video"""
    preview_dir = os.path.join(video_dir, ".previews")
    os.makedirs(preview_dir, exist_ok=True)
    # Thêm hậu tố _preview vào tên file
    name_without_ext = os.path.splitext(vid_name)[0]
    return os.path.join(preview_dir, f"{name_without_ext}_preview.mp4")


def _generate_video_preview(video_path: str, preview_path: str, max_height: int = 720) -> bool:
    """
    Tạo preview video với chất lượng thấp hơn để load nhanh trên web
    
    Args:
        video_path: Đường dẫn video gốc
        preview_path: Đường dẫn lưu preview
        max_height: Chiều cao tối đa (720p hoặc 480p)
    
    Returns:
        True nếu thành công, False nếu thất bại
    """
    try:
        # Kiểm tra xem preview đã tồn tại chưa
        if os.path.exists(preview_path):
            return True
        
        # FFmpeg command: giảm resolution xuống 720p, bitrate thấp
        # scale='-2:720' = giữ aspect ratio, chiều cao 720px
        # -crf 28 = chất lượng thấp hơn (18-28, càng cao càng nén nhiều)
        # -preset fast = encode nhanh
        command = [
            "ffmpeg",
            "-i", video_path,
            "-vf", f"scale=-2:{max_height}",  # Giữ aspect ratio, height = max_height
            "-crf", "28",  # Chất lượng: 28 = nén nhiều, file nhỏ
            "-preset", "fast",  # Encode nhanh
            "-c:a", "aac",  # Audio codec
            "-b:a", "96k",  # Audio bitrate thấp
            "-y",  # Overwrite
            preview_path
        ]
        
        creation_flags = 0x08000000 if os.name == "nt" else 0
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            check=False,
            timeout=120  # Timeout 2 phút
        )
        
        # Kiểm tra kết quả
        if result.returncode == 0 and os.path.exists(preview_path):
            # So sánh kích thước file
            original_size = os.path.getsize(video_path) / (1024 * 1024)  # MB
            preview_size = os.path.getsize(preview_path) / (1024 * 1024)  # MB
            reduction = ((original_size - preview_size) / original_size * 100) if original_size > 0 else 0
            print(f"✅ Preview created: {os.path.basename(video_path)} - {original_size:.1f}MB → {preview_size:.1f}MB (-{reduction:.0f}%)")
            return True
        else:
            print(f"⚠️ FFmpeg failed for {os.path.basename(video_path)}")
            return False
    except subprocess.TimeoutExpired:
        print(f"⏱️ Preview timeout for {os.path.basename(video_path)}")
        return False
    except Exception as e:
        print(f"❌ Error creating preview for {os.path.basename(video_path)}: {e}")
        return False


def _extract_single_frame(video_path: str, seek_time: float, output_path: str) -> None:
    """Cắt 1 khung hình tại thời điểm seek_time"""
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{seek_time:.2f}",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        output_path,
    ]
    creation_flags = 0x08000000 if os.name == "nt" else 0
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creation_flags, check=False)


def _generate_quick_thumb(video_path: str, thumb_path: str) -> None:
    """Tạo ảnh bìa 5 KHUNG HÌNH ghép ngang để AI nhìn rõ hành động"""
    try:
        duration = _get_video_duration(video_path)
        if duration <= 0:
            duration = 1.0
        
        # Cắt 5 khung hình tại các mốc thời gian khác nhau
        timepoints = [duration * 0.1, duration * 0.3, duration * 0.5, duration * 0.7, duration * 0.9]
        temp_dir = tempfile.gettempdir()
        temp_paths = [os.path.join(temp_dir, f"frame_{i}_{os.path.basename(video_path)}.jpg") for i in range(5)]
        
        # Cắt 5 frame
        for i, t in enumerate(timepoints):
            _extract_single_frame(video_path, t, temp_paths[i])
        
        # Kiểm tra có frame nào thành công không
        valid_images = []
        for p in temp_paths:
            if os.path.exists(p):
                try:
                    valid_images.append(Image.open(p))
                except Exception:
                    pass
        
        if not valid_images:
            # Fallback: cắt 1 ảnh đơn giản
            _extract_single_frame(video_path, max(0.1, duration * 0.3), thumb_path)
            return
        
        # Lấy kích thước chuẩn
        base_w = 150
        base_h = int(150 * (valid_images[0].height / valid_images[0].width))
        
        # Resize và ghép 5 ảnh
        RESAMPLE_LANCZOS = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else getattr(Image, 'LANCZOS', 1)
        images = []
        for p in temp_paths:
            if os.path.exists(p):
                try:
                    img = Image.open(p)
                    images.append(img.resize((base_w, base_h), RESAMPLE_LANCZOS))
                except Exception:
                    images.append(Image.new('RGB', (base_w, base_h), color='black'))
            else:
                images.append(Image.new('RGB', (base_w, base_h), color='black'))
        
        # Ghép ngang 5 ảnh
        merged_img = Image.new('RGB', (base_w * 5, base_h))
        for i, img in enumerate(images):
            merged_img.paste(img, (base_w * i, 0))
        
        merged_img.save(thumb_path, quality=85)
        
        # Dọn rác
        for p in temp_paths:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
    except Exception as e:
        # Fallback: tạo ảnh đơn giản
        duration = _get_video_duration(video_path)
        seek_time = max(0.1, duration * 0.3 if duration > 0 else 0.5)
        _extract_single_frame(video_path, seek_time, thumb_path)


def _extract_ai_content(data: Dict[str, Any]) -> str:
    try:
        return str((data.get("choices") or [{}])[0].get("message", {}).get("content", "")).strip()
    except Exception:
        return ""


def _build_ai_prompt(context: str = "", hint_text: str = "") -> str:
    base_rule = (
        "QUY TẮC TỐI THƯỢNG: Trả về MÔ TẢ CHI TIẾT hành động trong 1-2 CÂU TIẾNG VIỆT. "
        "BẮT BUỘC kể chi tiết: sản phẩm là cái gì, hành động chính là gì, cách thức thực hiện ra sao."
    )
    parts = [base_rule]
    if context:
        parts.append(f"BỐI CẢNH DỰ ÁN: {context}")
    if hint_text:
        parts.append(f"GỢI Ý TỪ NGƯỜI DÙNG: {hint_text}")
    parts.append(
        "Nhiệm vụ: Ảnh ghép 5 KHUNG HÌNH (từ trái sang phải: 10% → 30% → 50% → 70% → 90% video) "
        "cho thấy chuỗi hành động liên tiếp. Hãy mô tả rõ sản phẩm, hành động chính diễn ra như thế nào, "
        "kết quả cuối cùng. Không gạch đầu dòng."
    )
    return "\n\n".join(parts)


def _encode_image_to_base64(image_path: str) -> str:
    try:
        with Image.open(image_path) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=90)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception:
        with open(image_path, "rb") as handle:
            return base64.b64encode(handle.read()).decode("utf-8")


def _build_ai_payload(prompt: str, target_image: str, ref1: str = "", ref2: str = "") -> Dict[str, Any]:
    content: List[Dict[str, Any]] = []
    if ref1 and os.path.exists(ref1):
        content.append({"type": "text", "text": "Ảnh mẫu sản phẩm 1:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_encode_image_to_base64(ref1)}"}})
    if ref2 and os.path.exists(ref2):
        content.append({"type": "text", "text": "Ảnh mẫu sản phẩm 2:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_encode_image_to_base64(ref2)}"}})
    content.append({"type": "text", "text": prompt})
    content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{target_image}"}})
    selected_model = normalize_ai_model(load_app_config().get("ai_model", DEFAULT_AI_MODEL), "kie")
    return {
        "model": selected_model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
    }


def _request_ai_scene_description(project_id: str, vid_name: str, profile_name: Optional[str] = None, hint_text: str = "") -> str:
    config = load_app_config()
    kie_key = str(config.get("kie_key", "")).strip()
    if not kie_key:
        raise ValueError("Chưa có Kie.ai key trong cấu hình nên chưa AI soi được cảnh.")

    target_profile, _, broll_dir, _, _, _ = _ensure_project_runtime(project_id, profile_name)
    video_path = os.path.join(broll_dir, _safe_name(vid_name))
    if not os.path.exists(video_path):
        raise ValueError("Không tìm thấy file cảnh cần AI soi.")

    thumb_path = _thumb_path_for(broll_dir, _safe_name(vid_name))
    if not os.path.exists(thumb_path):
        _generate_quick_thumb(video_path, thumb_path)
    if not os.path.exists(thumb_path):
        raise ValueError("Không tạo được ảnh đại diện cho cảnh này.")

    project_data = _load_project_data(project_id, target_profile)
    prompt = _build_ai_prompt(project_data.get("product_context", ""), hint_text)
    payload = _build_ai_payload(
        prompt,
        _encode_image_to_base64(thumb_path),
        project_data.get("ref_img_1", ""),
        project_data.get("ref_img_2", ""),
    )
    selected_model = normalize_ai_model(config.get("ai_model", DEFAULT_AI_MODEL), "kie")
    endpoint = get_kie_endpoint(selected_model) or "https://api.kie.ai/gemini-2.5-flash/v1/chat/completions"
    headers = {"Authorization": f"Bearer {kie_key}", "Content-Type": "application/json"}
    response = requests.post(endpoint, headers=headers, json=payload, timeout=90)
    if response.status_code != 200:
        raise ValueError(f"API AI lỗi: {response.status_code}")
    description = _extract_ai_content(response.json())
    if not description:
        raise ValueError("AI chưa trả về mô tả hợp lệ.")
    return description


def get_scene_manager_data(project_id: str, profile_name: Optional[str] = None, keyword: str = "") -> Dict[str, Any]:
    target_profile, _, broll_dir, trash_dir, voice_dir, _ = _ensure_project_runtime(project_id, profile_name)
    project_data = _load_project_data(project_id, target_profile)
    project_data.setdefault("videos", {})
    project_data.setdefault("trash", {})
    keyword = str(keyword or "").strip().lower()

    def build_scene_rows(folder: str, folder_key: str):
        rows = []
        for name in sorted(os.listdir(folder), key=lambda item: os.path.getmtime(os.path.join(folder, item)), reverse=True):
            if not name.lower().endswith((".mp4", ".mov")):
                continue
            if keyword and keyword not in name.lower():
                continue
            info = _ensure_scene_meta(project_data.setdefault(folder_key, {}), name)
            if not float(info.get("duration", 0) or 0):
                info["duration"] = _get_video_duration(os.path.join(folder, name))
            rows.append(
                {
                    "name": name,
                    "description": str(info.get("description", "") or ""),
                    "duration": round(float(info.get("duration", 0) or 0), 1),
                    "usage_count": int(info.get("usage_count", 0) or 0),
                    "keep_audio": bool(info.get("keep_audio", False)),
                    "folder": folder_key,
                }
            )
        return rows

    active_items = build_scene_rows(broll_dir, "videos")
    trash_items = build_scene_rows(trash_dir, "trash")

    voice_usage = project_data.get("voice_usage", {}) or {}
    voice_cache = project_data.get("voice_srt_cache", {}) or {}
    # Collect voices currently being processed by any active voice-transcribe job
    processing_voices: set = set()
    for job in _WEB_JOBS.values():
        if (job.get("type") == "voice-transcribe"
                and job.get("project_id") == project_id
                and job.get("status") not in ("done", "error")):
            processing_voices.update(job.get("voice_names", []))
    voices = []
    for voice_name in sorted([item for item in os.listdir(voice_dir) if item.lower().endswith((".mp3", ".wav", ".m4a"))]):
        if voice_name in voice_cache:
            v_status = "✅ Đã xong"
        elif voice_name in processing_voices:
            v_status = "🔄 Đang bóc SRT..."
        else:
            v_status = "⏳ Chờ bóc SRT"
        voices.append(
            {
                "name": voice_name,
                "usage_count": int(voice_usage.get(voice_name, 0) or 0),
                "status": v_status,
            }
        )

    missing_count = sum(1 for item in active_items if not str(item.get("description", "") or "").strip())
    _save_project_data(project_id, target_profile, project_data)
    return {
        "ok": True,
        "profile_name": target_profile,
        "project_id": project_id,
        "active_items": active_items,
        "trash_items": trash_items,
        "voice_items": voices,
        "missing_count": missing_count,
        "settings": {
            "product_context": str(project_data.get("product_context", "") or ""),
            "product_name": str(project_data.get("product_name", "") or ""),
            "shopee_out_of_stock": bool(project_data.get("shopee_out_of_stock", False)),
            "product_links": [normalize_shopee_product_link(item) for item in list(project_data.get("product_links", []))[:6]] + [""] * max(0, 6 - len(list(project_data.get("product_links", []))[:6])),
            "ref_img_1_name": os.path.basename(str(project_data.get("ref_img_1", "") or "")),
            "ref_img_2_name": os.path.basename(str(project_data.get("ref_img_2", "") or "")),
        },
    }


def save_scene_settings(project_id: str, profile_name: Optional[str] = None, context: str = "", product_name: str = "", shopee_out_of_stock: bool = False, product_links: Optional[List[str]] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    project_data = _load_project_data(project_id, target_profile)
    cleaned_links = [normalize_shopee_product_link(item) for item in (product_links or [])][:6]
    cleaned_links += [""] * max(0, 6 - len(cleaned_links))
    project_data["product_context"] = str(context or "").strip()
    project_data["product_name"] = str(product_name or "").strip()
    project_data["shopee_out_of_stock"] = bool(shopee_out_of_stock)
    project_data["product_links"] = cleaned_links
    _save_project_data(project_id, target_profile, project_data)
    return get_scene_manager_data(project_id, target_profile)


def update_scene_item(project_id: str, vid_name: str, profile_name: Optional[str] = None, description: Optional[str] = None, keep_audio: Optional[bool] = None, in_trash: bool = False) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    project_data = _load_project_data(project_id, target_profile)
    bucket = "trash" if in_trash else "videos"
    store = project_data.setdefault(bucket, {})
    item = _ensure_scene_meta(store, _safe_name(vid_name))
    if description is not None:
        item["description"] = str(description or "").strip()
    if keep_audio is not None:
        item["keep_audio"] = bool(keep_audio)
    _save_project_data(project_id, target_profile, project_data)
    return dict(item)


def move_scene_item(project_id: str, vid_name: str, profile_name: Optional[str] = None, to_trash: bool = True) -> Dict[str, Any]:
    target_profile, _, broll_dir, trash_dir, _, _ = _ensure_project_runtime(project_id, profile_name)
    clean_name = _safe_name(vid_name)
    src_dir, dst_dir = (broll_dir, trash_dir) if to_trash else (trash_dir, broll_dir)
    src = os.path.join(src_dir, clean_name)
    dst = os.path.join(dst_dir, clean_name)
    
    if not os.path.exists(src):
        raise ValueError(f"Không tìm thấy cảnh {clean_name} trong thư mục nguồn.")
    
    # Kiểm tra file đích đã tồn tại chưa (tránh conflict)
    if os.path.exists(dst):
        # File trùng tên ở đích, tự động đổi tên
        base, ext = os.path.splitext(clean_name)
        counter = 1
        while os.path.exists(dst):
            new_name = f"{base}_{counter}{ext}"
            dst = os.path.join(dst_dir, new_name)
            counter += 1
        clean_name = os.path.basename(dst)
    
    # Move video file với retry (fix Windows file locking)
    video_moved = False
    for attempt in range(3):
        try:
            shutil.move(src, dst)
            video_moved = True
            break
        except PermissionError:
            if attempt < 2:
                time.sleep(0.3)  # Đợi Windows giải phóng lock
            else:
                raise ValueError(f"❌ Không thể di chuyển {clean_name} - File đang được preview/player sử dụng. Vui lòng dừng xem video và thử lại.")
        except Exception as e:
            raise ValueError(f"❌ Lỗi di chuyển {clean_name}: {str(e)}")
    
    if not video_moved:
        raise ValueError(f"❌ Không thể di chuyển video {clean_name}")
    
    # Move thumbnail cùng với video (QUAN TRỌNG!)
    # Thumbnail có tên file.mp4.jpg hoặc file.mov.jpg
    original_name = _safe_name(vid_name)
    src_thumb = _thumb_path_for(src_dir, original_name)
    dst_thumb = _thumb_path_for(dst_dir, clean_name)
    if os.path.exists(src_thumb):
        try:
            # Đảm bảo thư mục đích tồn tại
            os.makedirs(os.path.dirname(dst_thumb), exist_ok=True)
            shutil.move(src_thumb, dst_thumb)
        except Exception as e:
            # Thumbnail không quan trọng bằng video, nhưng log lỗi để debug
            print(f"⚠️ Không move được thumbnail: {e}")

    # Cập nhật metadata
    project_data = _load_project_data(project_id, target_profile)
    from_key, to_key = ("videos", "trash") if to_trash else ("trash", "videos")
    project_data.setdefault(from_key, {})
    project_data.setdefault(to_key, {})
    
    # Lấy metadata từ key gốc (trước khi đổi tên nếu có conflict)
    original_name = _safe_name(vid_name)
    meta = project_data[from_key].pop(original_name, {"description": "", "duration": _get_video_duration(dst), "usage_count": 0, "keep_audio": False})
    project_data[to_key][clean_name] = meta if isinstance(meta, dict) else {"description": "", "duration": _get_video_duration(dst), "usage_count": 0, "keep_audio": False}
    _save_project_data(project_id, target_profile, project_data)
    
    return {"ok": True, "name": clean_name, "to_trash": to_trash, "renamed": clean_name != original_name}


def delete_scene_item_forever(project_id: str, vid_name: str, profile_name: Optional[str] = None, in_trash: bool = False) -> Dict[str, Any]:
    target_profile, _, broll_dir, trash_dir, _, _ = _ensure_project_runtime(project_id, profile_name)
    clean_name = _safe_name(vid_name)
    folder = trash_dir if in_trash else broll_dir
    file_path = os.path.join(folder, clean_name)
    thumb_path = _thumb_path_for(folder, clean_name)
    
    # Xóa file video với retry (fix Windows file locking)
    if os.path.exists(file_path):
        for attempt in range(3):
            try:
                os.remove(file_path)
                break
            except PermissionError:
                if attempt < 2:
                    time.sleep(0.3)  # Đợi Windows giải phóng lock
                else:
                    raise ValueError(f"Không thể xóa {clean_name} - File đang được sử dụng bởi chương trình khác. Vui lòng đóng preview/player và thử lại.")
            except Exception as e:
                raise ValueError(f"Lỗi xóa {clean_name}: {str(e)}")
    
    # Xóa thumbnail
    if os.path.exists(thumb_path):
        try:
            os.remove(thumb_path)
        except OSError:
            pass
    
    # Cập nhật metadata
    project_data = _load_project_data(project_id, target_profile)
    bucket = "trash" if in_trash else "videos"
    project_data.setdefault(bucket, {})
    project_data[bucket].pop(clean_name, None)
    _save_project_data(project_id, target_profile, project_data)
    return {"ok": True, "name": clean_name, "deleted": True}


def bulk_scene_action(project_id: str, names: List[str], action: str, profile_name: Optional[str] = None, in_trash: bool = False) -> Dict[str, Any]:
    completed = 0
    failed_items = []
    for name in names or []:
        try:
            if action == "trash":
                move_scene_item(project_id, name, profile_name, to_trash=True)
            elif action == "restore":
                move_scene_item(project_id, name, profile_name, to_trash=False)
            elif action == "delete":
                delete_scene_item_forever(project_id, name, profile_name, in_trash=in_trash)
            else:
                raise ValueError("Hành động không hợp lệ.")
            completed += 1
        except Exception as e:
            failed_items.append({"name": name, "error": str(e)})
            continue
    return {"ok": True, "completed": completed, "requested": len(names or []), "failed": failed_items}


def save_uploaded_broll_files(project_id: str, files: List[tuple[str, bytes]], profile_name: Optional[str] = None) -> Dict[str, Any]:
    """Lưu file và tạo thumbnail song song với ThreadPoolExecutor"""
    target_profile, _, broll_dir, _, _, _ = _ensure_project_runtime(project_id, profile_name)
    project_data = _load_project_data(project_id, target_profile)
    project_data.setdefault("videos", {})
    
    upload_timestamp = _now_text()  # Timestamp chung cho batch upload này
    
    # Bước 1: Lưu tất cả file trước
    saved_files = []
    for file_name, content in files:
        clean_name = _safe_name(file_name)
        if not clean_name.lower().endswith((".mp4", ".mov")):
            continue
        file_path = os.path.join(broll_dir, clean_name)
        try:
            with open(file_path, "wb") as handle:
                handle.write(content)
            saved_files.append((clean_name, file_path))
        except Exception as e:
            print(f"❌ Lỗi lưu file {clean_name}: {e}")
            continue
    
    if not saved_files:
        return {"ok": True, "saved": []}
    
    # Bước 2: Xử lý theo BATCH như desktop (7 luồng, từng batch 15 files)
    config = load_app_config()
    base_threads = int(config.get("threads", 8))
    max_workers = min(7, base_threads)  # Giống desktop: 7 threads
    batch_size = 15  # Mỗi batch 15 files
    
    num_files = len(saved_files)
    num_batches = (num_files + batch_size - 1) // batch_size
    print(f"📊 Xử lý {num_files} files theo {num_batches} batch (mỗi batch {batch_size} files, {max_workers} threads)")
    
    def process_single_video(clean_name: str, file_path: str):
        """Xử lý 1 video: tạo thumbnail + preview version + lấy duration"""
        duration = 0.0
        thumb_success = False
        preview_success = False
        preview_name = ""
        try:
            # Lấy độ dài video trước (nhanh hơn)
            duration = _get_video_duration(file_path)
            
            # Tạo thumbnail 5 khung hình
            thumb_path = _thumb_path_for(broll_dir, clean_name)
            if not os.path.exists(thumb_path):
                _generate_quick_thumb(file_path, thumb_path)
                thumb_success = os.path.exists(thumb_path)
            else:
                thumb_success = True
            
            # Tạo preview video (720p, low bitrate) để xem trên web
            preview_path = _preview_path_for(broll_dir, clean_name)
            preview_success = _generate_video_preview(file_path, preview_path, max_height=720)
            if preview_success:
                preview_name = os.path.relpath(preview_path, broll_dir).replace("\\", "/")
        except Exception as e:
            print(f"⚠️ Lỗi xử lý {clean_name}: {e}")
        
        return (clean_name, duration, thumb_success, preview_success, preview_name)
    
    # Chia thành batches và xử lý tuần tự từng batch
    video_metadata = {}
    for batch_idx in range(num_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, num_files)
        batch_files = saved_files[start_idx:end_idx]
        
        print(f"🔄 Đang xử lý batch {batch_idx + 1}/{num_batches} ({len(batch_files)} files)...")
        
        completed_count = 0
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_single_video, name, path): name for name, path in batch_files}
                for future in as_completed(futures):
                    try:
                        clean_name, duration, thumb_success, preview_success, preview_name = future.result()
                        video_metadata[clean_name] = {
                            "duration": duration,
                            "thumb_success": thumb_success,
                            "preview_success": preview_success,
                            "preview_name": preview_name
                        }
                        completed_count += 1
                        # Log progress trong batch
                        print(f"  ✓ {completed_count}/{len(batch_files)} hoàn tất trong batch {batch_idx + 1}")
                    except Exception as e:
                        file_name = futures[future]
                        print(f"❌ Future failed for {file_name}: {e}")
                        video_metadata[file_name] = {
                            "duration": 0.0,
                            "thumb_success": False,
                            "preview_success": False,
                            "preview_name": ""
                        }
                        completed_count += 1
        except Exception as e:
            print(f"❌ Batch {batch_idx + 1} error: {e}")
            # Fallback: Xử lý tuần tự cho batch này
            for clean_name, file_path in batch_files:
                try:
                    duration = _get_video_duration(file_path)
                    video_metadata[clean_name] = {
                        "duration": duration,
                        "thumb_success": False,
                        "preview_success": False,
                        "preview_name": ""
                    }
                except Exception:
                    video_metadata[clean_name] = {
                        "duration": 0.0,
                        "thumb_success": False,
                        "preview_success": False,
                        "preview_name": ""
                    }
        
        print(f"✅ Batch {batch_idx + 1}/{num_batches} hoàn tất")
    
    # Log tổng kết
    total_processed = len(video_metadata)
    total_success = sum(1 for meta in video_metadata.values() if meta.get("thumb_success", False))
    print(f"🎉 Hoàn tất xử lý tất cả {num_batches} batches - {total_processed} files ({total_success} thumbnails OK)")
    
    # Bước 3: Cập nhật metadata cho TẤT CẢ file đã lưu (quan trọng!)
    saved = []
    for clean_name, file_path in saved_files:
        meta = _ensure_scene_meta(project_data["videos"], clean_name)
        
        # Lấy metadata đã xử lý (hoặc default nếu không có)
        file_meta = video_metadata.get(clean_name, {
            "duration": 0.0,
            "thumb_success": False,
            "preview_success": False,
            "preview_name": ""
        })
        meta["duration"] = file_meta["duration"]
        meta["uploaded_at"] = upload_timestamp
        
        # Lưu thông tin preview (để frontend biết dùng file nào)
        if file_meta.get("preview_success") and file_meta.get("preview_name"):
            meta["preview_name"] = file_meta["preview_name"]
        
        saved.append(clean_name)
    
    _save_project_data(project_id, target_profile, project_data)
    return {"ok": True, "saved": saved}


def _normalize_voice_marker_text(text: str) -> str:
    normalized_text = unicodedata.normalize("NFD", str(text or ""))
    normalized_text = "".join(ch for ch in normalized_text if unicodedata.category(ch) != "Mn")
    normalized_text = normalized_text.lower()
    normalized_text = re.sub(r"[^a-z0-9\s]", " ", normalized_text)
    return re.sub(r"\s+", " ", normalized_text).strip()


def _looks_like_voice_test_intro(text: str) -> bool:
    normalized_text = _normalize_voice_marker_text(text)
    if not normalized_text:
        return False

    trigger_phrases = [
        "day la giong noi thu cua toi",
        "day la giong noi thu cua tui",
        "giong noi thu cua toi",
        "giong noi thu cua tui",
        "day la giong noi thu",
        "giong noi thu",
    ]
    if any(phrase in normalized_text for phrase in trigger_phrases):
        return True

    words = set(normalized_text.split())
    if not {"giong", "noi", "thu"}.issubset(words):
        return False

    extra_hits = sum(word in words for word in ["day", "la", "cua", "toi", "tui"])
    return extra_hits >= 2


def _parse_voice_timeline_text(timeline_text: str) -> List[Dict[str, Any]]:
    timeline_items = []
    pattern = re.compile(r"\[\s*([0-9]+(?:\.[0-9]+)?)s\s*-\s*([0-9]+(?:\.[0-9]+)?)s\s*\]:\s*(.+)")
    for line in (timeline_text or "").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        start_text, end_text, caption = match.groups()
        timeline_items.append(
            {
                "start": float(start_text),
                "end": float(end_text),
                "text": caption.strip(),
            }
        )
    return timeline_items


def _detect_voice_test_intro_end(timeline_text: str) -> float:
    accumulated_text = ""
    for idx, item in enumerate(_parse_voice_timeline_text(timeline_text)):
        if idx >= 6 or float(item.get("start", 0.0) or 0.0) > 15.0:
            break

        caption_text = _normalize_voice_marker_text(item.get("text", ""))
        if not caption_text:
            continue

        accumulated_text = f"{accumulated_text} {caption_text}".strip()
        if _looks_like_voice_test_intro(caption_text) or _looks_like_voice_test_intro(accumulated_text):
            return max(0.0, round(float(item.get("end", 0.0) or 0.0) + 0.05, 2))
    return 0.0


def _trim_voice_file(voice_path: str, trim_start_seconds: float) -> bool:
    if trim_start_seconds <= 0:
        return False

    base_name, extension = os.path.splitext(voice_path)
    temp_path = f"{base_name}.__trim__{extension}"
    extension = extension.lower()

    codec_args: List[str] = []
    if extension == ".mp3":
        codec_args = ["-codec:a", "libmp3lame", "-q:a", "2"]
    elif extension == ".wav":
        codec_args = ["-codec:a", "pcm_s16le"]
    elif extension == ".m4a":
        codec_args = ["-codec:a", "aac", "-b:a", "192k"]

    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{trim_start_seconds:.2f}",
        "-i",
        voice_path,
        *codec_args,
        temp_path,
    ]

    creation_flags = 0x08000000 if os.name == "nt" else 0
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        os.replace(temp_path, voice_path)
        return True
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _transcribe_voice_with_auto_trim(voice_name: str, voice_path: str, config: Dict[str, Any]) -> bool:
    """Transcribe, detect intro, trim if needed. Returns True if trimmed. Does NOT save to cache."""
    modes = ["ohfree", "groq"]
    timeline_text = ""
    last_error: Exception | None = None
    for mode in modes:
        try:
            timeline_text = get_transcription(voice_path, voice_name, mode, config, lambda msg: None)
            if timeline_text:
                break
        except Exception as exc:
            last_error = exc
            continue

    if not timeline_text:
        if last_error:
            raise last_error
        return False

    trim_start_seconds = _detect_voice_test_intro_end(timeline_text)
    if trim_start_seconds <= 0:
        return False
    return _trim_voice_file(voice_path, trim_start_seconds)


def _process_one_voice(name: str, file_path: str, config: Dict[str, Any], project_id: str, target_profile: str, job_id: str, index: int, total: int, progress_callback) -> str:
    """Process a single voice file: trim intro + transcribe + save to SRT cache. Returns result label."""
    step_base = int((index - 1) / total * 90) + 5
    step_end = int(index / total * 90) + 5
    modes = ["ohfree", "groq"]

    _append_job_log(job_id, f"[{name}] Đang bóc SRT...", progress=step_base, progress_callback=progress_callback)

    # Step 1: First transcription pass
    timeline_text = ""
    for mode in modes:
        try:
            timeline_text = get_transcription(file_path, name, mode, config, lambda msg: None)
            if timeline_text:
                break
        except Exception:
            continue

    if not timeline_text:
        _append_job_log(job_id, f"[{name}] Không bóc được SRT (chưa cấu hình API)", progress=step_end, progress_callback=progress_callback)
        return "no_api"

    # Step 2: Detect and trim intro
    was_trimmed = False
    trim_start = _detect_voice_test_intro_end(timeline_text)
    if trim_start > 0 and _trim_voice_file(file_path, trim_start):
        was_trimmed = True
        # Re-transcribe after trim to get accurate SRT
        timeline_text = ""
        for mode in modes:
            try:
                timeline_text = get_transcription(file_path, name, mode, config, lambda msg: None)
                if timeline_text:
                    break
            except Exception:
                continue

    # Step 3: Save to cache
    if timeline_text:
        proj_data = _load_project_data(project_id, target_profile)
        proj_data.setdefault("voice_srt_cache", {})[name] = timeline_text
        _save_project_data(project_id, target_profile, proj_data)

    label = "✂️ Cắt intro + bóc SRT xong" if was_trimmed else "✅ Bóc SRT xong"
    _append_job_log(job_id, f"[{name}] {label}", progress=step_end, progress_callback=progress_callback)
    return "trimmed" if was_trimmed else "done"


def save_uploaded_voice_files(project_id: str, files: List[tuple[str, bytes]], profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile, _, _, _, voice_dir, _ = _ensure_project_runtime(project_id, profile_name)
    project_data = _load_project_data(project_id, target_profile)
    project_data.setdefault("voice_usage", {})
    saved = []
    trimmed = []
    config = load_app_config()
    for file_name, content in files:
        clean_name = _safe_name(file_name)
        if not clean_name.lower().endswith((".mp3", ".wav", ".m4a")):
            continue
        file_path = os.path.join(voice_dir, clean_name)
        with open(file_path, "wb") as handle:
            handle.write(content)
        try:
            if _transcribe_voice_with_auto_trim(clean_name, file_path, config):
                trimmed.append(clean_name)
        except Exception:
            pass
        project_data["voice_usage"].setdefault(clean_name, 0)
        saved.append(clean_name)
    _save_project_data(project_id, target_profile, project_data)
    return {"ok": True, "saved": saved, "trimmed": trimmed}
def start_voice_transcribe_job(project_id: str, files: List[tuple[str, bytes]], profile_name: Optional[str] = None, progress_callback=None, max_workers: int = 3) -> Dict[str, Any]:
    """Save uploaded voices immediately then transcribe+trim in parallel background threads."""
    target_profile, _, _, _, voice_dir, _ = _ensure_project_runtime(project_id, profile_name)
    project_data = _load_project_data(project_id, target_profile)
    project_data.setdefault("voice_usage", {})
    config = load_app_config()

    saved = []
    for file_name, content in files:
        clean_name = _safe_name(file_name)
        if not clean_name.lower().endswith((".mp3", ".wav", ".m4a")):
            continue
        file_path = os.path.join(voice_dir, clean_name)
        with open(file_path, "wb") as handle:
            handle.write(content)
        project_data["voice_usage"].setdefault(clean_name, 0)
        saved.append(clean_name)

    _save_project_data(project_id, target_profile, project_data)

    if not saved:
        return {"ok": True, "saved": [], "job_id": None, "message": "Không có file hợp lệ."}

    job_id = uuid.uuid4().hex[:10]
    job = {
        "job_id": job_id,
        "type": "voice-transcribe",
        "profile_name": target_profile,
        "project_id": project_id,
        "voice_names": list(saved),
        "status": "running",
        "progress": 0,
        "created_at": _now_text(),
        "total_items": len(saved),
        "completed_items": 0,
        "logs": [],
    }
    _WEB_JOBS[job_id] = job

    def worker():
        import concurrent.futures
        total = max(len(saved), 1)
        workers = min(max_workers, total)
        _append_job_log(job_id, f"Bắt đầu xử lý {total} voice ({workers} luồng song song)", progress=5, status="running", progress_callback=progress_callback)

        completed_count = 0
        completed_lock = threading.Lock()

        def process(args):
            nonlocal completed_count
            index, name = args
            file_path = os.path.join(voice_dir, name)
            try:
                result = _process_one_voice(name, file_path, config, project_id, target_profile, job_id, index, total, progress_callback)
            except Exception as exc:
                step_end = int(index / total * 90) + 5
                _append_job_log(job_id, f"[{name}] Lỗi: {exc}", progress=step_end, progress_callback=progress_callback)
            finally:
                with completed_lock:
                    completed_count += 1
                    job["completed_items"] = completed_count

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                list(executor.map(process, enumerate(saved, start=1)))
            _append_job_log(job_id, f"Hoàn tất xử lý {total} voice", progress=100, status="done", progress_callback=progress_callback)
        except Exception as exc:
            _append_job_log(job_id, f"Lỗi job voice: {exc}", status="error", progress_callback=progress_callback)

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "saved": saved, "job_id": job_id, "job": dict(job)}


def delete_voice_file(project_id: str, voice_name: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile, _, _, _, voice_dir, _ = _ensure_project_runtime(project_id, profile_name)
    clean_name = _safe_name(voice_name)
    file_path = os.path.join(voice_dir, clean_name)
    if os.path.exists(file_path):
        os.remove(file_path)
    project_data = _load_project_data(project_id, target_profile)
    (project_data.get("voice_usage") or {}).pop(clean_name, None)
    (project_data.get("voice_srt_cache") or {}).pop(clean_name, None)
    _save_project_data(project_id, target_profile, project_data)
    return {"ok": True, "deleted": clean_name}


def get_voice_statuses(project_id: str, profile_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lightweight: returns only voice name + status, no scene data."""
    target_profile, _, _, _, voice_dir, _ = _ensure_project_runtime(project_id, profile_name)
    project_data = _load_project_data(project_id, target_profile)
    voice_cache = project_data.get("voice_srt_cache", {}) or {}
    processing_voices: set = set()
    for job in _WEB_JOBS.values():
        if (job.get("type") == "voice-transcribe"
                and job.get("project_id") == project_id
                and job.get("status") not in ("done", "error")):
            processing_voices.update(job.get("voice_names", []))
    result = []
    for voice_name in sorted([f for f in os.listdir(voice_dir) if f.lower().endswith((".mp3", ".wav", ".m4a"))]):
        if voice_name in voice_cache:
            status = "done"
        elif voice_name in processing_voices:
            status = "processing"
        else:
            status = "pending"
        result.append({"name": voice_name, "status": status})
    return result


def save_ref_image_file(project_id: str, ref_index: int, file_name: str, content: bytes, profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile, _, _, _, _, ref_dir = _ensure_project_runtime(project_id, profile_name)
    ext = os.path.splitext(_safe_name(file_name))[1].lower() or ".jpg"
    ref_path = os.path.join(ref_dir, f"ref_{int(ref_index)}{ext}")
    with open(ref_path, "wb") as handle:
        handle.write(content)
    project_data = _load_project_data(project_id, target_profile)
    project_data[f"ref_img_{int(ref_index)}"] = ref_path
    _save_project_data(project_id, target_profile, project_data)
    return {"ok": True, "file_name": os.path.basename(ref_path)}


def clear_ref_images_web(project_id: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    project_data = _load_project_data(project_id, target_profile)
    for key in ("ref_img_1", "ref_img_2"):
        ref_path = str(project_data.get(key, "") or "")
        if ref_path and os.path.exists(ref_path):
            try:
                os.remove(ref_path)
            except OSError:
                pass
        project_data.pop(key, None)
    _save_project_data(project_id, target_profile, project_data)
    return {"ok": True}


def ai_describe_single_scene(project_id: str, vid_name: str, profile_name: Optional[str] = None, hint_text: str = "") -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    description = _request_ai_scene_description(project_id, vid_name, target_profile, hint_text)
    update_scene_item(project_id, vid_name, target_profile, description=description, keep_audio=None, in_trash=False)
    return {"ok": True, "name": _safe_name(vid_name), "description": description}


def start_broll_ai_job(project_id: str, profile_name: Optional[str] = None, progress_callback=None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    project_data = _load_project_data(project_id, target_profile)
    project_data.setdefault("videos", {})
    target_names = [name for name, meta in project_data["videos"].items() if not str((meta or {}).get("description", "") or "").strip()]
    if not target_names:
        raise ValueError("Tất cả cảnh đang dùng đã có mô tả rồi.")

    job_id = uuid.uuid4().hex[:10]
    job = {
        "job_id": job_id,
        "type": "broll-ai",
        "profile_name": target_profile,
        "project_id": project_id,
        "status": "queued",
        "progress": 0,
        "created_at": _now_text(),
        "total_items": len(target_names),
        "completed_items": 0,
        "logs": [],
    }
    _WEB_JOBS[job_id] = job

    def worker():
        try:
            _append_job_log(job_id, f"Bắt đầu AI soi {len(target_names)} cảnh", progress=5, status="running", progress_callback=progress_callback)
            for index, name in enumerate(target_names, start=1):
                try:
                    result = ai_describe_single_scene(project_id, name, target_profile, "")
                    job["completed_items"] = index
                    _append_job_log(job_id, f"[{name}] {result.get('description', '')[:80]}", progress=int((index / max(len(target_names), 1)) * 100), progress_callback=progress_callback)
                except Exception as exc:
                    _append_job_log(job_id, f"[{name}] Lỗi AI: {exc}", progress=int((index / max(len(target_names), 1)) * 100), progress_callback=progress_callback)
            _append_job_log(job_id, "AI đã điền xong mô tả cảnh trám", progress=100, status="done", progress_callback=progress_callback)
        except Exception as exc:
            _append_job_log(job_id, f"Lỗi job cảnh trám: {exc}", status="error", progress_callback=progress_callback)

    threading.Thread(target=worker, daemon=True).start()
    return dict(job)


def get_media_file_path(project_id: str, profile_name: Optional[str], section: str, file_name: str) -> str:
    _, _, broll_dir, trash_dir, voice_dir, ref_dir = _ensure_project_runtime(project_id, profile_name)
    mapping = {
        "Broll": broll_dir,
        "Broll_Thumbs": os.path.join(broll_dir, ".thumbnails"),
        "Broll_Trash": trash_dir,
        "Broll_Trash_Thumbs": os.path.join(trash_dir, ".thumbnails"),
        "Voices": voice_dir,
        "Ref_Images": ref_dir,
    }
    if section not in mapping:
        raise ValueError("Loại media không hợp lệ.")
    target_name = _safe_name(file_name)
    primary_path = os.path.join(mapping[section], target_name)
    if os.path.exists(primary_path):
        return primary_path

    # Fallback for legacy profile layout under BASE_PATH/<profile>/Projects/...
    legacy_profile = sanitize_profile_name(profile_name or "")
    legacy_project_dir = os.path.join(BASE_PATH, legacy_profile, "Projects", str(project_id))
    legacy_mapping = {
        "Broll": os.path.join(legacy_project_dir, "Broll"),
        "Broll_Thumbs": os.path.join(legacy_project_dir, "Broll", ".thumbnails"),
        "Broll_Trash": os.path.join(legacy_project_dir, "Broll_Trash"),
        "Broll_Trash_Thumbs": os.path.join(legacy_project_dir, "Broll_Trash", ".thumbnails"),
        "Voices": os.path.join(legacy_project_dir, "Voices"),
        "Ref_Images": os.path.join(legacy_project_dir, "Ref_Images"),
    }
    legacy_root = legacy_mapping.get(section)
    if legacy_root:
        legacy_path = os.path.join(legacy_root, target_name)
        if os.path.exists(legacy_path):
            return legacy_path

    return primary_path


def get_export_video_path(profile_name: Optional[str], file_name: str) -> str:
    target_profile = ensure_active_profile(profile_name)
    return os.path.join(get_export_dir(target_profile), _safe_name(file_name))


def _get_workspace_render_config_path(profile_name: str) -> str:
    return os.path.join(get_profile_dir(profile_name), "render_config.json")


def _load_workspace_render_config(profile_name: str) -> Dict[str, Any]:
    path = _get_workspace_render_config_path(profile_name)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_workspace_render_config(profile_name: str, ws_config: Dict[str, Any]) -> None:
    path = _get_workspace_render_config_path(profile_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ws_config, f, ensure_ascii=False, indent=4)


# Các key render config được lưu riêng theo workspace
_WORKSPACE_RENDER_KEYS = {
    "threads", "broll_vol", "video_speed", "auto_speed_max",
    "video_bright", "use_trans", "use_sfx", "trans_duration",
    "selected_transitions",
}


def get_render_studio_data(project_id: str = "", profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    config = load_app_config()
    ws_cfg = _load_workspace_render_config(target_profile)
    projects = list_projects(target_profile)
    active_project_id = str(project_id or (projects[0]["id"] if projects else ""))
    voice_usage: Dict[str, Any] = {}
    voices: List[Dict[str, Any]] = []

    if active_project_id:
        project_data = _load_project_data(active_project_id, target_profile)
        voice_usage = project_data.get("voice_usage", {}) or {}
        for voice_name in list_project_voices(active_project_id, target_profile):
            voices.append(
                {
                    "name": voice_name,
                    "usage_count": int(voice_usage.get(voice_name, 0) or 0),
                    "selected": True,
                }
            )

    # Render settings: ưu tiên per-workspace, fallback global
    def _ws(key, default):
        return ws_cfg.get(key) if ws_cfg.get(key) is not None else config.get(key, default)

    ai_provider = normalize_ai_provider(str(config.get("ai_provider", DEFAULT_AI_PROVIDER) or DEFAULT_AI_PROVIDER))
    ai_model = normalize_ai_model(str(config.get("ai_model", DEFAULT_AI_MODEL) or DEFAULT_AI_MODEL), ai_provider)

    return {
        "ok": True,
        "profile_name": target_profile,
        "project_id": active_project_id,
        "projects": projects,
        "voice_items": voices,
        "transition_options": list(_TRANSITION_OPTIONS),
        "settings": {
            "groq_key": str(config.get("groq_key", "") or ""),
            "kie_key": str(config.get("kie_key", "") or ""),
            "openrouter_key": str(config.get("openrouter_key", "") or ""),
            "ai_provider": ai_provider,
            "ai_model": ai_model,
            "available_ai_models": get_ai_models_catalog(),
            "default_ai_provider": DEFAULT_AI_PROVIDER,
            "default_ai_model": DEFAULT_AI_MODEL,
            "font_path": str(config.get("font_path", "") or ""),
            "client_secret": str(config.get("client_secret", "") or ""),
            "ohfree_cookie": str(config.get("ohfree_cookie", "") or ""),
            "boc_bang_mode": str(config.get("boc_bang_mode", "groq") or "groq"),
            "threads": max(1, min(5, int(_ws("threads", 2) or 2))),
            "broll_vol": max(0, min(100, int(_ws("broll_vol", 30) or 30))),
            "video_speed": float(_ws("video_speed", 1.0) or 1.0),
            "auto_speed_max": float(_ws("auto_speed_max", 1.4) or 1.4),
            "video_bright": float(_ws("video_bright", 1.0) or 1.0),
            "use_trans": bool(_ws("use_trans", True)),
            "use_sfx": bool(_ws("use_sfx", True)),
            "trans_duration": float(_ws("trans_duration", 0.5) or 0.5),
            "selected_transitions": [
                item for item in list(_ws("selected_transitions", ["fade"]) or ["fade"])
                if item in {row["key"] for row in _TRANSITION_OPTIONS}
            ] or ["fade"],
            "render_max_threads": max(1, min(16, int(config.get("render_max_threads", 1) or 1))),
        },
    }


def save_render_studio_settings(project_id: str = "", profile_name: Optional[str] = None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    config = load_app_config()
    ws_cfg = _load_workspace_render_config(target_profile)
    payload = settings or {}
    allowed_transitions = {item["key"] for item in _TRANSITION_OPTIONS}

    # --- Global settings (API keys, paths, system) ---
    if payload.get("groq_key") is not None:
        new_value = str(payload.get("groq_key") or "").strip()
        if new_value or not str(config.get("groq_key", "") or "").strip():
            config["groq_key"] = new_value
    if payload.get("kie_key") is not None:
        new_value = str(payload.get("kie_key") or "").strip()
        if new_value or not str(config.get("kie_key", "") or "").strip():
            config["kie_key"] = new_value
    if payload.get("openrouter_key") is not None:
        new_value = str(payload.get("openrouter_key") or "").strip()
        if new_value or not str(config.get("openrouter_key", "") or "").strip():
            config["openrouter_key"] = new_value
    current_provider = normalize_ai_provider(str(config.get("ai_provider", DEFAULT_AI_PROVIDER) or DEFAULT_AI_PROVIDER))
    current_model = normalize_ai_model(str(config.get("ai_model", DEFAULT_AI_MODEL) or DEFAULT_AI_MODEL), current_provider)

    if payload.get("ai_provider") is not None:
        current_provider = normalize_ai_provider(str(payload.get("ai_provider") or DEFAULT_AI_PROVIDER).strip().lower())

    if payload.get("ai_model") is not None:
        current_model = normalize_ai_model(str(payload.get("ai_model") or DEFAULT_AI_MODEL).strip(), current_provider)
    elif payload.get("ai_provider") is not None:
        current_model = normalize_ai_model(current_model, current_provider)

    config["ai_provider"] = current_provider
    config["ai_model"] = current_model
    if payload.get("font_path") is not None:
        config["font_path"] = str(payload.get("font_path") or "").strip()
    if payload.get("client_secret") is not None:
        config["client_secret"] = str(payload.get("client_secret") or "").strip()
    if payload.get("ohfree_cookie") is not None:
        config["ohfree_cookie"] = str(payload.get("ohfree_cookie") or "").strip()
    if payload.get("boc_bang_mode") is not None:
        mode = str(payload.get("boc_bang_mode") or "groq").strip().lower()
        config["boc_bang_mode"] = "ohfree" if mode == "ohfree" else "groq"
    if payload.get("render_max_threads") is not None:
        config["render_max_threads"] = max(1, min(16, int(payload.get("render_max_threads") or 1)))

    # --- Per-workspace render settings ---
    if payload.get("threads") is not None:
        ws_cfg["threads"] = max(1, min(5, int(payload.get("threads") or 2)))
    if payload.get("broll_vol") is not None:
        ws_cfg["broll_vol"] = max(0, min(100, int(payload.get("broll_vol") or 30)))
    if payload.get("video_speed") is not None:
        ws_cfg["video_speed"] = max(0.5, min(3.0, float(payload.get("video_speed") or 1.0)))
    if payload.get("auto_speed_max") is not None:
        ws_cfg["auto_speed_max"] = max(1.0, min(3.0, float(payload.get("auto_speed_max") or 1.4)))
    if payload.get("video_bright") is not None:
        ws_cfg["video_bright"] = max(0.5, min(2.0, float(payload.get("video_bright") or 1.0)))
    if payload.get("use_trans") is not None:
        ws_cfg["use_trans"] = bool(payload.get("use_trans"))
    if payload.get("use_sfx") is not None:
        ws_cfg["use_sfx"] = bool(payload.get("use_sfx"))
    if payload.get("trans_duration") is not None:
        ws_cfg["trans_duration"] = max(0.3, min(2.0, float(payload.get("trans_duration") or 0.5)))
    if payload.get("selected_transitions") is not None:
        selected = [item for item in list(payload.get("selected_transitions") or []) if item in allowed_transitions]
        ws_cfg["selected_transitions"] = selected or ["fade"]

    save_app_config(config)
    _save_workspace_render_config(target_profile, ws_cfg)

    # Nếu thay đổi số luồng → cập nhật semaphore ngay
    if payload.get("render_max_threads") is not None:
        _ensure_render_semaphore(config["render_max_threads"])
    return get_render_studio_data(project_id, target_profile)


def _resolve_adb_path_web() -> str:
    adb_from_path = shutil.which("adb")
    if adb_from_path:
        return adb_from_path

    candidate_paths = [
        os.path.join(BASE_PATH, "adb.exe"),
        os.path.join(BASE_PATH, "platform-tools", "adb.exe"),
        os.path.join(os.getcwd(), "adb.exe"),
        os.path.join(os.getcwd(), "platform-tools", "adb.exe"),
    ]
    for env_key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        sdk_root = str(os.environ.get(env_key, "") or "").strip()
        if sdk_root:
            candidate_paths.append(os.path.join(sdk_root, "platform-tools", "adb.exe"))

    for path in candidate_paths:
        if path and os.path.exists(path):
            return path
    return ""


def _run_adb_command_web(args: List[str], serial: Optional[str] = None, timeout: int = 10) -> str:
    adb_executable = _resolve_adb_path_web()
    if not adb_executable:
        raise FileNotFoundError("Không tìm thấy adb trong máy.")
    command = [adb_executable]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    creation_flags = 0x08000000 if os.name == "nt" else 0
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
        creationflags=creation_flags,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or "ADB command failed")
    return process.stdout


def _parse_adb_devices_web(raw_output: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in str(raw_output or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices attached") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        extras: Dict[str, str] = {}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                extras[key] = value
        rows.append(
            {
                "serial": parts[0],
                "state": parts[1],
                "model": extras.get("model", ""),
                "brand": extras.get("product", ""),
                "android": "",
                "battery": "",
                "transport": extras.get("transport_id", ""),
            }
        )
    return rows


def _collect_phone_runtime_info(serial: str) -> Dict[str, str]:
    info = {"brand": "", "model": "", "android": "", "battery": ""}
    try:
        info["brand"] = _run_adb_command_web(["shell", "getprop", "ro.product.brand"], serial=serial, timeout=8).strip()
        info["model"] = _run_adb_command_web(["shell", "getprop", "ro.product.model"], serial=serial, timeout=8).strip()
        info["android"] = _run_adb_command_web(["shell", "getprop", "ro.build.version.release"], serial=serial, timeout=8).strip()
        battery_raw = _run_adb_command_web(["shell", "dumpsys", "battery"], serial=serial, timeout=8)
        match = re.search(r"level:\s*(\d+)", battery_raw)
        if match:
            info["battery"] = f"{match.group(1)}%"
    except Exception:
        pass
    return info


def list_phone_devices() -> Dict[str, Any]:
    config = load_app_config()
    selected_devices = [str(item or "").strip() for item in list(config.get("auto_post_selected_devices", [])) if str(item or "").strip()]
    adb_path = _resolve_adb_path_web()
    if not adb_path:
        return {"ok": True, "items": [], "selected_devices": selected_devices, "adb_path": "", "message": "Chưa tìm thấy adb trên máy này."}

    try:
        output = _run_adb_command_web(["devices", "-l"], timeout=15)
        items = _parse_adb_devices_web(output)
        for item in items:
            if item.get("state") == "device":
                item.update(_collect_phone_runtime_info(str(item.get("serial", ""))))
            item["selected"] = str(item.get("serial", "")) in selected_devices
        return {
            "ok": True,
            "items": items,
            "selected_devices": selected_devices,
            "adb_path": adb_path,
            "message": f"Phát hiện {len(items)} thiết bị ADB.",
        }
    except Exception as exc:
        return {"ok": True, "items": [], "selected_devices": selected_devices, "adb_path": adb_path, "message": str(exc)}


def save_phone_device_selection(serials: List[str]) -> Dict[str, Any]:
    config = load_app_config()
    cleaned = []
    seen = set()
    for serial in serials or []:
        value = str(serial or "").strip()
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
    config["auto_post_selected_devices"] = cleaned
    save_app_config(config)
    return {"ok": True, "selected_devices": cleaned}


def get_autopost_center_data(profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    config = load_app_config()
    jobs = list_shopee_job_rows(target_profile, limit=500)
    selected_devices = [str(item or "").strip() for item in list(config.get("auto_post_selected_devices", [])) if str(item or "").strip()]
    return {
        "ok": True,
        "profile_name": target_profile,
        "csv_path": get_shopee_csv_file(target_profile),
        "selected_devices": selected_devices,
        "settings": {
            "auto_post_stagger": int(config.get("auto_post_stagger", 15) or 15),
            "auto_post_click_delay": float(config.get("auto_post_click_delay", 1.0) or 1.0),
            "auto_post_upload_wait": int(config.get("auto_post_upload_wait", 25) or 25),
            "auto_post_rest_min": int(config.get("auto_post_rest_min", 8) or 8),
            "auto_post_rest_max": int(config.get("auto_post_rest_max", 15) or 15),
            "auto_post_match_threshold": float(config.get("auto_post_match_threshold", 0.82) or 0.82),
        },
        "jobs": jobs,
        "counts": {
            "total": len(jobs),
            "pending": sum(1 for item in jobs if str(item.get("status", "") or "").strip() in ("", "Chưa đăng", "Chưa chuyển", "Sẵn sàng đăng")),
            "done": sum(1 for item in jobs if "Đã đăng" in str(item.get("status", "") or "")),
            "processing": sum(1 for item in jobs if "Đang" in str(item.get("status", "") or "")),
        },
    }


def save_autopost_center_settings(profile_name: Optional[str] = None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = settings or {}
    config = load_app_config()
    if payload.get("auto_post_stagger") is not None:
        config["auto_post_stagger"] = max(1, min(300, int(payload.get("auto_post_stagger") or 15)))
    if payload.get("auto_post_click_delay") is not None:
        config["auto_post_click_delay"] = max(0.1, min(10.0, float(payload.get("auto_post_click_delay") or 1.0)))
    if payload.get("auto_post_upload_wait") is not None:
        config["auto_post_upload_wait"] = max(5, min(300, int(payload.get("auto_post_upload_wait") or 25)))
    if payload.get("auto_post_rest_min") is not None:
        config["auto_post_rest_min"] = max(1, min(300, int(payload.get("auto_post_rest_min") or 8)))
    if payload.get("auto_post_rest_max") is not None:
        config["auto_post_rest_max"] = max(config.get("auto_post_rest_min", 8), min(600, int(payload.get("auto_post_rest_max") or 15)))
    if payload.get("auto_post_match_threshold") is not None:
        config["auto_post_match_threshold"] = max(0.5, min(0.99, float(payload.get("auto_post_match_threshold") or 0.82)))
    save_app_config(config)
    return get_autopost_center_data(profile_name)


def _ensure_excel_log_file(profile_name: Optional[str] = None) -> str:
    target_profile = ensure_active_profile(profile_name)
    csv_path = get_excel_log_file(target_profile)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(_MANAGER_HEADERS)
    return csv_path


def list_manager_videos(profile_name: Optional[str] = None, keyword: str = "", status_filter: str = "all", limit: int = 500) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    csv_path = _ensure_excel_log_file(target_profile)
    keyword_text = str(keyword or "").strip().lower()
    filter_name = str(status_filter or "all").strip().lower()
    items: List[Dict[str, Any]] = []

    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            rows = list(reader)
    except Exception:
        rows = []

    rows.reverse()
    for row in rows:
        if len(row) < 4:
            continue
        date_text = str(row[0] or "")
        project_name = str(row[1] or "")
        voice_name = str(row[2] or "")
        file_path = str(row[3] or "")
        status_text = str(row[4] if len(row) > 4 else "Chưa chuyển" or "Chưa chuyển")
        video_name = os.path.basename(file_path)
        exists = os.path.exists(file_path)

        if keyword_text and keyword_text not in " ".join([date_text, project_name, voice_name, video_name, status_text]).lower():
            continue
        if filter_name == "done" and status_text != "Đã chuyển":
            continue
        if filter_name == "pending" and status_text == "Đã chuyển":
            continue
        if filter_name == "missing" and exists:
            continue

        items.append(
            {
                "date": date_text,
                "project": project_name,
                "voice": voice_name,
                "path": file_path,
                "video_name": video_name,
                "status": status_text,
                "exists": exists,
            }
        )

    return {
        "ok": True,
        "profile_name": target_profile,
        "items": items[:limit],
        "counts": {
            "total": len(items),
            "done": sum(1 for item in items if item.get("status") == "Đã chuyển"),
            "pending": sum(1 for item in items if item.get("status") != "Đã chuyển"),
            "missing": sum(1 for item in items if not item.get("exists")),
        },
    }


def update_manager_video_status(paths: List[str], new_status: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    csv_path = _ensure_excel_log_file(target_profile)
    path_set = {str(item or "").strip() for item in (paths or []) if str(item or "").strip()}
    if not path_set:
        raise ValueError("Chưa có video nào được chọn.")

    updated = 0
    rows: List[List[str]] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row_index, row in enumerate(reader):
            if row_index == 0:
                rows.append(row)
                continue
            while len(row) < len(_MANAGER_HEADERS):
                row.append("")
            if str(row[3] or "").strip() in path_set:
                row[4] = str(new_status or "").strip() or "Chưa chuyển"
                updated += 1
            rows.append(row)

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)
    return {"ok": True, "updated": updated}


def send_manager_videos_to_icloud(paths: List[str], profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    config = load_app_config()
    icloud_dir = str(config.get("icloud_path", "") or "").strip()
    if not icloud_dir or not os.path.exists(icloud_dir):
        raise ValueError("Chưa cấu hình thư mục iCloud hợp lệ trong phần mềm.")

    picked_paths = [str(item or "").strip() for item in (paths or []) if str(item or "").strip()]
    if not picked_paths:
        raise ValueError("Bác chưa chọn video nào để gửi iPhone.")

    folder_name = f"Video_Xuat_Tu_Web_{time.strftime('%d%m%Y_%H%M')}"
    target_dir = os.path.join(icloud_dir, folder_name)
    os.makedirs(target_dir, exist_ok=True)

    import random
    random.shuffle(picked_paths)
    copied_paths: List[str] = []
    stamp = time.strftime('%Y%m%d_%H%M')

    for index, file_path in enumerate(picked_paths, start=1):
        if not os.path.exists(file_path):
            continue
        base_name = os.path.basename(file_path)
        target_name = f"{index:02d}_[{stamp}]_{base_name}"
        shutil.copy2(file_path, os.path.join(target_dir, target_name))
        copied_paths.append(file_path)

    if copied_paths:
        update_manager_video_status(copied_paths, "Đã chuyển", target_profile)

    return {"ok": True, "folder_name": folder_name, "copied": len(copied_paths), "target_dir": target_dir}


def delete_manager_videos(paths: List[str], profile_name: Optional[str] = None) -> Dict[str, Any]:
    target_profile = ensure_active_profile(profile_name)
    csv_path = _ensure_excel_log_file(target_profile)
    path_set = {str(item or "").strip() for item in (paths or []) if str(item or "").strip()}
    if not path_set:
        raise ValueError("Chưa có video nào được chọn để xóa.")

    kept_rows: List[List[str]] = []
    deleted_names: List[str] = []
    removed = 0

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row_index, row in enumerate(reader):
            if row_index == 0:
                kept_rows.append(row)
                continue
            while len(row) < len(_MANAGER_HEADERS):
                row.append("")
            file_path = str(row[3] or "").strip()
            if file_path in path_set:
                removed += 1
                deleted_names.append(os.path.basename(file_path))
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                continue
            kept_rows.append(row)

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(kept_rows)

    try:
        delete_shopee_jobs(deleted_names, csv_path=get_shopee_csv_file(target_profile))
    except Exception:
        pass

    return {"ok": True, "removed": removed, "deleted_names": deleted_names}
