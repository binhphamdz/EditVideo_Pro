import os
import json
import shutil
import threading
import time
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import telebot # THƯ VIỆN TELEGRAM BOT
import sys
sys.modules.setdefault("main", sys.modules[__name__])
from paths import (
    DEFAULT_PROFILE,
    get_active_profile,
    get_all_profiles,
    get_excel_log_file,
    get_export_dir,
    get_profile_dir,
    get_profile_project_dir,
    get_projects_list_file,
    get_projects_root,
    get_workspace_dir,
    migrate_legacy_workspace,
    sanitize_profile_name,
    set_active_profile,
)

# =================================================================
# [MỚI] BỘ CÔNG CỤ LA BÀN TÌM ĐƯỜNG DẪN DÀNH CHO BẢN BUILD ONEFILE
# =================================================================
def resource_path(relative_path):
    """ Lấy đường dẫn tới các file ĐÍNH KÈM (như logo.png, whoosh.MP3) nằm BÊN TRONG file .exe """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_executable_path():
    """ Lấy đường dẫn thư mục chứa phần mềm (BÊN NGOÀI file .exe) để lưu Data, Config """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.getcwd()

# Dùng biến này làm mỏ neo thay cho os.getcwd()
BASE_PATH = get_executable_path()
# =================================================================

# =================================================================
# BÙA CHỐNG SPAM LỖI WINERROR 6 CỦA MOVIEPY KHI TẮT APP
# =================================================================
import moviepy.video.io.ffmpeg_reader as ffmpeg_reader
old_del = ffmpeg_reader.FFMPEG_VideoReader.__del__
def safe_del(self):
    try:
        old_del(self)
    except Exception:
        pass
ffmpeg_reader.FFMPEG_VideoReader.__del__ = safe_del
# =================================================================

# from tab0_capcut import CapCutTab
from tab1_broll import BRollTab
from tab2_modules import FacelessTab
from tab4_manager import ManagerTab
from tab5_phone import PhoneManagerTab
from tab11_auto_post import AutoPostTab
# from tab5_tiktok import TikTokTab  # [ĐÃ XÓA]
from tab6_subtitle import SubtitleTab  
from tab7_script import ScriptTab  
from tab8_telegram import TelegramTab # <--- IMPORT TAB 8 MỚI
from bot_telegram import TelegramBotManager
from tab9_script_analysis import ScriptAnalysisTab
from tab10_config import ConfigTab

# [ĐÃ SỬA] DÙNG BASE_PATH ĐỂ TẠO THƯ MỤC CẠNH FILE EXE CHỨ KHÔNG PHẢI TRONG TEMP
WORKSPACE_DIR = ""
PROJECTS_LIST_FILE = ""
GLOBAL_OUT_DIR = ""
EXCEL_LOG_FILE = ""
GUEST_PROFILE = "Vãng_Lai"


def _ensure_excel_log_file():
    if not os.path.exists(EXCEL_LOG_FILE):
        with open(EXCEL_LOG_FILE, 'w', encoding='utf-8-sig') as f:
            f.write("Ngày Tạo,Tên Project,Tên Voice,Đường Dẫn Video,Trạng Thái\n")


def refresh_runtime_paths(profile_name=None):
    global WORKSPACE_DIR, PROJECTS_LIST_FILE, GLOBAL_OUT_DIR, EXCEL_LOG_FILE

    if profile_name:
        set_active_profile(profile_name)

    WORKSPACE_DIR = get_profile_dir()
    PROJECTS_LIST_FILE = get_projects_list_file()
    GLOBAL_OUT_DIR = get_export_dir()
    EXCEL_LOG_FILE = get_excel_log_file()

    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    os.makedirs(GLOBAL_OUT_DIR, exist_ok=True)
    _ensure_excel_log_file()


def get_startup_profile():
    conf_file = os.path.join(BASE_PATH, "config_dao_dien.json")
    try:
        with open(conf_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        saved_profile = str((data or {}).get("active_profile", "")).strip()
        if saved_profile:
            return saved_profile
    except Exception:
        pass

    profiles = [p for p in get_all_profiles() if p != GUEST_PROFILE]
    if profiles:
        return profiles[0]
    return DEFAULT_PROFILE


refresh_runtime_paths(get_startup_profile())

class MainApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🎬 TOOL EDIT VIDEO PRO BY PHẠM VĂN BÌNH - 0345.26.22.29")
        self.root.geometry("2200x1200")
        self.root.configure(bg="#f4f6f9")
        
        # =======================================================
        # [GẮN Ổ KHÓA TỔNG] - LINH HỒN CỦA HỆ THỐNG ĐA LUỒNG
        # =======================================================
        self.json_lock = threading.Lock()
        
        # =======================================================
        # GẮN ICON SỬ DỤNG HÀM LA BÀN
        # =======================================================
        try:
            icon_path = resource_path("icon.png")
            icon_image = tk.PhotoImage(file=icon_path)
            self.root.iconphoto(True, icon_image)
        except Exception as e:
            print("Chưa tìm thấy file logo.png: ", e)
        # =======================================================
        
        self.config = self.load_config()
        self.active_profile = set_active_profile(self.config.get("active_profile", DEFAULT_PROFILE))
        migrate_legacy_workspace(self.active_profile)
        refresh_runtime_paths(self.active_profile)
        self.config["active_profile"] = self.active_profile
        self.projects = self.load_projects()
        
        # Các biến quản lý Bot Telegram
        self.bot = None
        self.bot_is_running = False
        
        self.setup_ui()
        
        
    def get_active_profile_name(self):
        return getattr(self, "active_profile", get_active_profile())

    def _refresh_profile_selector(self):
        if hasattr(self, "cmb_profile") and self.cmb_profile.winfo_exists():
            profiles = get_all_profiles()
            self.cmb_profile["values"] = profiles
            self.profile_var.set(self.get_active_profile_name())

        if hasattr(self, "lbl_profile_hint") and self.lbl_profile_hint.winfo_exists():
            self.lbl_profile_hint.config(text=f"Đang làm việc trong tài khoản: {self.get_active_profile_name()}")

    def switch_profile(self, profile_name, show_notice=False):
        next_profile = set_active_profile(profile_name)
        if next_profile == self.get_active_profile_name() and hasattr(self, "tab1"):
            self._refresh_profile_selector()
            return

        if hasattr(self, "tab1"):
            try:
                self.tab1.save_all_descriptions()
                self.tab1.save_project_context()
                self.tab1.save_product_info()
            except Exception:
                pass

        self.active_profile = next_profile
        refresh_runtime_paths(self.active_profile)
        self.config["active_profile"] = self.active_profile
        self.save_config()
        self.projects = self.load_projects()
        if hasattr(self, "telegram_manager") and self.telegram_manager:
            try:
                self.telegram_manager.clear_sessions()
            except Exception:
                pass
        self._refresh_profile_selector()

        if hasattr(self, "tab1"):
            try:
                self.tab1.current_project_id = None
                self.tab1.refresh_project_list()
                self.tab1.render_video_list(reset_pages=True)
                self.tab1.lbl_proj_name.config(text="Chưa chọn Project nào")
                for item in self.tab1.tree_voices.get_children():
                    self.tab1.tree_voices.delete(item)
                self.tab1.txt_context.delete("1.0", tk.END)
                self.tab1.ent_product_name.delete(0, tk.END)
                self.tab1.var_shopee_out_of_stock.set(False)
                for entry in self.tab1.product_link_entries:
                    entry.delete(0, tk.END)
                self.tab1.lbl_ref1.config(text="Chưa chọn", fg="gray")
                self.tab1.lbl_ref2.config(text="Chưa chọn", fg="gray")
            except Exception:
                pass

        if hasattr(self, "tab2"):
            self.tab2.update_combo_projects()
        if hasattr(self, "tab4"):
            self.tab4.load_excel_data()
        if hasattr(self, "tab11"):
            self.tab11.runtime_csv_path = None
            self.tab11.on_tab_activated()

        if show_notice:
            messagebox.showinfo("Đổi tài khoản", f"Đã chuyển sang không gian làm việc: {self.active_profile}")

    def on_profile_selected(self, event=None):
        selected_profile = self.profile_var.get().strip()
        if not selected_profile:
            return
        if selected_profile == self.get_active_profile_name():
            self._refresh_profile_selector()
            return
        self.switch_profile(selected_profile)

    def create_profile_dialog(self):
        new_profile_name = simpledialog.askstring("Tạo tài khoản", "Nhập tên tài khoản / workspace mới:")
        if not new_profile_name:
            return
        self.switch_profile(new_profile_name, show_notice=True)

    def rename_profile(self, old_profile, new_profile_name):
        old_profile = str(old_profile or "").strip()
        if not old_profile:
            return False, "Không xác định được tài khoản cũ để đổi tên."
        if old_profile.casefold() == GUEST_PROFILE.casefold():
            return False, "Không đổi tên mục Vãng Lai để tránh lạc project hệ thống."

        new_profile_name = sanitize_profile_name(new_profile_name)
        if not new_profile_name:
            return False, "Tên tài khoản mới không hợp lệ."
        if new_profile_name.casefold() == old_profile.casefold():
            return False, "Tên mới đang trùng với tên cũ."

        existing_profiles = {name.casefold() for name in self.get_available_profiles()}
        if new_profile_name.casefold() in existing_profiles:
            return False, "Đã có tài khoản này rồi, bác đặt tên khác giúp em."

        if hasattr(self, "tab1"):
            try:
                self.tab1.save_all_descriptions()
                self.tab1.save_project_context()
                self.tab1.save_product_info()
            except Exception:
                pass

        old_dir = os.path.join(get_workspace_dir(), old_profile)
        new_dir = os.path.join(get_workspace_dir(), new_profile_name)
        if not os.path.exists(old_dir):
            return False, "Không thấy thư mục tài khoản cũ để đổi tên."

        try:
            shutil.move(old_dir, new_dir)
            marker_path = os.path.join(new_dir, ".workspace_profile.json")
            with open(marker_path, "w", encoding="utf-8") as handle:
                json.dump({"profile_name": new_profile_name}, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            return False, f"Không thể đổi tên tài khoản: {exc}"

        self.active_profile = set_active_profile(new_profile_name)
        refresh_runtime_paths(self.active_profile)
        self.config["active_profile"] = self.active_profile
        self.save_config()
        self.projects = self.load_projects()

        if hasattr(self, "telegram_manager") and self.telegram_manager:
            try:
                self.telegram_manager.clear_sessions()
            except Exception:
                pass

        self._refresh_profile_selector()
        if hasattr(self, "tab1"):
            self.tab1.refresh_project_list()
        if hasattr(self, "tab2"):
            self.tab2.update_combo_projects()
        if hasattr(self, "tab4"):
            self.tab4.load_excel_data()
        if hasattr(self, "tab11"):
            self.tab11.runtime_csv_path = None
            self.tab11.on_tab_activated()

        return True, f"Đã đổi tên tài khoản thành: {new_profile_name}"

    def rename_profile_dialog(self):
        old_profile = self.get_active_profile_name()
        new_profile_name = simpledialog.askstring("Đổi tên tài khoản", "Nhập tên mới cho tài khoản:", initialvalue=old_profile)
        if not new_profile_name:
            return

        ok, msg = self.rename_profile(old_profile, new_profile_name)
        if ok:
            messagebox.showinfo("Thành công", msg)
        else:
            messagebox.showwarning("Chưa đổi được", msg)

    def _make_unique_project_id(self, project_id, target_profile, target_projects):
        base_id = str(project_id)
        candidate = base_id
        counter = 1
        target_root = get_projects_root(target_profile)

        while candidate in target_projects or os.path.exists(os.path.join(target_root, candidate)):
            candidate = f"{base_id}_{counter}"
            counter += 1
        return candidate

    def _make_unique_project_name(self, project_name, existing_projects, source_profile):
        existing_names = {
            str((pdata or {}).get("name", "")).strip().casefold()
            for pdata in existing_projects.values()
        }
        base_name = str(project_name or "Project").strip() or "Project"
        candidate = base_name

        if candidate.casefold() not in existing_names:
            return candidate

        counter = 1
        while True:
            suffix = f" (từ {source_profile})" if counter == 1 else f" (từ {source_profile} {counter})"
            candidate = f"{base_name}{suffix}"
            if candidate.casefold() not in existing_names:
                return candidate
            counter += 1

    def _move_projects_to_guest_profile(self, source_profile, target_profile=GUEST_PROFILE):
        import shutil

        source_projects = self.load_projects_for_profile(source_profile)
        target_projects = self.load_projects_for_profile(target_profile)
        source_root = get_projects_root(source_profile)
        target_root = get_projects_root(target_profile)
        moved_names = []
        failed_messages = []
        remaining_source_projects = {}

        if os.path.isdir(source_root):
            for folder_name in os.listdir(source_root):
                folder_path = os.path.join(source_root, folder_name)
                if os.path.isdir(folder_path) and folder_name not in source_projects:
                    source_projects[folder_name] = {
                        "name": f"Project_{folder_name}",
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }

        for project_id, project_meta in list(source_projects.items()):
            project_meta = dict(project_meta or {})
            project_name = str(project_meta.get("name", "")).strip() or str(project_id)
            new_project_id = self._make_unique_project_id(project_id, target_profile, target_projects)
            safe_project_name = self._make_unique_project_name(project_name, target_projects, source_profile)
            project_meta["name"] = safe_project_name

            src_dir = os.path.join(source_root, str(project_id))
            dst_dir = os.path.join(target_root, str(new_project_id))

            try:
                if os.path.exists(src_dir):
                    shutil.move(src_dir, dst_dir)
                else:
                    os.makedirs(dst_dir, exist_ok=True)

                target_projects[new_project_id] = project_meta
                moved_names.append(safe_project_name)
            except Exception as exc:
                remaining_source_projects[str(project_id)] = project_meta
                failed_messages.append(f"- {project_name}: {exc}")

        self.save_projects_for_profile(target_profile, target_projects)
        self.save_projects_for_profile(source_profile, remaining_source_projects)
        return moved_names, failed_messages

    def delete_profile_dialog(self):
        selected_profile = (self.profile_var.get().strip() if hasattr(self, "profile_var") else "") or self.get_active_profile_name()
        protected_profile = GUEST_PROFILE.casefold()

        if selected_profile.casefold() == protected_profile:
            return messagebox.showwarning("Khóa an toàn", "Không thể xóa mục Vãng Lai vì đây là nơi giữ project cũ an toàn.")

        profiles = self.get_available_profiles()
        if len(profiles) <= 1:
            return messagebox.showwarning("Chú ý", "Phải giữ lại ít nhất 1 tài khoản làm việc.")

        guest_profile = GUEST_PROFILE
        get_profile_dir(guest_profile)

        profile_projects = self.load_projects_for_profile(selected_profile)
        project_names = []
        for project_id, pdata in profile_projects.items():
            project_names.append(str((pdata or {}).get("name", "")).strip() or str(project_id))

        source_root = get_projects_root(selected_profile)
        if os.path.isdir(source_root):
            for folder_name in os.listdir(source_root):
                folder_path = os.path.join(source_root, folder_name)
                if os.path.isdir(folder_path) and folder_name not in profile_projects:
                    project_names.append(f"Project_{folder_name}")

        unique_names = []
        seen = set()
        for name in project_names:
            key = name.casefold()
            if key not in seen:
                unique_names.append(name)
                seen.add(key)

        preview_lines = "\n".join(f"• {name}" for name in unique_names[:12]) if unique_names else "• Hiện chưa có project nào"
        if len(unique_names) > 12:
            preview_lines += f"\n• ... và {len(unique_names) - 12} project khác"

        confirm_message = (
            f"Tài khoản '{selected_profile}' đang có {len(unique_names)} project:\n\n"
            f"{preview_lines}\n\n"
            f"Khi xóa, toàn bộ project cũ sẽ được chuyển sang mục '{guest_profile}'.\n\n"
            f"Bác có chắc muốn xóa tài khoản này không?"
        )

        if not messagebox.askyesno("Xóa tài khoản", confirm_message):
            return

        if selected_profile == self.get_active_profile_name():
            self.switch_profile(guest_profile)

        moved_names, failed_messages = self._move_projects_to_guest_profile(selected_profile, guest_profile)
        if failed_messages:
            return messagebox.showerror(
                "Chưa xóa được",
                "Có vài project chưa chuyển xong nên tài khoản chưa bị xóa:\n\n" + "\n".join(failed_messages[:8])
            )

        profile_dir = os.path.join(get_workspace_dir(), selected_profile)
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception as exc:
            return messagebox.showerror("Lỗi xóa", f"Đã chuyển project nhưng chưa xóa được thư mục tài khoản:\n{exc}")

        self._refresh_profile_selector()
        if hasattr(self, "tab1"):
            self.tab1.refresh_project_list()
        if hasattr(self, "tab2"):
            self.tab2.update_combo_projects()
        if hasattr(self, "tab4"):
            self.tab4.load_excel_data()
        if hasattr(self, "tab11"):
            self.tab11.on_tab_activated()

        moved_count = len(moved_names)
        messagebox.showinfo("Đã xóa tài khoản", f"Đã xóa tài khoản '{selected_profile}'.\n\nĐã chuyển {moved_count} project sang mục '{guest_profile}'.")

    def get_proj_dir(self, pid, profile_name=None):
        return get_profile_project_dir(pid, profile_name or self.get_active_profile_name())

    def get_available_profiles(self):
        return get_all_profiles()

    def load_projects_for_profile(self, profile_name):
        target_file = get_projects_list_file(profile_name)
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_projects_for_profile(self, profile_name, projects_data):
        import shutil

        target_file = get_projects_list_file(profile_name)
        backup_file = target_file.replace(".json", "_backup.json")

        with self.json_lock:
            if os.path.exists(target_file) and os.path.getsize(target_file) > 0:
                try:
                    shutil.copy2(target_file, backup_file)
                except Exception:
                    pass

            try:
                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(projects_data, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

    def move_project_to_profile(self, project_id, target_profile):
        import shutil

        source_profile = self.get_active_profile_name()
        target_profile = str(target_profile or "").strip()

        if not project_id or project_id not in self.projects:
            return False, "Bác phải chọn đúng 1 project trước đã."
        if not target_profile:
            return False, "Bác chưa chọn tài khoản đích."
        if target_profile == source_profile:
            return False, "Không thể chuyển project vào chính tài khoản hiện tại."

        project_meta = self.projects.get(project_id, {}) or {}
        project_name = str(project_meta.get("name", "")).strip() or str(project_id)
        target_projects = self.load_projects_for_profile(target_profile)

        for _, pdata in target_projects.items():
            existing_name = str((pdata or {}).get("name", "")).strip()
            if existing_name.casefold() == project_name.casefold():
                return False, f"Tài khoản đích đã có project trùng tên: {project_name}"

        source_dir = os.path.join(get_projects_root(source_profile), str(project_id))
        target_dir = os.path.join(get_projects_root(target_profile), str(project_id))

        if not os.path.exists(source_dir):
            return False, "Không tìm thấy thư mục project để chuyển."
        if os.path.exists(target_dir):
            return False, "Tài khoản đích đã có sẵn thư mục project cùng mã này."

        try:
            shutil.move(source_dir, target_dir)
        except Exception as exc:
            return False, f"Không thể chuyển thư mục project: {exc}"

        self.projects.pop(project_id, None)
        self.save_projects()

        target_projects[project_id] = project_meta
        self.save_projects_for_profile(target_profile, target_projects)
        return True, f"Đã chuyển project '{project_name}' sang tài khoản {target_profile}."

    def load_config(self):
        conf_file = os.path.join(BASE_PATH, "config_dao_dien.json")
        try:
            with open(conf_file, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}

    def save_config(self):
        conf_file = os.path.join(BASE_PATH, "config_dao_dien.json")
        try:
            with open(conf_file, "w", encoding="utf-8") as f: json.dump(self.config, f, indent=4)
        except: pass

    def load_projects(self):
        try:
            with open(PROJECTS_LIST_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}

    # =======================================================
    # [NÂNG CẤP 1] - LƯU PROJECT CÓ BACKUP VÀ Ổ KHÓA
    # =======================================================
    def save_projects(self):
        import shutil
        backup_file = PROJECTS_LIST_FILE.replace(".json", "_backup.json")
        
        with self.json_lock: # Bật khóa an toàn
            # 1. Tạo file Backup
            if os.path.exists(PROJECTS_LIST_FILE) and os.path.getsize(PROJECTS_LIST_FILE) > 0:
                try: shutil.copy2(PROJECTS_LIST_FILE, backup_file)
                except: pass
            
            # 2. Ghi file chính
            try:
                with open(PROJECTS_LIST_FILE, "w", encoding="utf-8") as f: 
                    json.dump(self.projects, f, indent=4)
            except: pass

    # =======================================================
    # [NÂNG CẤP 2] - ĐỌC DATA CŨNG PHẢI ĐÓNG KHÓA (CHỐNG MẤT ĐIỂM)
    # =======================================================
    def get_project_data(self, pid):
        data_file = os.path.join(self.get_proj_dir(pid), "project_data.json")
        backup_file = os.path.join(self.get_proj_dir(pid), "project_data_backup.json")
        
        with self.json_lock: # Khóa lại không cho ai ghi lúc mình đang đọc
            # 1. Thử đọc file chính trước
            if os.path.exists(data_file):
                try:
                    with open(data_file, 'r', encoding='utf-8') as f: 
                        return json.load(f)
                except Exception as e:
                    print(f"⚠️ Cảnh báo: File dự án chính bị hỏng ({e}). Đang kích hoạt Backup...")
                    
                    # 2. Nếu file chính hỏng (do sập nguồn), lôi file Backup ra xài
                    if os.path.exists(backup_file):
                        try:
                            with open(backup_file, 'r', encoding='utf-8') as f: 
                                data = json.load(f)
                                
                                # Khôi phục đè ngược lại file chính luôn
                                with open(data_file, 'w', encoding='utf-8') as f_recover:
                                    json.dump(data, f_recover, indent=4)
                                return data
                        except: pass

        return {
            "videos": {},
            "trash": {},
            "timeline": [],
            "product_context": "",
            "product_name": "",
            "shopee_out_of_stock": False,
            "product_links": ["", "", "", "", "", ""],
        }

    # =======================================================
    # [NÂNG CẤP 3] - GHI DATA CHÍNH CHU TRỌN BỘ Ổ KHÓA + BACKUP
    # =======================================================
    def save_project_data(self, pid, data):
        import shutil
        data_file = os.path.join(self.get_proj_dir(pid), "project_data.json")
        backup_file = os.path.join(self.get_proj_dir(pid), "project_data_backup.json")
        
        with self.json_lock: # Bật khóa an toàn
            # 1. TẠO FILE BACKUP
            if os.path.exists(data_file) and os.path.getsize(data_file) > 0:
                try:
                    shutil.copy2(data_file, backup_file)
                except:
                    pass
                    
            # 2. GHI ĐÈ FILE CHÍNH
            try:
                with open(data_file, 'w', encoding='utf-8') as f: 
                    json.dump(data, f, indent=4)
            except Exception as e:
                print(f"Lỗi khi lưu data: {e}")

    def setup_ui(self):
        # ... (Từ đoạn này sếp giữ nguyên code cũ của sếp nhé) ...
        style = ttk.Style()
        style.theme_use("clam")

        top_profile_frame = tk.Frame(self.root, bg="#f4f6f9", padx=10, pady=6)
        top_profile_frame.pack(fill="x", padx=10, pady=(8, 0))

        tk.Label(top_profile_frame, text="🏛️ Tài khoản làm việc:", bg="#f4f6f9", fg="#2c3e50", font=("Arial", 10, "bold")).pack(side="left")
        self.profile_var = tk.StringVar(value=self.get_active_profile_name())
        self.cmb_profile = ttk.Combobox(top_profile_frame, textvariable=self.profile_var, state="readonly", width=24, font=("Arial", 10))
        self.cmb_profile.pack(side="left", padx=(8, 6))
        self.cmb_profile.bind("<<ComboboxSelected>>", self.on_profile_selected)

        tk.Button(top_profile_frame, text="➕ Tạo tài khoản", bg="#27ae60", fg="white", font=("Arial", 9, "bold"), command=self.create_profile_dialog).pack(side="left", padx=(0, 6))
        tk.Button(top_profile_frame, text="✏️ Đổi tên tài khoản", bg="#f39c12", fg="white", font=("Arial", 9, "bold"), command=self.rename_profile_dialog).pack(side="left", padx=(0, 6))
        tk.Button(top_profile_frame, text="🗑️ Xóa tài khoản", bg="#c0392b", fg="white", font=("Arial", 9, "bold"), command=self.delete_profile_dialog).pack(side="left", padx=(0, 10))
        self.lbl_profile_hint = tk.Label(top_profile_frame, text="", bg="#f4f6f9", fg="#7f8c8d", font=("Arial", 9, "italic"))
        self.lbl_profile_hint.pack(side="left")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        self.frame_tab1 = tk.Frame(self.notebook, bg="#f4f6f9")
        self.frame_tab2 = tk.Frame(self.notebook, bg="#f4f6f9")
        self.frame_tab4 = tk.Frame(self.notebook, bg="#f4f6f9") 
        self.frame_tab5 = tk.Frame(self.notebook, bg="#f4f6f9")
        self.frame_tab11 = tk.Frame(self.notebook, bg="#f4f6f9")
        
        self.notebook.add(self.frame_tab1, text=" 📂KHO CẢNH TRÁM ")
        self.notebook.add(self.frame_tab2, text=" 🚀 EDIT VIDEO ĐA LUỒNG ")
        self.notebook.add(self.frame_tab4, text=" 📊 QUẢN LÝ VIDEO ")
        self.notebook.add(self.frame_tab5, text=" 📱 QUẢN LÝ ĐIỆN THOẠI ")
        self.notebook.add(self.frame_tab11, text=" 🚜 AUTO ĐĂNG SHOPEE ")
        
        self.tab1 = BRollTab(self.frame_tab1, self)
        self.tab2 = FacelessTab(self.frame_tab2, self)
        self.tab4 = ManagerTab(self.frame_tab4, self) 
        self.tab5 = PhoneManagerTab(self.frame_tab5, self)
        self.tab11 = AutoPostTab(self.frame_tab11, self)

        # [ĐÃ XÓA] TikTok Upload Tab

        self.tab7_frame = tk.Frame(self.notebook, bg="#f4f6f9")
        self.notebook.add(self.tab7_frame, text="🍲 XÀO KỊCH BẢN")
        self.tab7 = ScriptTab(self.tab7_frame, self)

   

        # Thêm khung cho Tab 9
        self.tab9_frame = tk.Frame(self.notebook, bg="#f4f6f9")
        self.notebook.add(self.tab9_frame, text=" 🔪 GHÉP KỊCH BẢN ")
        self.tab9 = ScriptAnalysisTab(self.tab9_frame, self)

             # TAB 8: TELEGRAM BOT
        self.tab8_frame = tk.Frame(self.notebook, bg="#f4f6f9")
        self.notebook.add(self.tab8_frame, text=" 🤖CẤU HÌNH BOT TELEGRAM ")
        self.tab8 = TelegramTab(self.tab8_frame, self)

        # [THÊM TAB 10 VÀO ĐÂY]
        self.tab10_frame = tk.Frame(self.notebook, bg="#f4f6f9")
        self.notebook.add(self.tab10_frame, text=" ⚙️CẤU HÌNH HỆ THỐNG ")
        self.tab10 = ConfigTab(self.tab10_frame, self)





        # Khởi tạo Quản lý Bot
        self.telegram_manager = TelegramBotManager(self)
        self.telegram_manager.start_telegram_bot()

        self._refresh_profile_selector()
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

    def on_tab_changed(self, event):
        self._refresh_profile_selector()
        self.tab2.update_combo_projects()
        self.tab1.refresh_project_list()
        self.tab4.load_excel_data() 
        if hasattr(self, 'tab5'):
            self.tab5.on_tab_activated()
        if hasattr(self, 'tab11'):
            self.tab11.on_tab_activated()

    # =================================================================
    # HÀM CẦU NỐI (PROXY) TỪ TAB 8 SANG BOT MANAGER
    # =================================================================
    def restart_telegram_bot(self):
        """Hàm này được gọi từ Tab 8 khi bác bấm 'Lưu & Khởi Động' """
        if hasattr(self, 'telegram_manager') and self.telegram_manager:
            self.telegram_manager.stop_telegram_bot()
            import time
            time.sleep(1) 
            self.telegram_manager.start_telegram_bot()
        
    def stop_telegram_bot(self):
        """Hàm này được gọi từ Tab 8 khi bác bấm 'Tắt Bot' """
        if hasattr(self, 'telegram_manager') and self.telegram_manager:
            self.telegram_manager.stop_telegram_bot()

if __name__ == "__main__":
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()