import json
import os
import re
import shutil
import sys


def resource_path(relative_path):
    """ Lấy đường dẫn tuyệt đối cho tài nguyên bên trong file EXE """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_executable_path():
    """ Lấy đường dẫn thư mục chứa file EXE bên ngoài """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


BASE_PATH = get_executable_path()
DEFAULT_PROFILE = "Tai_Khoan_Chinh"
PROFILE_MARKER_FILE = ".workspace_profile.json"
ACTIVE_PROFILE = DEFAULT_PROFILE


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def sanitize_profile_name(profile_name):
    text = str(profile_name or DEFAULT_PROFILE).strip()
    if not text:
        return DEFAULT_PROFILE

    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text[:60] or DEFAULT_PROFILE


def get_workspace_dir():
    """Lấy thư mục gốc chứa tất cả dữ liệu"""
    return _ensure_dir(os.path.join(BASE_PATH, "Workspace_Data"))


def ensure_profile_structure(profile_name=None):
    profile_name = sanitize_profile_name(profile_name or ACTIVE_PROFILE)
    profile_dir = _ensure_dir(os.path.join(get_workspace_dir(), profile_name))

    for folder_name in ("Projects", "B_Roll_Data", "B_Roll_Trash", "Voice_Data", "Kho_Video_Xuat_Xuong", os.path.join("Kho_Video_Xuat_Xuong", "DA_DANG")):
        _ensure_dir(os.path.join(profile_dir, folder_name))

    marker_path = os.path.join(profile_dir, PROFILE_MARKER_FILE)
    if not os.path.exists(marker_path):
        try:
            with open(marker_path, "w", encoding="utf-8") as handle:
                json.dump({"profile_name": profile_name}, handle, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return profile_dir


def set_active_profile(profile_name):
    """Đổi tài khoản đang làm việc"""
    global ACTIVE_PROFILE
    ACTIVE_PROFILE = sanitize_profile_name(profile_name)
    ensure_profile_structure(ACTIVE_PROFILE)
    return ACTIVE_PROFILE


def get_active_profile():
    """Lấy tên tài khoản đang làm việc hiện tại"""
    return ACTIVE_PROFILE


def get_profile_dir(profile_name=None):
    """Lấy thư mục làm việc riêng của Tài khoản hiện tại"""
    return ensure_profile_structure(profile_name)


def get_projects_root(profile_name=None):
    return _ensure_dir(os.path.join(get_profile_dir(profile_name), "Projects"))


def get_profile_project_dir(project_id, profile_name=None):
    return _ensure_dir(os.path.join(get_projects_root(profile_name), str(project_id)))


def get_projects_list_file(profile_name=None):
    return os.path.join(get_profile_dir(profile_name), "projects_list.json")


def get_projects_backup_file(profile_name=None):
    return os.path.join(get_profile_dir(profile_name), "projects_list_backup.json")


def get_excel_log_file(profile_name=None):
    return os.path.join(get_profile_dir(profile_name), "Danh_Sach_Video.csv")


def get_shopee_csv_file(profile_name=None):
    return os.path.join(get_profile_dir(profile_name), "Danh_sach_video_Shopee.csv")


def get_broll_dir(profile_name=None):
    """Thư mục chứa video Cảnh trám của TK hiện tại"""
    return _ensure_dir(os.path.join(get_profile_dir(profile_name), "B_Roll_Data"))


def get_broll_trash_dir(profile_name=None):
    """Thư mục Thùng rác Cảnh trám của TK hiện tại"""
    return _ensure_dir(os.path.join(get_profile_dir(profile_name), "B_Roll_Trash"))


def get_export_dir(profile_name=None):
    """Kho chứa video Đã Render xong của TK hiện tại"""
    return _ensure_dir(os.path.join(get_profile_dir(profile_name), "Kho_Video_Xuat_Xuong"))


def get_posted_video_dir(profile_name=None):
    return _ensure_dir(os.path.join(get_export_dir(profile_name), "DA_DANG"))


def get_voice_dir(profile_name=None):
    """Thư mục chứa Audio/Voice của TK hiện tại"""
    return _ensure_dir(os.path.join(get_profile_dir(profile_name), "Voice_Data"))


def _profile_has_user_data(profile_name):
    profile_dir = os.path.join(get_workspace_dir(), sanitize_profile_name(profile_name))

    projects_file = os.path.join(profile_dir, "projects_list.json")
    if os.path.exists(projects_file):
        try:
            with open(projects_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict) and data:
                    return True
        except Exception:
            if os.path.getsize(projects_file) > 10:
                return True

    for folder_name in ("Projects", "B_Roll_Data", "B_Roll_Trash", "Voice_Data", "Kho_Video_Xuat_Xuong"):
        folder_path = os.path.join(profile_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue

        for item_name in os.listdir(folder_path):
            if folder_name == "Kho_Video_Xuat_Xuong" and item_name == "DA_DANG":
                posted_dir = os.path.join(folder_path, item_name)
                if os.path.isdir(posted_dir) and os.listdir(posted_dir):
                    return True
                continue
            return True

    return False


def get_all_profiles():
    """Quét ổ cứng và lấy danh sách tất cả các tài khoản hiện có"""
    ws_dir = get_workspace_dir()
    profiles = []

    for entry in os.listdir(ws_dir):
        entry_path = os.path.join(ws_dir, entry)
        if not os.path.isdir(entry_path):
            continue

        marker_path = os.path.join(entry_path, PROFILE_MARKER_FILE)
        projects_file = os.path.join(entry_path, "projects_list.json")
        is_placeholder = re.fullmatch(r"Tai_Khoan_[A-Z]", entry or "") is not None
        if is_placeholder and entry != ACTIVE_PROFILE and not _profile_has_user_data(entry):
            continue

        if os.path.exists(marker_path) or os.path.exists(projects_file) or entry == ACTIVE_PROFILE:
            profiles.append(entry)

    if not profiles:
        ensure_profile_structure(DEFAULT_PROFILE)
        return [DEFAULT_PROFILE]

    return sorted(set(profiles), key=str.lower)


def migrate_legacy_workspace(default_profile=None):
    """Di chuyển dữ liệu kiểu cũ ở gốc Workspace_Data vào 1 profile mặc định."""
    profile_name = sanitize_profile_name(default_profile or DEFAULT_PROFILE)
    ws_dir = get_workspace_dir()
    profile_dir = ensure_profile_structure(profile_name)
    projects_root = get_projects_root(profile_name)

    legacy_to_target = [
        (os.path.join(ws_dir, "projects_list.json"), get_projects_list_file(profile_name)),
        (os.path.join(ws_dir, "projects_list_backup.json"), get_projects_backup_file(profile_name)),
        (os.path.join(ws_dir, "Danh_Sach_Video.csv"), get_excel_log_file(profile_name)),
        (os.path.join(ws_dir, "Danh_sach_video_Shopee.csv"), get_shopee_csv_file(profile_name)),
    ]

    for legacy_path, target_path in legacy_to_target:
        if os.path.exists(legacy_path) and not os.path.exists(target_path):
            try:
                shutil.move(legacy_path, target_path)
            except Exception:
                pass

    legacy_output_dir = os.path.join(ws_dir, "Kho_Video_Xuat_Xuong")
    target_output_dir = get_export_dir(profile_name)
    if os.path.isdir(legacy_output_dir) and os.path.normcase(os.path.abspath(legacy_output_dir)) != os.path.normcase(os.path.abspath(target_output_dir)):
        for item_name in os.listdir(legacy_output_dir):
            src_item = os.path.join(legacy_output_dir, item_name)
            dst_item = os.path.join(target_output_dir, item_name)
            if os.path.exists(dst_item):
                continue
            try:
                shutil.move(src_item, dst_item)
            except Exception:
                pass
        try:
            os.rmdir(legacy_output_dir)
        except OSError:
            pass

    project_ids = set()
    projects_file = get_projects_list_file(profile_name)
    if os.path.exists(projects_file):
        try:
            with open(projects_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    project_ids.update(str(key) for key in data.keys())
        except Exception:
            pass

    for entry in os.listdir(ws_dir):
        entry_path = os.path.join(ws_dir, entry)
        if os.path.isdir(entry_path) and re.fullmatch(r"\d{14}", entry):
            project_ids.add(entry)

    for project_id in project_ids:
        legacy_project_dir = os.path.join(ws_dir, project_id)
        target_project_dir = os.path.join(projects_root, project_id)
        if os.path.isdir(legacy_project_dir) and not os.path.exists(target_project_dir):
            try:
                shutil.move(legacy_project_dir, target_project_dir)
            except Exception:
                pass

    return profile_dir