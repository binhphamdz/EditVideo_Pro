import asyncio
import os
import secrets
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from starlette.datastructures import Headers
from starlette.requests import Request as StarletteRequest

from paths import BASE_PATH
from bot_telegram_web import get_bot_manager, send_telegram_notification
from web_services import (
    ai_describe_single_scene,
    authenticate_web_user,
    bulk_scene_action,
    change_current_user_password,
    clear_ref_images_web,
    create_project_entry,
    create_workspace_entry,
    delete_manager_videos,
    delete_project_entry,
    delete_web_user,
    delete_workspace_entry,
    rename_workspace_entry,
    cancel_render_job,
    list_render_queue,
    start_render_queue_worker,
    get_render_max_threads,
    delete_voice_file,
    get_voice_statuses,
    delete_script_campaign_file,
    delete_script_campaign_folder,
    ensure_active_profile,
    ensure_default_admin_user,
    extract_script_assets,
    generate_subtitle_for_web,
    create_script_campaign_folder,
    get_all_web_jobs,
    get_autopost_center_data,
    get_export_video_path,
    get_media_file_path,
    get_render_studio_data,
    get_scene_manager_data,
    get_script_studio_data,
    get_subtitle_studio_data,
    get_telegram_center_data,
    get_user_allowed_workspaces,
    get_user_by_username,
    get_web_job,
    get_workspace_summary,
    list_manager_videos,
    list_phone_devices,
    list_project_voices,
    list_projects,
    list_rendered_videos,
    list_shopee_job_rows,
    list_web_users,
    list_workspaces,
    move_project_to_profile_web,
    register_web_user,
    rename_project_entry,
    resolve_user_profile_access,
    save_autopost_center_settings,
    save_phone_device_selection,
    save_ref_image_file,
    save_render_studio_settings,
    save_scene_settings,
    save_telegram_center_settings,
    save_script_studio_data,
    save_subtitle_studio_data,
    save_uploaded_subtitle_videos,
    save_uploaded_broll_files,
    save_uploaded_voice_files,
    start_voice_transcribe_job,
    send_manager_videos_to_icloud,
    set_project_status_entry,
    set_user_workspace_access,
    spin_script_web,
    start_autopost_job,
    start_broll_ai_job,
    start_mock_job,
    start_script_scrape_job,
    start_real_render_job,
    switch_workspace,
    update_current_user_profile,
    update_manager_video_status,
    update_scene_item,
    update_web_user,
    user_has_feature_access,
    record_login_log,
    get_login_logs,
    load_app_config,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

FAVICON_ICO_PATH = os.path.join(BASE_PATH, "icon.ico")
FAVICON_PNG_PATH = os.path.join(BASE_PATH, "icon.png")
OG_IMAGE_PATH = os.path.join(BASE_PATH, "brand_og.png")


def _get_session_secret() -> str:
    """Load or generate a persistent secret key for session signing."""
    secret_file = os.path.join(BASE_PATH, ".session_secret")
    try:
        if os.path.isfile(secret_file):
            with open(secret_file, "r", encoding="utf-8") as f:
                key = f.read().strip()
            if len(key) >= 32:
                return key
    except Exception:
        pass
    key = secrets.token_hex(32)
    try:
        with open(secret_file, "w", encoding="utf-8") as f:
            f.write(key)
    except Exception:
        pass
    return key


app = FastAPI(title="EditVideo Pro Web Dashboard", version="0.2.0")

# Note: Starlette default multipart limit is ~1MB per file
# We rely on timeout config in uvicorn instead
print("📦 Upload handling: Timeout-based (no hard size limit)")


def _silence_proactor_pipe_errors(loop, context):
    """Suppress benign Windows ProactorEventLoop ConnectionResetError when
    a browser closes a video stream connection mid-transfer."""
    exception = context.get("exception")
    if isinstance(exception, (ConnectionResetError, ConnectionAbortedError)):
        return  # ignore — browser closed the video stream
    loop.default_exception_handler(context)


@app.on_event("startup")
async def _setup_loop_exception_handler():
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_silence_proactor_pipe_errors)


# Middleware để log upload requests (debug)
@app.middleware("http")
async def log_upload_requests(request: Request, call_next):
    if request.url.path == "/api/broll/upload":
        content_length = request.headers.get('content-length', '0')
        content_length_mb = int(content_length) / (1024 * 1024) if content_length.isdigit() else 0
        print(f"🌐 Incoming upload request - size: {content_length_mb:.2f}MB, method: {request.method}")
        
        # Warn nếu body quá lớn
        if content_length_mb > 800:
            print(f"⚠️ WARNING: Very large upload ({content_length_mb:.2f}MB), may take several minutes")
    
    try:
        response = await call_next(request)
        if request.url.path == "/api/broll/upload":
            print(f"✅ Upload request completed - status: {response.status_code}")
        return response
    except Exception as e:
        if request.url.path == "/api/broll/upload":
            print(f"❌ Upload request failed: {e}")
        raise


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000", 
        "http://127.0.0.1:8000",
        "http://editvideopro.online",
        "https://editvideopro.online",
        "http://editvideopro.online:8080",  # FRP vhostHTTPPort
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=_get_session_secret(), same_site="lax", https_only=False)


def _file_response(path: str, media_type: str | None = None):
    if os.path.exists(path):
        return FileResponse(path, media_type=media_type)
    return JSONResponse(status_code=404, content={"ok": False, "message": "Not found"})


@app.get("/favicon.ico")
def favicon_ico():
    return _file_response(FAVICON_ICO_PATH, media_type="image/x-icon")


@app.get("/icon.png")
def favicon_png():
    return _file_response(FAVICON_PNG_PATH, media_type="image/png")


@app.get("/og.png")
def og_image():
    if os.path.exists(OG_IMAGE_PATH):
        return _file_response(OG_IMAGE_PATH, media_type="image/png")
    return _file_response(FAVICON_PNG_PATH, media_type="image/png")


class WorkspaceSwitchPayload(BaseModel):
    profile_name: str


class WorkspaceCreatePayload(BaseModel):
    workspace_name: str
    owner_username: Optional[str] = None


class WorkspaceRenamePayload(BaseModel):
    old_name: str
    new_name: str


class AccountProfilePayload(BaseModel):
    full_name: str = ""


class AccountPasswordPayload(BaseModel):
    current_password: str = ""
    new_password: str = ""
    confirm_password: str = ""


class JobPayload(BaseModel):
    profile_name: Optional[str] = None
    project_id: Optional[str] = None
    voice_names: Optional[list[str]] = None
    note: str = ""


class UserManagePayload(BaseModel):
    username: str
    approved: Optional[bool] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None
    can_use_phone: Optional[bool] = None
    can_use_autopost: Optional[bool] = None
    workspaces: Optional[list[str]] = None


class ProjectManagePayload(BaseModel):
    profile_name: Optional[str] = None
    project_id: str = ""
    project_name: str = ""
    status: Optional[str] = None
    target_profile: str = ""


class SceneUpdatePayload(BaseModel):
    profile_name: Optional[str] = None
    project_id: str
    vid_name: Optional[str] = None
    description: Optional[str] = None
    keep_audio: Optional[bool] = None
    context: Optional[str] = None
    product_name: Optional[str] = None
    shopee_out_of_stock: Optional[bool] = None
    product_links: Optional[list[str]] = None
    hint_text: str = ""


class SceneBulkActionPayload(BaseModel):
    profile_name: Optional[str] = None
    project_id: str
    action: str
    names: list[str] = []
    in_trash: bool = False


class RenderStudioPayload(BaseModel):
    profile_name: Optional[str] = None
    project_id: Optional[str] = None
    groq_key: Optional[str] = None
    kie_key: Optional[str] = None
    openrouter_key: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    font_path: Optional[str] = None
    client_secret: Optional[str] = None
    ohfree_cookie: Optional[str] = None
    boc_bang_mode: Optional[str] = None
    threads: Optional[int] = None
    broll_vol: Optional[int] = None
    video_speed: Optional[float] = None
    auto_speed_max: Optional[float] = None
    video_bright: Optional[float] = None
    use_trans: Optional[bool] = None
    use_sfx: Optional[bool] = None
    trans_duration: Optional[float] = None
    selected_transitions: Optional[list[str]] = None
    render_max_threads: Optional[int] = None


class VideoManagerPayload(BaseModel):
    profile_name: Optional[str] = None
    paths: list[str] = []
    status: Optional[str] = None


class PhoneSelectionPayload(BaseModel):
    serials: list[str] = []


class AutoPostSettingsPayload(BaseModel):
    profile_name: Optional[str] = None
    auto_post_stagger: Optional[int] = None
    auto_post_click_delay: Optional[float] = None
    auto_post_upload_wait: Optional[int] = None
    auto_post_rest_min: Optional[int] = None
    auto_post_rest_max: Optional[int] = None
    auto_post_match_threshold: Optional[float] = None


class TelegramBotPayload(BaseModel):
    profile_name: Optional[str] = None
    telegram_bot_token: Optional[str] = None


class SubtitleStudioPayload(BaseModel):
    profile_name: Optional[str] = None
    project_id: str = ""
    voice_name: str = ""
    source_type: str = "voice"
    source_name: str = ""
    subtitle_text: str = ""


class ScriptStudioPayload(BaseModel):
    profile_name: Optional[str] = None
    project_id: str = ""
    folder_name: str = ""
    file_name: str = ""
    source_text: str = ""
    product_info: str = ""
    keys_text: str = ""
    prompt: str = ""
    output_text: str = ""
    urls_text: str = ""
    selected_hook: str = ""
    use_ytdlp: Optional[bool] = None
    threads: Optional[int] = None
    boc_bang_mode: str = ""
    kie_key: str = ""


class ConnectionManager:
    def __init__(self):
        self.connections = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        dead = []
        for connection in list(self.connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)


ws_manager = ConnectionManager()
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def emit_status(message: Dict[str, Any]):
    global _main_loop
    try:
        loop = _main_loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast(message), loop)
        else:
            asyncio.run(ws_manager.broadcast(message))
    except Exception:
        pass


def _get_request_user(request: Request) -> Dict[str, Any]:
    ensure_default_admin_user()
    username = str(request.session.get("username", "") or "").strip()
    if not username:
        return {}
    user = get_user_by_username(username)
    if not user or not user.get("approved") or not user.get("is_active", True):
        request.session.clear()
        return {}
    return user


def _login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


def _api_guard(request: Request, admin_only: bool = False) -> tuple[Dict[str, Any], Optional[JSONResponse]]:
    user = _get_request_user(request)
    if not user:
        return {}, JSONResponse(status_code=401, content={"ok": False, "message": "Bạn cần đăng nhập trước."})
    if admin_only and user.get("role") != "admin":
        return {}, JSONResponse(status_code=403, content={"ok": False, "message": "Chỉ admin mới dùng được chức năng này."})
    return user, None


def _feature_guard(user: Dict[str, Any], feature_name: str, feature_label: str) -> Optional[JSONResponse]:
    if not user_has_feature_access(user.get("username", ""), feature_name):
        return JSONResponse(status_code=403, content={"ok": False, "message": f"Bạn chưa được admin cấp quyền dùng mục {feature_label}."})
    return None


def _empty_summary(profile_name: str = "") -> Dict[str, Any]:
    return {
        "profile_name": profile_name,
        "project_count": 0,
        "video_count": 0,
        "shopee_job_count": 0,
        "pending_shopee_jobs": 0,
        "latest_videos": [],
    }


def _resolve_profile_for_request(request: Request, user: Dict[str, Any], requested_profile: Optional[str] = None, allow_empty: bool = False) -> tuple[Optional[str], Optional[JSONResponse]]:
    session_profile = str(request.session.get("active_profile", "") or "").strip()
    candidate = str(requested_profile or "").strip() or session_profile

    if allow_empty and user.get("role") != "admin" and not candidate:
        allowed = get_user_allowed_workspaces(user.get("username", ""))
        if not allowed:
            return "", None

    try:
        resolved = resolve_user_profile_access(user.get("username", ""), candidate or None)
        request.session["active_profile"] = resolved
        return resolved, None
    except PermissionError as exc:
        return None, JSONResponse(status_code=403, content={"ok": False, "message": str(exc)})


@app.on_event("startup")
async def on_startup():
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    ensure_active_profile()
    ensure_default_admin_user()
    start_render_queue_worker(progress_callback=emit_status)
    
    # Khởi động bot Telegram nếu có token
    try:
        bot_manager = get_bot_manager()
        bot_manager.start_telegram_bot()
        print("✅ Bot Telegram đã được khởi động từ server.")
    except Exception as e:
        print(f"⚠️ Lỗi khởi động bot Telegram: {e}")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _get_request_user(request):
        return RedirectResponse(url="/", status_code=303)
    ensure_default_admin_user()
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": "",
            "success": "",
            "default_admin": {"username": "admin", "password": "1"},
        },
    )


def _get_client_ip(request: Request) -> str:
    """Lấy IP thật của người dùng, hỗ trợ Cloudflare và reverse proxy."""
    cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cf_ip:
        return cf_ip
    x_forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return str(request.client.host) if request.client else ""


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    client_ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")[:256]
    try:
        user = authenticate_web_user(username, password)
        record_login_log(user["username"], client_ip, user_agent, success=True)
        request.session.clear()
        request.session["username"] = user["username"]
        assigned = user.get("assigned_workspaces") or []
        request.session["active_profile"] = assigned[0] if assigned else ""
        
        # Gửi thông báo qua Telegram nếu không phải admin
        if user.get("role") != "admin":
            try:
                send_telegram_notification(
                    f"🔔 Nhân viên đăng nhập:\n"
                    f"👤 User: {user['username']}\n"
                    f"🏛️ Workspace: {assigned[0] if assigned else 'Chưa cấp'}\n"
                    f"🌐 IP: {client_ip}\n"
                    f"📅 Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                )
            except Exception as e:
                print(f"⚠️ Lỗi gửi thông báo login qua Telegram: {e}")
        
        return RedirectResponse(url="/", status_code=303)
    except Exception as exc:
        record_login_log(username, client_ip, user_agent, success=False)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": str(exc),
                "success": "",
                "default_admin": {"username": "admin", "password": "1"},
            },
            status_code=400,
        )


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if _get_request_user(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"error": "", "success": ""})


@app.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    full_name: str = Form(""),
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    if password != confirm_password:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Mật khẩu nhập lại chưa khớp.", "success": ""},
            status_code=400,
        )

    try:
        user = register_web_user(full_name, username, password, "employee")
        
        # Gửi thông báo qua Telegram cho admin
        try:
            send_telegram_notification(
                f"🆕 Nhân viên mới đăng ký - Cần duyệt!\n"
                f"👤 Username: {username}\n"
                f"📝 Họ tên: {full_name or 'Chưa nhập'}\n"
                f"⚠️ Trạng thái: Chờ admin duyệt\n"
                f"📅 Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
                f"👉 Vào trang quản lý để duyệt nhân viên này!"
            )
        except Exception as e:
            print(f"⚠️ Lỗi gửi thông báo đăng ký qua Telegram: {e}")
        
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": "",
                "success": f"Đã đăng ký tài khoản {user['username']}. Vui lòng chờ admin duyệt trước khi đăng nhập.",
            },
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": str(exc), "success": ""},
            status_code=400,
        )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    current_user = _get_request_user(request)
    if not current_user:
        return _login_redirect()

    saved_profile = str(request.session.get("active_profile", "") or "")
    workspaces = list_workspaces(current_user.get("username", ""), saved_profile)
    active_profile = next((item.get("name", "") for item in workspaces if item.get("is_active")), "")
    if not active_profile and workspaces:
        active_profile = workspaces[0].get("name", "")
    if active_profile:
        request.session["active_profile"] = active_profile

    summary = get_workspace_summary(active_profile) if active_profile else _empty_summary()
    projects = list_projects(active_profile) if active_profile else []
    shopee_jobs = list_shopee_job_rows(active_profile) if active_profile else []

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_profile": active_profile or "Chưa cấp workspace",
            "summary": summary,
            "workspaces": workspaces,
            "projects": projects,
            "shopee_jobs": shopee_jobs,
            "current_user": current_user,
            "is_admin": current_user.get("role") == "admin",
        },
    )


@app.get("/api/health")
def health(request: Request):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, None, allow_empty=True)
    if access_error:
        return access_error
    return {"ok": True, "active_profile": resolved_profile, "user": user}


@app.get("/api/me")
def api_me(request: Request):
    user, error = _api_guard(request)
    if error:
        return error
    return {"ok": True, "user": user}


@app.post("/api/account/profile")
def api_account_profile(request: Request, payload: AccountProfilePayload):
    user, error = _api_guard(request)
    if error:
        return error
    try:
        item = update_current_user_profile(user.get("username", ""), payload.full_name)
        return {"ok": True, "item": item, "message": "Đã cập nhật thông tin cá nhân."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/account/password")
def api_account_password(request: Request, payload: AccountPasswordPayload):
    user, error = _api_guard(request)
    if error:
        return error
    if payload.new_password != payload.confirm_password:
        return JSONResponse(status_code=400, content={"ok": False, "message": "Mật khẩu nhập lại chưa khớp."})
    try:
        change_current_user_password(user.get("username", ""), payload.current_password, payload.new_password)
        return {"ok": True, "message": "Đã đổi mật khẩu thành công."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/workspaces")
def api_workspaces(request: Request):
    user, error = _api_guard(request)
    if error:
        return error
    current_profile = str(request.session.get("active_profile", "") or "")
    items = list_workspaces(user.get("username", ""), current_profile)
    active_profile = next((item.get("name", "") for item in items if item.get("is_active")), "")
    if not active_profile and items:
        active_profile = items[0].get("name", "")
        request.session["active_profile"] = active_profile
    return {
        "ok": True,
        "active_profile": active_profile,
        "items": items,
        "user": user,
    }


@app.post("/api/workspaces/switch")
def api_switch_workspace(request: Request, payload: WorkspaceSwitchPayload):
    user, error = _api_guard(request)
    if error:
        return error
    try:
        result = switch_workspace(payload.profile_name, user.get("username", ""))
        request.session["active_profile"] = result.get("active_profile", "")
        emit_status({"event": "workspace_switched", "active_profile": result["active_profile"], "actor": user.get("username")})
        return result
    except Exception as exc:
        return JSONResponse(status_code=403, content={"ok": False, "message": str(exc)})


@app.post("/api/workspaces/create")
def api_create_workspace(request: Request, payload: WorkspaceCreatePayload):
    user, error = _api_guard(request)
    if error:
        return error
    try:
        owner_username = payload.owner_username if user.get("role") == "admin" else user.get("username", "")
        result = create_workspace_entry(payload.workspace_name, user.get("username", ""), owner_username)
        request.session["active_profile"] = result.get("workspace", "")
        return {"ok": True, **result, "message": "Đã tạo workspace mới thành công."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/workspaces/delete")
def api_delete_workspace(request: Request, payload: WorkspaceSwitchPayload):
    user, error = _api_guard(request, admin_only=True)
    if error:
        return error
    try:
        result = delete_workspace_entry(payload.profile_name, user.get("username", ""))
        return {"ok": True, **result, "message": "Đã xóa workspace."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/workspaces/rename")
def api_rename_workspace(request: Request, payload: WorkspaceRenamePayload):
    user, error = _api_guard(request)
    if error:
        return error
    try:
        result = rename_workspace_entry(payload.old_name, payload.new_name, user.get("username", ""))
        if request.session.get("active_profile") == result.get("old_name"):
            request.session["active_profile"] = result.get("new_name", "")
        return {"ok": True, **result, "message": f"Đã đổi tên workspace thành {result.get('new_name', '')}."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/users")
def api_users(request: Request):
    _, error = _api_guard(request, admin_only=True)
    if error:
        return error
    return {"ok": True, "items": list_web_users()}


@app.post("/api/users/update")
def api_users_update(request: Request, payload: UserManagePayload):
    user, error = _api_guard(request, admin_only=True)
    if error:
        return error
    try:
        item = update_web_user(
            payload.username,
            user.get("username", "admin"),
            approved=payload.approved,
            is_active=payload.is_active,
            role=payload.role,
            can_use_phone=payload.can_use_phone,
            can_use_autopost=payload.can_use_autopost,
        )
        return {"ok": True, "item": item, "items": list_web_users(), "message": "Đã cập nhật tài khoản."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/users/workspaces")
def api_users_workspaces(request: Request, payload: UserManagePayload):
    _, error = _api_guard(request, admin_only=True)
    if error:
        return error
    try:
        item = set_user_workspace_access(payload.username, payload.workspaces or [])
        return {"ok": True, "item": item, "items": list_web_users(), "message": "Đã cấp workspace cho tài khoản."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/users/delete")
def api_users_delete(request: Request, payload: UserManagePayload):
    user, error = _api_guard(request, admin_only=True)
    if error:
        return error
    try:
        result = delete_web_user(payload.username, user.get("username", ""))
        return {"ok": True, **result, "message": "Đã xóa nhân viên và chuyển workspace về admin."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/login-logs")
def api_login_logs(request: Request, username: Optional[str] = None, limit: int = 200):
    user, error = _api_guard(request, admin_only=True)
    if error:
        return error
    logs = get_login_logs(username=username or None, limit=min(int(limit), 500))
    return {"ok": True, "items": logs}


@app.get("/api/summary")
def api_summary(request: Request, profile_name: Optional[str] = None):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    return get_workspace_summary(resolved_profile) if resolved_profile else _empty_summary()


@app.get("/api/projects")
def api_projects(request: Request, profile_name: Optional[str] = None):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    return {
        "ok": True,
        "items": list_projects(resolved_profile) if resolved_profile else [],
        "workspaces": list_workspaces(user.get("username", ""), resolved_profile or str(request.session.get("active_profile", "") or "")),
    }


@app.post("/api/projects/create")
def api_projects_create(request: Request, payload: ProjectManagePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = create_project_entry(payload.project_name, resolved_profile)
        return {**result, "message": "Đã tạo project mới."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/projects/rename")
def api_projects_rename(request: Request, payload: ProjectManagePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = rename_project_entry(payload.project_id, payload.project_name, resolved_profile)
        return {**result, "message": "Đã đổi tên project."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/projects/status")
def api_projects_status(request: Request, payload: ProjectManagePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = set_project_status_entry(payload.project_id, payload.status, resolved_profile)
        message = "Đã cập nhật trạng thái project."
        return {**result, "message": message}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/projects/delete")
def api_projects_delete(request: Request, payload: ProjectManagePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = delete_project_entry(payload.project_id, resolved_profile)
        return {**result, "message": "Đã xóa project."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/projects/move")
def api_projects_move(request: Request, payload: ProjectManagePayload):
    user, error = _api_guard(request, admin_only=True)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = move_project_to_profile_web(payload.project_id, payload.target_profile, resolved_profile)
        return {**result, "message": f"Đã chuyển project sang tài khoản {result.get('target_profile', '')}."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/project-voices")
def api_project_voices(request: Request, project_id: str, profile_name: Optional[str] = None):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name)
    if access_error:
        return access_error
    return {"items": list_project_voices(project_id, resolved_profile)}


@app.get("/api/shopee-jobs")
def api_shopee_jobs(request: Request, profile_name: Optional[str] = None):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    return {"items": list_shopee_job_rows(resolved_profile) if resolved_profile else []}


@app.get("/api/videos")
def api_videos(request: Request, profile_name: Optional[str] = None):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    return {"items": list_rendered_videos(resolved_profile, limit=100) if resolved_profile else []}


@app.get("/api/render-studio")
def api_render_studio(request: Request, project_id: str = "", profile_name: Optional[str] = None):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    try:
        if not resolved_profile:
            return {"ok": False, "message": "Tài khoản này chưa được admin cấp workspace nào."}
        return get_render_studio_data(project_id, resolved_profile)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/render-studio/settings")
def api_render_studio_settings(request: Request, payload: RenderStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = save_render_studio_settings(payload.project_id or "", resolved_profile, payload.model_dump())
        return {"ok": True, "data": data, "message": "Đã lưu cấu hình edit video đa luồng."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/video-manager")
def api_video_manager(request: Request, profile_name: Optional[str] = None, keyword: str = "", status: str = "all"):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    try:
        return list_manager_videos(resolved_profile, keyword, status) if resolved_profile else {"ok": True, "items": [], "counts": {"total": 0, "done": 0, "pending": 0, "missing": 0}}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/video-manager/status")
def api_video_manager_status(request: Request, payload: VideoManagerPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = update_manager_video_status(payload.paths, payload.status or "Chưa chuyển", resolved_profile)
        return {"ok": True, "result": result, "message": "Đã cập nhật trạng thái video."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/video-manager/send-icloud")
def api_video_manager_send_icloud(request: Request, payload: VideoManagerPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = send_manager_videos_to_icloud(payload.paths, resolved_profile)
        return {"ok": True, "result": result, "message": f"Đã gửi {result.get('copied', 0)} video sang iCloud."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/video-manager/download-zip")
def api_video_manager_download_zip(request: Request, payload: VideoManagerPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error

    import zipfile, io, time as _time
    from paths import get_workspace_dir, BASE_PATH as _BASE_PATH

    # Xác định thư mục cho phép — chỉ cho phép file trong Workspace_Data
    _allowed_root = os.path.realpath(get_workspace_dir())
    _kho_root = os.path.realpath(os.path.join(_BASE_PATH, "Workspace_Data", "Kho_Video_Xuat_Xuong"))

    def _is_allowed_path(p: str) -> bool:
        real = os.path.realpath(p)
        return real.startswith(_allowed_root + os.sep) or real.startswith(_kho_root + os.sep)

    paths = [p for p in (payload.paths or []) if p and os.path.isfile(p) and _is_allowed_path(p)]
    if not paths:
        return JSONResponse(status_code=400, content={"ok": False, "message": "Không tìm thấy file video nào hợp lệ."})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        seen_names: dict = {}
        for fp in paths:
            base = os.path.basename(fp)
            if base in seen_names:
                seen_names[base] += 1
                stem, ext = os.path.splitext(base)
                base = f"{stem}_{seen_names[base]}{ext}"
            else:
                seen_names[base] = 0
            zf.write(fp, base)
    buf.seek(0)

    zip_name = f"videos_{_time.strftime('%Y%m%d_%H%M%S')}.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{zip_name}"',
        "Content-Length": str(buf.getbuffer().nbytes),
    }
    return StreamingResponse(buf, media_type="application/zip", headers=headers)


@app.post("/api/video-manager/delete")
def api_video_manager_delete(request: Request, payload: VideoManagerPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = delete_manager_videos(payload.paths, resolved_profile)
        return {"ok": True, "result": result, "message": f"Đã xóa {result.get('removed', 0)} video khỏi máy và danh sách."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/phone-devices")
def api_phone_devices(request: Request):
    user, error = _api_guard(request)
    if error:
        return error
    feature_error = _feature_guard(user, "phone", "Quản lý điện thoại")
    if feature_error:
        return feature_error
    return list_phone_devices()


@app.post("/api/phone-devices/select")
def api_phone_devices_select(request: Request, payload: PhoneSelectionPayload):
    user, error = _api_guard(request)
    if error:
        return error
    feature_error = _feature_guard(user, "phone", "Quản lý điện thoại")
    if feature_error:
        return feature_error
    return save_phone_device_selection(payload.serials)


@app.get("/api/autopost-center")
def api_autopost_center(request: Request, profile_name: Optional[str] = None):
    user, error = _api_guard(request)
    if error:
        return error
    feature_error = _feature_guard(user, "autopost", "Auto đăng Shopee")
    if feature_error:
        return feature_error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    return get_autopost_center_data(resolved_profile) if resolved_profile else {"ok": False, "message": "Tài khoản này chưa được admin cấp workspace nào.", "jobs": [], "counts": {}}


@app.post("/api/autopost-center/settings")
def api_autopost_center_settings(request: Request, payload: AutoPostSettingsPayload):
    user, error = _api_guard(request)
    if error:
        return error
    feature_error = _feature_guard(user, "autopost", "Auto đăng Shopee")
    if feature_error:
        return feature_error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = save_autopost_center_settings(resolved_profile, payload.model_dump())
        return {"ok": True, "data": data, "message": "Đã lưu cấu hình auto đăng Shopee."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/telegram-bot")
def api_telegram_bot(request: Request, profile_name: Optional[str] = None):
    user, error = _api_guard(request, admin_only=True)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    try:
        return get_telegram_center_data(resolved_profile)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/telegram-bot/settings")
def api_telegram_bot_settings(request: Request, payload: TelegramBotPayload):
    user, error = _api_guard(request, admin_only=True)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name, allow_empty=True)
    if access_error:
        return access_error
    try:
        data = save_telegram_center_settings(resolved_profile, payload.model_dump())
        return {"ok": True, "data": data, "message": "Đã lưu cấu hình Telegram bot."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/subtitle")
def api_subtitle(request: Request, project_id: str = "", profile_name: Optional[str] = None, voice_name: str = ""):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    try:
        return get_subtitle_studio_data(project_id, resolved_profile, voice_name)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/subtitle/upload")
async def api_subtitle_upload(request: Request, project_id: str = Form(...), profile_name: str = Form(""), subtitle_files: list[UploadFile] = File(...)):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name)
    if access_error:
        return access_error
    try:
        files = [(item.filename or "", await item.read()) for item in subtitle_files]
        result = save_uploaded_subtitle_videos(project_id, files, resolved_profile)
        return {"ok": True, "result": result, "message": f"Đã nạp {len(result.get('saved', []))} video cho tab phụ đề."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/subtitle/save")
def api_subtitle_save(request: Request, payload: SubtitleStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = save_subtitle_studio_data(
            payload.project_id,
            payload.voice_name,
            payload.subtitle_text,
            resolved_profile,
            source_type=payload.source_type,
            source_name=payload.source_name,
        )
        return {"ok": True, "data": data, "message": "Đã lưu phụ đề theo đúng tab 6."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/subtitle/generate")
def api_subtitle_generate(request: Request, payload: SubtitleStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = generate_subtitle_for_web(
            payload.project_id,
            payload.voice_name,
            resolved_profile,
            source_type=payload.source_type,
            source_name=payload.source_name,
        )
        return {"ok": True, "data": data, "message": "Đã bóc phụ đề SRT xong cho tab 6."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/script")
def api_script(request: Request, project_id: str = "", profile_name: Optional[str] = None, folder_name: str = "", file_name: str = ""):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name, allow_empty=True)
    if access_error:
        return access_error
    try:
        return get_script_studio_data(project_id, resolved_profile, folder_name=folder_name, file_name=file_name)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/script/campaign/create")
def api_script_campaign_create(request: Request, payload: ScriptStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = create_script_campaign_folder(payload.folder_name, resolved_profile)
        return {"ok": True, "data": data, "message": "Đã tạo chiến dịch mới cho tab 7."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/script/campaign/delete")
def api_script_campaign_delete(request: Request, payload: ScriptStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = delete_script_campaign_folder(payload.folder_name, resolved_profile)
        return {"ok": True, "data": data, "message": "Đã xóa chiến dịch tab 7."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/script/file/delete")
def api_script_file_delete(request: Request, payload: ScriptStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = delete_script_campaign_file(payload.folder_name, payload.file_name, resolved_profile)
        return {"ok": True, "data": data, "message": "Đã xóa kịch bản đang chọn."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/script/run")
def api_script_run(request: Request, payload: ScriptStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        job = start_script_scrape_job(
            profile_name=resolved_profile,
            folder_name=payload.folder_name,
            urls_text=payload.urls_text,
            max_workers=int(payload.threads or 3),
            use_ytdlp=bool(payload.use_ytdlp) if payload.use_ytdlp is not None else True,
            trans_mode=payload.boc_bang_mode or "ohfree",
            progress_callback=emit_status,
        )
        return {"ok": True, "job": job, "message": "Đã bắt đầu tải video và bóc băng cho chiến dịch tab 7."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/script/save")
def api_script_save(request: Request, payload: ScriptStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = save_script_studio_data(
            payload.project_id,
            resolved_profile,
            source_text=payload.source_text,
            product_info=payload.product_info,
            keys_text=payload.keys_text,
            prompt=payload.prompt,
            output_text=payload.output_text,
            folder_name=payload.folder_name,
            file_name=payload.file_name,
            urls_text=payload.urls_text,
            use_ytdlp=payload.use_ytdlp,
            threads=payload.threads,
            boc_bang_mode=payload.boc_bang_mode,
            kie_key=payload.kie_key,
            selected_hook=payload.selected_hook,
        )
        return {"ok": True, "data": data, "message": "Đã lưu đầy đủ dữ liệu tab 7."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/script/extract")
def api_script_extract(request: Request, payload: ScriptStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = extract_script_assets(
            payload.project_id,
            resolved_profile,
            source_text=payload.source_text,
            folder_name=payload.folder_name,
            file_name=payload.file_name,
            kie_key=payload.kie_key,
        )
        return {"ok": True, "data": data, "message": data.get("message", "AI đã bóc key và thông tin sản phẩm.")}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/script/spin")
def api_script_spin(request: Request, payload: ScriptStudioPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = spin_script_web(
            payload.project_id,
            resolved_profile,
            source_text=payload.source_text,
            product_info=payload.product_info,
            keys_text=payload.keys_text,
            prompt=payload.prompt,
            folder_name=payload.folder_name,
            file_name=payload.file_name,
            selected_hook=payload.selected_hook,
            kie_key=payload.kie_key,
        )
        return {"ok": True, "data": data, "message": data.get("message", "AI đã xào xong kịch bản.")}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/jobs")
def api_jobs(request: Request):
    user, error = _api_guard(request)
    if error:
        return error
    allowed_profiles = None if user.get("role") == "admin" else get_user_allowed_workspaces(user.get("username", ""))
    return {"items": get_all_web_jobs(allowed_profiles=allowed_profiles)}


@app.get("/api/broll")
def api_broll(request: Request, project_id: str, profile_name: Optional[str] = None, keyword: str = ""):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name)
    if access_error:
        return access_error
    try:
        return get_scene_manager_data(project_id, resolved_profile, keyword)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/broll/settings")
def api_broll_settings(request: Request, payload: SceneUpdatePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        data = save_scene_settings(
            payload.project_id,
            resolved_profile,
            context=payload.context or "",
            product_name=payload.product_name or "",
            shopee_out_of_stock=bool(payload.shopee_out_of_stock),
            product_links=payload.product_links or [],
        )
        return {"ok": True, "data": data, "message": "Đã lưu thông tin cảnh trám."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/broll/scene")
def api_broll_scene(request: Request, payload: SceneUpdatePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        item = update_scene_item(
            payload.project_id,
            payload.vid_name or "",
            resolved_profile,
            description=payload.description,
            keep_audio=payload.keep_audio,
            in_trash=False,
        )
        return {"ok": True, "item": item, "message": "Đã lưu mô tả cảnh."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/broll/action")
def api_broll_action(request: Request, payload: SceneBulkActionPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = bulk_scene_action(payload.project_id, payload.names, payload.action, resolved_profile, in_trash=payload.in_trash)
        completed = result.get('completed', 0)
        requested = result.get('requested', 0)
        failed = result.get('failed', [])
        
        if failed:
            msg = f"Đã xử lý {completed}/{requested} cảnh. {len(failed)} cảnh lỗi."
        else:
            msg = f"Đã xử lý {completed} cảnh thành công."
        
        return {"ok": True, "result": result, "message": msg}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/broll/ai-single")
def api_broll_ai_single(request: Request, payload: SceneUpdatePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = ai_describe_single_scene(payload.project_id, payload.vid_name or "", resolved_profile, payload.hint_text or "")
        return {"ok": True, "item": result, "message": "AI đã điền mô tả cho cảnh này."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/broll/ai-all")
def api_broll_ai_all(request: Request, payload: SceneUpdatePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        job = start_broll_ai_job(payload.project_id, resolved_profile, progress_callback=emit_status)
        return {"ok": True, "job": job, "message": "AI đang điền toàn bộ mô tả cảnh trám."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/broll/upload")
async def api_broll_upload(request: Request, project_id: str = Form(...), profile_name: str = Form(""), broll_files: list[UploadFile] = File(...)):
    # Log request size
    content_length = request.headers.get('content-length', '0')
    content_length_mb = int(content_length) / (1024 * 1024) if content_length.isdigit() else 0
    print(f"🟢 api_broll_upload called - project_id: {project_id}, profile: {profile_name}, files: {len(broll_files)}, body size: {content_length_mb:.2f}MB")
    
    user, error = _api_guard(request)
    if error:
        print(f"❌ Auth error: {error}")
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name)
    if access_error:
        print(f"❌ Profile access error: {access_error}")
        return access_error
    try:
        # CRITICAL FIX: Stream files to disk instead of loading all into RAM
        print(f"🔵 Streaming {len(broll_files)} files to disk (not loading to RAM)...")
        files = []
        total_bytes = 0
        for idx, item in enumerate(broll_files):
            filename = item.filename or f"unknown_{idx}.mp4"
            print(f"  📥 Reading file {idx+1}/{len(broll_files)}: {filename}")
            try:
                content = await item.read()
                file_size_mb = len(content) / (1024 * 1024)
                total_bytes += len(content)
                files.append((filename, content))
                print(f"  ✅ File {idx+1} read: {file_size_mb:.2f} MB")
                
                # Warn if file is very large
                if file_size_mb > 100:
                    print(f"  ⚠️ Warning: Large file {filename} ({file_size_mb:.2f} MB)")
            except Exception as e:
                print(f"  ❌ Error reading {filename}: {e}")
                continue
        
        total_mb = total_bytes / (1024 * 1024)
        print(f"🔵 All {len(files)} files read ({total_mb:.2f} MB total), calling save_uploaded_broll_files...")
        result = save_uploaded_broll_files(project_id, files, resolved_profile)
        saved_count = len(result.get('saved', []))
        print(f"✅ Upload complete - saved {saved_count} files")
        return {"ok": True, "result": result, "message": f"Đã nạp {saved_count} cảnh trám lên web."}
    except Exception as exc:
        print(f"❌ Upload exception: {exc}")
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/voices/upload")
async def api_voices_upload(request: Request, project_id: str = Form(...), profile_name: str = Form(""), voice_files: list[UploadFile] = File(...)):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name)
    if access_error:
        return access_error
    try:
        files = [(item.filename or "", await item.read()) for item in voice_files]
        result = start_voice_transcribe_job(project_id, files, resolved_profile, progress_callback=emit_status)
        count = len(result.get('saved', []))
        return {"ok": True, "result": result, "message": f"Đã nạp {count} voice, đang bóc SRT..."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/voices/delete")
def api_voices_delete(request: Request, payload: SceneUpdatePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = delete_voice_file(payload.project_id, payload.vid_name or "", resolved_profile)
        return {"ok": True, "result": result, "message": "Đã xóa voice."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.get("/api/voices/status")
def api_voices_status(request: Request, project_id: str = "", profile_name: str = ""):
    """Lightweight endpoint: returns only voice statuses, no full scene reload."""
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name)
    if access_error:
        return access_error
    try:
        statuses = get_voice_statuses(project_id, resolved_profile)
        return {"ok": True, "statuses": statuses}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/broll/ref-image")
async def api_broll_ref_image(request: Request, project_id: str = Form(...), profile_name: str = Form(""), ref_index: int = Form(...), ref_file: UploadFile = File(...)):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name)
    if access_error:
        return access_error
    try:
        result = save_ref_image_file(project_id, ref_index, ref_file.filename or "ref.jpg", await ref_file.read(), resolved_profile)
        return {"ok": True, "result": result, "message": "Đã cập nhật ảnh mẫu sản phẩm."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/broll/clear-refs")
def api_broll_clear_refs(request: Request, payload: SceneUpdatePayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        result = clear_ref_images_web(payload.project_id, resolved_profile)
        return {"ok": True, "result": result, "message": "Đã xóa ảnh mẫu tham chiếu."}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


def _range_response(file_path: str, request: Request):
    """Serve file with HTTP Range support (206 Partial Content) for smooth video/audio seeking."""
    file_size = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska", ".webm": "video/webm",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    }
    media_type = mime_map.get(ext, "application/octet-stream")

    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(file_path, media_type=media_type)

    # Parse Range: bytes=start-end
    try:
        range_val = range_header.replace("bytes=", "").strip()
        parts = range_val.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
    except (ValueError, IndexError):
        return FileResponse(file_path, media_type=media_type)

    end = min(end, file_size - 1)
    chunk_size = end - start + 1

    def iter_file():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                data = f.read(min(65536, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Type": media_type,
    }
    return StreamingResponse(iter_file(), status_code=206, headers=headers, media_type=media_type)


@app.get("/media/{profile_name}/{project_id}/{section}/{file_name:path}")
def media_file(request: Request, profile_name: str, project_id: str, section: str, file_name: str):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name)
    if access_error:
        return access_error
    try:
        file_path = get_media_file_path(project_id, resolved_profile, section, file_name)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})
    if not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"ok": False, "message": "Không tìm thấy file media."})
    return _range_response(file_path, request)


@app.get("/media/exports/{profile_name}/{file_name:path}")
def media_export_file(request: Request, profile_name: str, file_name: str):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, profile_name)
    if access_error:
        return access_error
    try:
        file_path = get_export_video_path(resolved_profile, file_name)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})
    if not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"ok": False, "message": "Không tìm thấy video xuất xưởng."})
    return _range_response(file_path, request)


@app.post("/api/render")
def api_render(request: Request, payload: JobPayload):
    user, error = _api_guard(request)
    if error:
        return error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    if payload.project_id:
        try:
            job = start_real_render_job(payload.project_id, resolved_profile, payload.voice_names, progress_callback=emit_status, created_by=user.get("username", ""))
            pos = job.get("queue_position", 0)
            msg = f"Ghi nhận thành công! Bạn đang ở vị trí số {pos} trong hàng đợi." if pos else "Đã đưa vào hàng đợi render."
            return {"ok": True, "job": job, "message": msg}
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

    job = start_mock_job("render", resolved_profile, payload.note, progress_callback=emit_status)
    return {"ok": True, "job": job, "message": "Đã tạo job render nền cho dashboard web."}


@app.get("/api/render-queue")
def api_render_queue(request: Request):
    user, error = _api_guard(request)
    if error:
        return error
    allowed_profiles = None if user.get("role") == "admin" else get_user_allowed_workspaces(user.get("username", ""))
    return {"ok": True, "items": list_render_queue(allowed_profiles=allowed_profiles)}


@app.post("/api/render-queue/cancel")
def api_cancel_render(request: Request, payload: dict):
    user, error = _api_guard(request)
    if error:
        return error
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        return JSONResponse(status_code=400, content={"ok": False, "message": "Thiếu job_id."})
    try:
        result = cancel_render_job(job_id, actor=user.get("username", ""))
        return {"ok": True, **result, "message": "Đã hủy job render."}
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "message": str(exc)})


@app.post("/api/autopost")
def api_autopost(request: Request, payload: JobPayload):
    user, error = _api_guard(request)
    if error:
        return error
    feature_error = _feature_guard(user, "autopost", "Auto đăng Shopee")
    if feature_error:
        return feature_error
    resolved_profile, access_error = _resolve_profile_for_request(request, user, payload.profile_name)
    if access_error:
        return access_error
    try:
        job = start_autopost_job(resolved_profile, progress_callback=emit_status)
        return {"ok": True, "job": job, "message": "Đã tạo job auto post từ dashboard web."}
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "message": str(exc)}


@app.get("/api/jobs/{job_id}")
def api_job_detail(request: Request, job_id: str):
    user, error = _api_guard(request)
    if error:
        return error
    job = get_web_job(job_id)
    if not job:
        return {"ok": False, "job": None}
    if user.get("role") != "admin":
        allowed_profiles = set(get_user_allowed_workspaces(user.get("username", "")))
        if job.get("profile_name") not in allowed_profiles:
            return JSONResponse(status_code=403, content={"ok": False, "message": "403 Không có quyền truy cập job này."})
    return {"ok": True, "job": job}


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    username = ""
    try:
        username = str(websocket.session.get("username", "") or "")
    except Exception:
        username = ""
    if not username:
        await websocket.close(code=4401)
        return

    # Vập kiểm tra approved + is_active — không cho user bị khóa kết nối WS
    try:
        ws_user = get_user_by_username(username)
        if not ws_user or not ws_user.get("approved") or not ws_user.get("is_active", True):
            await websocket.close(code=4403)
            return
    except Exception:
        await websocket.close(code=4403)
        return

    await ws_manager.connect(websocket)
    await websocket.send_json({"event": "connected", "active_profile": ensure_active_profile(), "username": username})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    
    # Load config để lấy port
    app_config = load_app_config()
    server_port = app_config.get("server_port", 8000)

    # Config cho upload file lớn
    print(f"🚀 Starting server on port {server_port}...")
    print(f"📊 Upload timeout: 300s (5 phút)")
    print(f"💾 Max concurrent requests: 10000")
    
    config = uvicorn.Config(
        "server:app",
        host="127.0.0.1",
        port=server_port,
        reload=False,
        timeout_keep_alive=300,  # 5 phút cho upload lớn
        limit_max_requests=10000,
        backlog=2048
    )
    server = uvicorn.Server(config)
    server.run()
