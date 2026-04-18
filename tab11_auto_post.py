import os
import random
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2

from paths import BASE_PATH
from shopee_export import (
    POSTED_VIDEO_DIR,
    VIDEO_OUTPUT_DIR,
    claim_next_shopee_job,
    get_shopee_csv_path,
    load_shopee_jobs,
    resolve_shopee_video_path,
    update_shopee_status,
)

try:
    import uiautomator2 as u2
except ImportError:
    u2 = None


class AutoPostTab:
    REQUIRED_IMAGE_FILES = [
        "tab_live.png",
        "icon_canhan.png",
        "nut_dang_video.png",
        "chu_thu_vien.png",
        "nut_tiep_theo.png",
        "nut_tiep_theo_2.png",
        "o_nhap_mota.png",
        "nut_dong_y.png",
        "nut_them_san_pham.png",
        "icon_link.png",
        "only_link.png",
        "nut_xoa_tat_ca.png",
        "nut_nhap.png",
        "chon_tat_ca.png",
        "nut_them_sp_cuoi.png",
        "nut_dang_cuoi.png",
    ]
    REMOTE_VIDEO_EXTENSIONS = ("mp4", "mov", "avi", "mkv", "3gp", "webm", "m4v")
    REMOTE_VIDEO_DIRS = (
        "/sdcard/DCIM/Camera",
        "/sdcard/DCIM",
        "/sdcard/Movies",
        "/sdcard/Download",
        "/sdcard/Pictures",
    )

    def __init__(self, parent_frame, main_app):
        self.parent = parent_frame
        self.main_app = main_app
        self.parent.config(bg="#f8f9fa")

        self.is_farming = False
        self.is_paused = False
        self.active_workers = 0
        self.active_workers_lock = threading.Lock()
        self.job_retry_counts = {}
        self.job_retry_lock = threading.Lock()
        self.runtime_csv_path = ""

        self.var_stagger = tk.IntVar(value=int(self.main_app.config.get("auto_post_stagger", 15)))
        self.var_click_delay = tk.DoubleVar(value=float(self.main_app.config.get("auto_post_click_delay", 1.0)))
        self.var_upload_wait = tk.IntVar(value=int(self.main_app.config.get("auto_post_upload_wait", 25)))
        self.var_rest_min = tk.IntVar(value=int(self.main_app.config.get("auto_post_rest_min", 8)))
        self.var_rest_max = tk.IntVar(value=int(self.main_app.config.get("auto_post_rest_max", 15)))
        self.var_match_threshold = tk.DoubleVar(value=float(self.main_app.config.get("auto_post_match_threshold", 0.82)))

        self.setup_ui()
        self._bind_settings()
        self.refresh_jobs_preview()

    def setup_ui(self):
        top_frame = tk.Frame(self.parent, bg="#e8f4f8", pady=15, padx=20, bd=1, relief="solid")
        top_frame.pack(fill="x", side="top", pady=10, padx=20)
        tk.Label(
            top_frame,
            text="🚜 TRUNG TÂM KIỂM SOÁT AUTO ĐĂNG SHOPEE",
            bg="#e8f4f8",
            font=("Arial", 16, "bold"),
            fg="#d9534f",
        ).pack(side="left", padx=10)

        self.btn_stop = tk.Button(
            top_frame,
            text="⏹ DỪNG HẲN",
            bg="#d9534f",
            fg="white",
            font=("Arial", 12, "bold"),
            command=self.stop_auto_post,
            state="disabled",
            width=15,
        )
        self.btn_stop.pack(side="right", padx=10)
        self.btn_pause = tk.Button(
            top_frame,
            text="⏸ TẠM DỪNG",
            bg="#f0ad4e",
            fg="white",
            font=("Arial", 12, "bold"),
            command=self.pause_auto_post,
            state="disabled",
            width=15,
        )
        self.btn_pause.pack(side="right", padx=10)
        self.btn_auto = tk.Button(
            top_frame,
            text="▶ BẮT ĐẦU AUTO ĐĂNG",
            bg="#28a745",
            fg="white",
            font=("Arial", 12, "bold"),
            command=self.start_auto_post,
            width=20,
        )
        self.btn_auto.pack(side="right", padx=10)

        self.manage_status = tk.Label(
            self.parent,
            text="🖱️ Nếu có ảnh mẫu trong thư mục Phone_image, tool sẽ ưu tiên bấm bằng ảnh; nếu thiếu thì dùng tọa độ fallback.",
            fg="#337ab7",
            font=("Arial", 11, "italic", "bold"),
            bg="#f8f9fa",
        )
        self.manage_status.pack(pady=5)

        content = tk.PanedWindow(self.parent, orient=tk.HORIZONTAL, sashwidth=6, bg="#f8f9fa")
        content.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        left_panel = tk.Frame(content, bg="#f8f9fa")
        right_panel = tk.Frame(content, bg="#f8f9fa")
        content.add(left_panel, minsize=520)
        content.add(right_panel, minsize=520)

        settings_frame = tk.LabelFrame(
            left_panel,
            text=" ⚙️ Cấu hình Farm ",
            bg="#ffffff",
            font=("Arial", 11, "bold"),
            padx=15,
            pady=10,
        )
        settings_frame.pack(fill="x", pady=(0, 10))

        self._add_setting_row(settings_frame, 0, "Giãn cách máy (s):", self.var_stagger, 3, 120)
        self._add_setting_row(settings_frame, 1, "Delay click (s):", self.var_click_delay, 0.2, 5.0, increment=0.1)
        self._add_setting_row(settings_frame, 2, "Chờ upload sau đăng (s):", self.var_upload_wait, 5, 180)
        self._add_setting_row(settings_frame, 3, "Nghỉ min (s):", self.var_rest_min, 3, 180)
        self._add_setting_row(settings_frame, 4, "Nghỉ max (s):", self.var_rest_max, 3, 300)
        self._add_setting_row(settings_frame, 5, "Ngưỡng khớp ảnh:", self.var_match_threshold, 0.6, 0.98, increment=0.01)

        path_frame = tk.LabelFrame(
            left_panel,
            text=" 📁 Nguồn dữ liệu ",
            bg="#ffffff",
            font=("Arial", 11, "bold"),
            padx=15,
            pady=10,
        )
        path_frame.pack(fill="x", pady=(0, 10))

        tk.Label(path_frame, text="File job Shopee CSV:", bg="#ffffff", font=("Arial", 10, "bold")).pack(anchor="w")
        self.lbl_csv_path = tk.Label(path_frame, text=self.get_current_csv_path(), bg="#ffffff", justify="left", fg="#2c3e50", wraplength=520)
        self.lbl_csv_path.pack(anchor="w", pady=(2, 8))

        btn_path = tk.Frame(path_frame, bg="#ffffff")
        btn_path.pack(fill="x")
        tk.Button(btn_path, text="📌 Chọn CSV", bg="#8e44ad", fg="white", font=("Arial", 9, "bold"), command=self.pick_shopee_csv).pack(side="left", padx=(0, 8))
        tk.Button(btn_path, text="📑 Mở CSV", bg="#3498db", fg="white", font=("Arial", 9, "bold"), command=self.open_shopee_csv).pack(side="left", padx=(0, 8))
        tk.Button(btn_path, text="📂 Mở kho video", bg="#16a085", fg="white", font=("Arial", 9, "bold"), command=self.open_video_folder).pack(side="left", padx=(0, 8))
        tk.Button(btn_path, text="🖼️ Mở thư mục ảnh", bg="#e67e22", fg="white", font=("Arial", 9, "bold"), command=self.open_image_folder).pack(side="left")

        cv_frame = tk.LabelFrame(
            left_panel,
            text=" 🖼️ Trung tâm ảnh mắt thần OpenCV ",
            bg="#ffffff",
            font=("Arial", 11, "bold"),
            fg="#e67e22",
            padx=15,
            pady=10,
        )
        cv_frame.pack(fill="both", expand=True)

        tk.Label(
            cv_frame,
            text="Hệ thống tự động nhận diện ảnh trong thư mục Phone_image. Bác chỉ cần cắt ảnh đúng nút và thả vào thư mục này.",
            bg="#ffffff",
            fg="#337ab7",
            font=("Arial", 10, "bold"),
            justify="left",
            wraplength=520,
        ).pack(anchor="w", pady=(0, 10))

        files_req = "\n".join(f"{idx + 1}. {name}" for idx, name in enumerate(self.REQUIRED_IMAGE_FILES))
        tk.Label(
            cv_frame,
            text=f"📌 Danh sách ảnh nên có:\n{files_req}",
            bg="#f9f9f9",
            fg="#d35400",
            font=("Courier New", 9, "bold"),
            justify="left",
            anchor="w",
            padx=10,
            pady=10,
        ).pack(fill="x")

        info_frame = tk.LabelFrame(
            right_panel,
            text=" 📋 Danh sách job Shopee ",
            bg="#ffffff",
            font=("Arial", 11, "bold"),
            padx=15,
            pady=10,
        )
        info_frame.pack(fill="both", expand=True, pady=(0, 10))

        summary_bar = tk.Frame(info_frame, bg="#ffffff")
        summary_bar.pack(fill="x", pady=(0, 8))
        self.lbl_job_summary = tk.Label(summary_bar, text="Chưa nạp file job.", bg="#ffffff", fg="#8e44ad", font=("Arial", 10, "bold"))
        self.lbl_job_summary.pack(side="left")
        tk.Button(summary_bar, text="🔄 Làm mới danh sách", bg="#34495e", fg="white", font=("Arial", 9, "bold"), command=self.refresh_jobs_preview).pack(side="right")

        cols = ("stt", "video", "product", "status")
        self.tree_jobs = ttk.Treeview(info_frame, columns=cols, show="headings", height=16)
        self.tree_jobs.heading("stt", text="STT")
        self.tree_jobs.heading("video", text="Tên Video")
        self.tree_jobs.heading("product", text="Tên Sản Phẩm")
        self.tree_jobs.heading("status", text="Trạng thái")
        self.tree_jobs.column("stt", width=60, anchor="center")
        self.tree_jobs.column("video", width=320, anchor="w")
        self.tree_jobs.column("product", width=200, anchor="w")
        self.tree_jobs.column("status", width=160, anchor="center")
        self.tree_jobs.tag_configure("done", foreground="#27ae60")
        self.tree_jobs.tag_configure("processing", foreground="#e67e22")
        self.tree_jobs.tag_configure("error", foreground="#c0392b")
        self.tree_jobs.tag_configure("pending", foreground="#2c3e50")

        job_scroll = ttk.Scrollbar(info_frame, orient="vertical", command=self.tree_jobs.yview)
        self.tree_jobs.configure(yscrollcommand=job_scroll.set)
        self.tree_jobs.pack(side="left", fill="both", expand=True)
        job_scroll.pack(side="right", fill="y")

        guide_frame = tk.LabelFrame(
            right_panel,
            text=" Hướng dẫn vận hành ",
            bg="#ffffff",
            font=("Arial", 11, "bold"),
            fg="#8e44ad",
            padx=15,
            pady=10,
        )
        guide_frame.pack(fill="x")
        instructions = (
            "✅ BƯỚC 1: Render video ở tab Edit Video để sinh file job Shopee CSV.\n"
            "✅ BƯỚC 2: Sang tab Quản Lý Điện Thoại, tick chọn các box phone cần chạy.\n"
            "✅ BƯỚC 3: Kiểm tra thư mục Phone_image đã đủ ảnh mẫu.\n"
            "🚀 BƯỚC 4: Quay lại đây bấm [▶ BẮT ĐẦU AUTO ĐĂNG]."
        )
        tk.Label(guide_frame, text=instructions, bg="#ffffff", font=("Arial", 11), justify="left", anchor="nw").pack(fill="x")

    def _add_setting_row(self, parent, row_idx, label_text, variable, min_val, max_val, increment=1):
        row = tk.Frame(parent, bg="#ffffff")
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label_text, bg="#ffffff", font=("Arial", 10), width=22, anchor="w").pack(side="left")
        spin = tk.Spinbox(
            row,
            textvariable=variable,
            from_=min_val,
            to=max_val,
            increment=increment,
            width=8,
            font=("Arial", 10),
        )
        spin.pack(side="left")

    def _bind_settings(self):
        bindings = {
            "auto_post_stagger": self.var_stagger,
            "auto_post_click_delay": self.var_click_delay,
            "auto_post_upload_wait": self.var_upload_wait,
            "auto_post_rest_min": self.var_rest_min,
            "auto_post_rest_max": self.var_rest_max,
            "auto_post_match_threshold": self.var_match_threshold,
        }
        for config_key, variable in bindings.items():
            variable.trace_add("write", lambda *args, key=config_key, var=variable: self._save_setting(key, var))

    def _save_setting(self, config_key, variable):
        try:
            self.main_app.config[config_key] = variable.get()
            self.main_app.save_config()
        except Exception:
            pass

    def on_tab_activated(self):
        self._refresh_csv_path_label()
        self.refresh_jobs_preview()

    def get_current_csv_path(self):
        return get_shopee_csv_path(self.main_app.config)

    def get_active_csv_path(self):
        return self.runtime_csv_path or self.get_current_csv_path()

    def _refresh_csv_path_label(self):
        if hasattr(self, "lbl_csv_path") and self.lbl_csv_path.winfo_exists():
            self.lbl_csv_path.config(text=self.get_current_csv_path())

    def get_phone_image_dir(self):
        folder = os.path.join(BASE_PATH, "Phone_image")
        os.makedirs(folder, exist_ok=True)
        return folder

    def open_image_folder(self):
        folder = self.get_phone_image_dir()
        if os.name == "nt":
            os.startfile(folder)

    def pick_shopee_csv(self):
        if self.is_farming:
            messagebox.showwarning("Đang chạy", "Không đổi file CSV khi hệ thống auto đăng đang chạy.")
            return

        initial_path = self.get_current_csv_path()
        selected_path = filedialog.asksaveasfilename(
            title="Chọn file CSV job Shopee",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialdir=os.path.dirname(initial_path) if os.path.dirname(initial_path) else BASE_PATH,
            initialfile=os.path.basename(initial_path),
        )
        if not selected_path:
            return

        self.main_app.config["shopee_csv_path"] = selected_path
        self.main_app.save_config()
        self._refresh_csv_path_label()
        self.refresh_jobs_preview()

    def open_shopee_csv(self):
        csv_path = self.get_current_csv_path()
        if os.path.exists(csv_path):
            os.startfile(csv_path)
        else:
            messagebox.showwarning("Thiếu file", "Chưa có file CSV job Shopee. Bác render video trước đã.")

    def open_video_folder(self):
        os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)
        if os.name == "nt":
            os.startfile(VIDEO_OUTPUT_DIR)

    def refresh_jobs_preview(self):
        self._refresh_csv_path_label()

        for item in self.tree_jobs.get_children():
            self.tree_jobs.delete(item)

        jobs = load_shopee_jobs(csv_path=self.get_active_csv_path())
        pending_count = 0
        processing_count = 0
        done_count = 0

        for job in jobs:
            status = job.get("status", "")
            if "Đã đăng" in status:
                tag = "done"
                done_count += 1
            elif "Đang xử" in status:
                tag = "processing"
                processing_count += 1
            elif "Lỗi" in status:
                tag = "error"
            else:
                tag = "pending"
                pending_count += 1

            self.tree_jobs.insert(
                "",
                "end",
                values=(job.get("stt", ""), job.get("video_name", ""), job.get("product_name", ""), status),
                tags=(tag,),
            )

        if not jobs:
            self.lbl_job_summary.config(text="Chưa có job nào trong file CSV Shopee.", fg="#c0392b")
        else:
            self.lbl_job_summary.config(
                text=f"Tổng {len(jobs)} job | Chờ đăng: {pending_count} | Đang xử: {processing_count} | Đã đăng: {done_count}",
                fg="#8e44ad",
            )

    def show_status_temp(self, msg, color="green", duration=3500):
        if hasattr(self, "manage_status") and self.manage_status.winfo_exists():
            self.manage_status.config(text=msg, fg=color)
            if duration > 0:
                self.parent.after(duration, lambda: self.manage_status.config(text="🖱️ Đang chờ lệnh auto đăng...", fg="#337ab7"))

    def get_adb_path(self):
        if hasattr(self.main_app, "tab5") and getattr(self.main_app.tab5, "adb_path", ""):
            return self.main_app.tab5.adb_path
        local_adb = os.path.join(BASE_PATH, "adb.exe")
        return local_adb if os.path.exists(local_adb) else "adb"

    def pause_auto_post(self):
        if not self.is_farming:
            return
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.btn_pause.config(text="▶ TIẾP TỤC", bg="#5bc0de")
            self.show_status_temp("⏸ Đã ra lệnh tạm dừng. Các máy sẽ dừng sau bước hiện tại.", "orange", 0)
        else:
            self.btn_pause.config(text="⏸ TẠM DỪNG", bg="#f0ad4e")
            self.show_status_temp("▶ Đã tiếp tục dàn auto đăng.", "green")

    def stop_auto_post(self):
        if not self.is_farming:
            return
        if messagebox.askyesno("Cảnh báo", "Bác có chắc muốn dừng hẳn hệ thống auto đăng không?"):
            self.is_farming = False
            self.is_paused = False
            self.btn_stop.config(text="⏳ ĐANG DỪNG...", state="disabled")
            self.btn_pause.config(state="disabled")
            self.show_status_temp("⏹ Đang gửi lệnh dừng tới tất cả các máy...", "red", 0)

    def start_auto_post(self):
        if u2 is None:
            return messagebox.showerror("Thiếu thư viện", "Chưa cài uiautomator2. Cài thư viện này thì tab auto đăng mới chạy được.")

        csv_path = self.get_current_csv_path()
        if not os.path.exists(csv_path):
            return messagebox.showerror("Thiếu file", f"Không tìm thấy file CSV job Shopee:\n{csv_path}\n\nHãy render video trước hoặc chọn file CSV khác.")

        selected_devices = self.main_app.tab5.get_selected_devices() if hasattr(self.main_app, "tab5") else []
        if not selected_devices:
            messagebox.showwarning("Chưa chọn máy", "Bác chưa tick máy nào ở tab Quản Lý Điện Thoại.")
            if hasattr(self.main_app, "frame_tab5"):
                self.main_app.notebook.select(self.main_app.frame_tab5)
            return

        self.runtime_csv_path = csv_path
        self.is_farming = True
        self.is_paused = False
        self.btn_auto.config(state="disabled", text="🚜 ĐANG CHẠY AUTO")
        self.btn_stop.config(state="normal", text="⏹ DỪNG HẲN")
        self.btn_pause.config(state="normal", text="⏸ TẠM DỪNG", bg="#f0ad4e")
        self.show_status_temp(f"🚀 Bắt đầu auto đăng trên {len(selected_devices)} máy.", "green")

        with self.active_workers_lock:
            self.active_workers = len(selected_devices)

        for index, device_id in enumerate(selected_devices):
            self.main_app.tab5.update_device_farm_status(device_id, "🚀 Chuẩn bị xuất kích...")
            delay_time = index * max(0, int(self.var_stagger.get()))
            threading.Thread(target=self._farm_worker_delayed, args=(device_id, delay_time), daemon=True).start()

    def _farm_worker_delayed(self, device_id, delay_time):
        adb_cmd = self.get_adb_path()
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        remote_dir = "/sdcard/DCIM/Camera/"
        current_job = None
        job_csv_path = self.get_active_csv_path()

        def upd_status(msg):
            self.parent.after(0, lambda: self.main_app.tab5.update_device_farm_status(device_id, msg))

        def update_job_status(video_name, status):
            update_shopee_status(video_name, status, csv_path=job_csv_path)
            self.parent.after(0, self.refresh_jobs_preview)

        try:
            if delay_time > 0:
                upd_status(f"⏳ Đợi tới lượt ({delay_time}s)")
                for _ in range(delay_time):
                    if not self.is_farming:
                        break
                    time.sleep(1)

            if not self.is_farming:
                return

            upd_status("🧹 Dọn toàn bộ video cũ trên máy...")
            self._clear_remote_videos(adb_cmd, device_id, creationflags, remote_dir=remote_dir, clear_all_dirs=True)

            upd_status("🔌 Kết nối U2...")
            device = u2.connect(device_id)
            try:
                device.set_input_ime(True)
            except Exception:
                pass
            self._normalize_device_orientation(device)

            is_app_running = False

            while self.is_farming:
                current_job = None
                self._wait_if_paused(device_id)
                if not self.is_farming:
                    break

                upd_status("🔎 Đang nhận job từ CSV...")
                current_job = claim_next_shopee_job(device_id[-4:], csv_path=job_csv_path)
                self.parent.after(0, self.refresh_jobs_preview)
                if not current_job:
                    upd_status("🎉 Hoàn thành! (Hết job)")
                    break

                video_name = current_job["video_name"]
                caption_text = current_job.get("caption", "")
                link_text = str(current_job.get("link", "") or "")
                video_path = resolve_shopee_video_path(video_name)

                if not os.path.exists(video_path):
                    self._clear_job_retry(device_id, video_name)
                    update_job_status(video_name, "Lỗi mất file ❌")
                    upd_status(f"❌ Mất file: {video_name}")
                    current_job = None
                    time.sleep(1)
                    continue

                # =========================================================
                # [FIX BẮT ĐẦU TỪ ĐÂY] - Trị dứt điểm bệnh ADB kén Tiếng Việt
                # =========================================================
                import tempfile
                
                # Tạo tên file thuần tiếng Anh không dấu để ADB không bị "ngáo"
                file_ext = os.path.splitext(video_path)[1] or ".mp4"
                safe_remote_name = f"auto_shopee_{int(time.time())}{file_ext}"
                remote_video_path = self._join_remote_path(remote_dir, safe_remote_name)
                
                upd_status(f"🧹 Dọn thư mục video rồi đẩy {video_name} vào máy...")
                self._clear_remote_videos(adb_cmd, device_id, creationflags, remote_dir=remote_dir, clear_all_dirs=False)
                subprocess.run([adb_cmd, "-s", device_id, "shell", "mkdir", "-p", remote_dir], creationflags=creationflags)

                push_ok = False
                temp_local_path = ""
                try:
                    # 1. Copy file ra thư mục Temp của máy tính
                    temp_local_path = os.path.join(tempfile.gettempdir(), safe_remote_name)
                    shutil.copy2(video_path, temp_local_path)
                    
                    # 2. Push file Temp (tên an toàn) lên điện thoại
                    result = subprocess.run(
                        [adb_cmd, "-s", device_id, "push", temp_local_path, remote_video_path],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="ignore", # Chống văng app nếu ADB nhả log ký tự lạ
                        timeout=120,
                        creationflags=creationflags,
                    )
                    
                    if result.returncode == 0:
                        self._broadcast_media_scan(adb_cmd, device_id, remote_video_path, creationflags)
                        time.sleep(2)
                        push_ok = True
                    else:
                        push_error = (result.stderr or result.stdout or "adb push thất bại").strip()
                        upd_status(f"❌ Push lỗi: {push_error[:60]}")
                        
                except subprocess.TimeoutExpired:
                    upd_status("❌ Đẩy file quá lâu, bỏ job này.")
                except Exception as e:
                    upd_status(f"❌ Lỗi copy/đẩy file: {str(e)[:40]}")
                finally:
                    # 3. Quét dọn file Temp trên máy tính để không tốn ổ C
                    if temp_local_path and os.path.exists(temp_local_path):
                        try: os.remove(temp_local_path)
                        except: pass
                # =========================================================
                # [FIX KẾT THÚC Ở ĐÂY]
                # =========================================================

                if not push_ok:
                    retry_count = self._increment_job_retry(device_id, video_name)
                    if retry_count >= 2:
                        self._clear_job_retry(device_id, video_name)
                        update_job_status(video_name, "Lỗi chuyển file ❌")
                        upd_status("❌ Đẩy file lỗi 2 lần, bỏ qua job này.")
                    else:
                        update_job_status(video_name, "Chưa chuyển")
                        upd_status("🔁 Đẩy file lỗi, sẽ thử lại job này thêm 1 lần.")
                    current_job = None
                    time.sleep(2)
                    continue

                try:
                    self._run_post_workflow(device, device_id, adb_cmd, caption_text, link_text, is_app_running, upd_status)
                    is_app_running = True
                except LimitReachedError:
                    self._clear_job_retry(device_id, video_name)
                    update_job_status(video_name, "Chưa chuyển")
                    upd_status("🛑 Máy này đã chạm giới hạn đăng hôm nay.")
                    self._cleanup_remote_file(adb_cmd, device_id, remote_video_path, creationflags)
                    current_job = None
                    break
                except LinkImportError:
                    self._clear_job_retry(device_id, video_name)
                    update_job_status(video_name, "Lỗi Link ❌")
                    upd_status("⚠️ Link sản phẩm lỗi, bỏ qua job này.")
                    self._force_stop_shopee(adb_cmd, device_id, creationflags)
                    is_app_running = False
                    self._cleanup_remote_file(adb_cmd, device_id, remote_video_path, creationflags)
                    current_job = None
                    continue
                except Exception as exc:
                    retry_count = self._increment_job_retry(device_id, video_name)
                    if retry_count >= 2:
                        self._clear_job_retry(device_id, video_name)
                        update_job_status(video_name, "Lỗi quy trình ❌")
                        upd_status(f"❌ Lỗi quy trình 2 lần, bỏ qua: {str(exc)[:45]}")
                    else:
                        update_job_status(video_name, "Chưa chuyển")
                        upd_status(f"❌ Lỗi quy trình, sẽ thử lại: {str(exc)[:45]}")
                    self._force_stop_shopee(adb_cmd, device_id, creationflags)
                    is_app_running = False
                    self._cleanup_remote_file(adb_cmd, device_id, remote_video_path, creationflags)
                    current_job = None
                    time.sleep(2)
                    continue

                wait_upload = max(1, int(self.var_upload_wait.get()))
                upd_status(f"⏳ Chờ Shopee xử lý sau đăng ({wait_upload}s)...")
                for _ in range(wait_upload):
                    if not self.is_farming:
                        break
                    self._wait_if_paused(device_id)
                    time.sleep(1)

                update_job_status(video_name, "Đã đăng ✅")
                self._clear_job_retry(device_id, video_name)
                upd_status("✅ Đăng xong, đang dọn file...")
                os.makedirs(POSTED_VIDEO_DIR, exist_ok=True)
                if os.path.exists(video_path):
                    try:
                        shutil.move(video_path, os.path.join(POSTED_VIDEO_DIR, video_name))
                    except Exception:
                        pass
                self._cleanup_remote_file(adb_cmd, device_id, remote_video_path, creationflags)
                current_job = None

                rest_min = max(1, int(self.var_rest_min.get()))
                rest_max = max(rest_min, int(self.var_rest_max.get()))
                rest_time = random.randint(rest_min, rest_max)
                for remaining in range(rest_time, 0, -1):
                    if not self.is_farming:
                        break
                    self._wait_if_paused(device_id)
                    upd_status(f"💤 Nghỉ chống spam ({remaining}s)...")
                    time.sleep(1)

            try:
                device.set_input_ime(False)
            except Exception:
                pass
            try:
                device.freeze_rotation(False)
            except Exception:
                pass
        except Exception as exc:
            upd_status(f"❌ Lỗi thiết bị: {str(exc)[:70]}")
            if current_job:
                update_job_status(current_job["video_name"], "Chưa chuyển")
        finally:
            if current_job and self.is_farming is False:
                update_job_status(current_job["video_name"], "Chưa chuyển")
            with self.active_workers_lock:
                self.active_workers -= 1
                if self.active_workers <= 0:
                    self.runtime_csv_path = ""
                    self.is_farming = False
                    self.is_paused = False
                    self.parent.after(0, lambda: self.btn_auto.config(state="normal", text="▶ BẮT ĐẦU AUTO ĐĂNG"))
                    self.parent.after(0, lambda: self.btn_stop.config(state="disabled", text="⏹ DỪNG HẲN"))
                    self.parent.after(0, lambda: self.btn_pause.config(state="disabled", text="⏸ TẠM DỪNG", bg="#f0ad4e"))
                    self.parent.after(0, lambda: self.show_status_temp("⏹ Hệ thống auto đăng đã dừng hoàn toàn.", "blue", 0))
            self.parent.after(0, self.refresh_jobs_preview)

    def _wait_if_paused(self, device_id):
        while self.is_paused and self.is_farming:
            self.main_app.tab5.update_device_farm_status(device_id, "⏸ Đang tạm dừng...")
            time.sleep(1)

    def _run_post_workflow(self, device, device_id, adb_cmd, caption_text, link_text, is_app_running, upd_status):
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

        def adb_tap(x, y):
            subprocess.run([adb_cmd, "-s", device_id, "shell", "input", "tap", str(x), str(y)], creationflags=creationflags)
            time.sleep(float(self.var_click_delay.get()))

        self._normalize_device_orientation(device)

        if not is_app_running:
            upd_status("🚀 Khởi động Shopee...")
            self._force_stop_shopee(adb_cmd, device_id, creationflags)
            time.sleep(2)
            device.app_start("com.shopee.vn")
            time.sleep(15)
            self._normalize_device_orientation(device)
            self._tap_by_image(device_id, "tab_live.png", timeout=15, fallback=(543, 2024))
            time.sleep(4)

        upd_status("🔍 Tìm icon Cá Nhân...")
        found_icon = False
        for _ in range(3):
            try:
                self._tap_by_image(device_id, "icon_canhan.png", conf=0.75, timeout=5)
                found_icon = True
                break
            except Exception:
                subprocess.run([adb_cmd, "-s", device_id, "shell", "input", "swipe", "500", "1500", "500", "500", "300"], creationflags=creationflags)
                time.sleep(3)

        if not found_icon:
            width, height = device.window_size()
            tap_x = int(width * 0.093)
            tap_y = int(height * (0.097 if (height / width) < 1.8 else 0.075))
            adb_tap(tap_x, tap_y)

        time.sleep(3)
        self._tap_by_image(device_id, "nut_dang_video.png", timeout=10)
        time.sleep(3)
        self._tap_by_image(device_id, "chu_thu_vien.png", timeout=10)
        time.sleep(3)
        self._normalize_device_orientation(device)

        upd_status("🤖 Chọn video vừa đẩy lên máy...")
        width, height = device.window_size()
        tap_x = int(width * 0.22)
        tap_y = int(height * (0.175 if (height / width) < 1.8 else 0.165))
        adb_tap(tap_x, tap_y)
        time.sleep(2)

        self._tap_by_image(device_id, "nut_tiep_theo.png", timeout=10)
        time.sleep(4)

        upd_status("⏳ Đang chờ Shopee load video...")
        wait_time = 0
        while wait_time < 180:
            if not self.is_farming:
                raise RuntimeError("Dừng auto")
            if device(textContains="Đang tải").exists or device(textContains="Uploading").exists:
                time.sleep(2)
                wait_time += 2
                continue
            time.sleep(3)
            break

        self._tap_by_image(device_id, "nut_tiep_theo_2.png", timeout=10)
        time.sleep(2)

        width, height = device.window_size()
        self._tap_by_image(device_id, "o_nhap_mota.png", timeout=6, fallback=(int(width * 0.6), int(height * 0.12)))
        time.sleep(2)

        upd_status("✍️ Đang nhập caption...")
        self._set_device_text(device, caption_text)
        time.sleep(2)
        self._tap_by_image(device_id, "nut_dong_y.png", timeout=5, fallback=(int(width * 0.90), int(height * 0.07)))
        time.sleep(2)

        width, height = device.window_size()
        fallback_add_product = (int(width * 0.72), int(height * (0.360 if (height / width) < 1.8 else 0.355)))
        self._tap_by_image(device_id, "nut_them_san_pham.png", conf=0.75, timeout=8, fallback=fallback_add_product)
        time.sleep(4)

        self._tap_by_image(device_id, "icon_link.png", timeout=10)
        time.sleep(2)

        upd_status("🔗 Đang nhập link sản phẩm...")
        try:
            self._tap_by_image(device_id, "only_link.png", timeout=3)
            time.sleep(1)
            adb_tap(int(width * 0.5), int(height * 0.35))
        except Exception:
            try:
                self._tap_by_image(device_id, "nut_xoa_tat_ca.png", timeout=5, fallback=(int(width * 0.9), int(height * 0.25)))
            except Exception:
                pass
            time.sleep(1)
            adb_tap(int(width * 0.5), int(height * 0.35))

        time.sleep(1)
        self._set_device_text(device, link_text)
        time.sleep(2)
        self._tap_by_image(device_id, "nut_nhap.png", timeout=10)
        time.sleep(4)

        try:
            self._tap_by_image(device_id, "chon_tat_ca.png", timeout=8)
            time.sleep(2)
        except Exception as exc:
            raise LinkImportError(str(exc))

        self._tap_by_image(device_id, "nut_them_sp_cuoi.png", timeout=8, fallback=(int(width * 0.8), int(height * 0.95)))
        time.sleep(2)
        self._tap_by_image(device_id, "nut_dang_cuoi.png", timeout=8, fallback=(int(width * 0.5), int(height * 0.95)))
        time.sleep(2)

        toast_msg = ""
        try:
            toast_msg = device.toast.get_message(1.0, default="")
        except Exception:
            pass
        is_limit = "too many videos" in toast_msg.lower() or device(textContains="too many videos").exists or device(textContains="Post too many").exists
        if is_limit:
            raise LimitReachedError("Shopee báo đạt giới hạn đăng")

    def _tap_by_image(self, device_id, image_name, conf=None, timeout=10, fallback=None):
        image_dir = self.get_phone_image_dir()
        base_name, extension = os.path.splitext(image_name)
        possible_files = [image_name] + [f"{base_name}_{idx}{extension}" for idx in range(2, 6)]
        valid_paths = [os.path.join(image_dir, name) for name in possible_files if os.path.exists(os.path.join(image_dir, name))]
        if not valid_paths:
            if fallback:
                self._adb_tap(device_id, fallback[0], fallback[1])
                return True
            raise FileNotFoundError(f"Thiếu ảnh mẫu {image_name}")

        adb_cmd = self.get_adb_path()
        threshold = float(conf if conf is not None else self.var_match_threshold.get())
        start_time = time.time()
        temp_screen = os.path.join(BASE_PATH, f"temp_cv2_{device_id.replace(':', '_').replace('.', '_')}.png")

        while time.time() - start_time < timeout:
            if not self.is_farming:
                raise RuntimeError("Dừng auto")
            try:
                with open(temp_screen, "wb") as handle:
                    subprocess.run([adb_cmd, "-s", device_id, "exec-out", "screencap", "-p"], stdout=handle, check=False)
                if not os.path.exists(temp_screen) or os.path.getsize(temp_screen) == 0:
                    time.sleep(1)
                    continue

                screen_img = cv2.imread(temp_screen)
                if screen_img is None:
                    time.sleep(1)
                    continue

                for image_path in valid_paths:
                    template = cv2.imread(image_path)
                    if template is None:
                        continue
                    result = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val >= threshold:
                        height, width = template.shape[:2]
                        cx = max_loc[0] + width // 2
                        cy = max_loc[1] + height // 2
                        self._adb_tap(device_id, cx, cy)
                        return True
            finally:
                if os.path.exists(temp_screen):
                    try:
                        os.remove(temp_screen)
                    except Exception:
                        pass
            time.sleep(1)

        if fallback:
            self._adb_tap(device_id, fallback[0], fallback[1])
            return True
        raise RuntimeError(f"Không tìm thấy ảnh {image_name}")

    def _adb_tap(self, device_id, x, y):
        adb_cmd = self.get_adb_path()
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        subprocess.run([adb_cmd, "-s", device_id, "shell", "input", "tap", str(x), str(y)], creationflags=creationflags)
        time.sleep(float(self.var_click_delay.get()))

    def _set_device_text(self, device, text_value):
        try:
            device.set_fastinput_ime(True)
            device.send_keys(text_value, clear=False)
        finally:
            try:
                device.set_fastinput_ime(False)
            except Exception:
                pass

    def _force_stop_shopee(self, adb_cmd, device_id, creationflags):
        subprocess.run([adb_cmd, "-s", device_id, "shell", "am", "force-stop", "com.shopee.vn"], creationflags=creationflags)

    def _join_remote_path(self, remote_dir, file_name):
        return f"{remote_dir.rstrip('/')}/{file_name}"

    def _normalize_device_orientation(self, device):
        try:
            device.freeze_rotation(True)
        except Exception:
            pass

        try:
            orientation = device.orientation
        except Exception:
            orientation = ""

        if orientation not in ("natural", "n", 0):
            try:
                device.set_orientation("n")
                time.sleep(1)
            except Exception:
                pass

    def _increment_job_retry(self, device_id, video_name):
        retry_key = (str(device_id or ""), str(video_name or ""))
        with self.job_retry_lock:
            retry_count = self.job_retry_counts.get(retry_key, 0) + 1
            self.job_retry_counts[retry_key] = retry_count
            return retry_count

    def _clear_job_retry(self, device_id, video_name):
        retry_key = (str(device_id or ""), str(video_name or ""))
        with self.job_retry_lock:
            self.job_retry_counts.pop(retry_key, None)

    def _get_remote_video_dirs(self, remote_dir=None, clear_all_dirs=True):
        ordered_dirs = []
        candidates = [remote_dir] if not clear_all_dirs else [remote_dir, *self.REMOTE_VIDEO_DIRS]
        for candidate in candidates:
            normalized = str(candidate or "").strip().rstrip("/")
            if normalized and normalized not in ordered_dirs:
                ordered_dirs.append(normalized)
        return ordered_dirs

    def _build_remote_clear_script(self, remote_dirs, clear_all_dirs=True):
        find_patterns = []
        for ext in self.REMOTE_VIDEO_EXTENSIONS:
            find_patterns.append(f'-iname "*.{ext}"')
            find_patterns.append(f'-iname "*.{ext.upper()}"')

        script_parts = []
        for remote_path in remote_dirs:
            patterns = []
            for ext in self.REMOTE_VIDEO_EXTENSIONS:
                patterns.append(f'"{remote_path}"/*.{ext}')
                patterns.append(f'"{remote_path}"/*.{ext.upper()}')
                patterns.append(f'"{remote_path}"/*/*.{ext}')
                patterns.append(f'"{remote_path}"/*/*.{ext.upper()}')
            script_parts.append("rm -f " + " ".join(patterns))

        fallback_script = " ; ".join(script_parts)
        if not clear_all_dirs:
            return fallback_script

        find_expr = " -o ".join(find_patterns)
        return (
            "if command -v find >/dev/null 2>&1; then "
            f"find /sdcard -type f \\( {find_expr} \\) -delete ; "
            "else "
            f"{fallback_script} ; "
            "fi"
        )

    def _clear_remote_videos(self, adb_cmd, device_id, creationflags, remote_dir=None, clear_all_dirs=True):
        remote_dirs = self._get_remote_video_dirs(remote_dir=remote_dir, clear_all_dirs=clear_all_dirs)
        if not remote_dirs:
            return

        cleanup_script = self._build_remote_clear_script(remote_dirs, clear_all_dirs=clear_all_dirs)
        subprocess.run(
            [adb_cmd, "-s", device_id, "shell", "sh", "-c", cleanup_script],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=creationflags,
            check=False,
        )

        for remote_path in remote_dirs:
            subprocess.run(
                [
                    adb_cmd,
                    "-s",
                    device_id,
                    "shell",
                    "am",
                    "broadcast",
                    "-a",
                    "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                    "-d",
                    f"file://{remote_path}",
                ],
                creationflags=creationflags,
                check=False,
            )

    def _broadcast_media_scan(self, adb_cmd, device_id, remote_path, creationflags):
        normalized_path = str(remote_path or "").strip()
        if not normalized_path:
            return

        subprocess.run(
            [
                adb_cmd,
                "-s",
                device_id,
                "shell",
                "am",
                "broadcast",
                "-a",
                "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d",
                f"file://{normalized_path}",
            ],
            creationflags=creationflags,
            check=False,
        )
        subprocess.run(
            [
                adb_cmd,
                "-s",
                device_id,
                "shell",
                "sh",
                "-c",
                f'if command -v cmd >/dev/null 2>&1; then cmd media rescan "{normalized_path}" >/dev/null 2>&1; fi',
            ],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
            check=False,
        )

    def _cleanup_remote_file(self, adb_cmd, device_id, remote_path, creationflags):
        try:
            subprocess.run(
                [adb_cmd, "-s", device_id, "shell", "sh", "-c", f'rm -f "{remote_path}"'],
                creationflags=creationflags,
                check=False,
            )
            self._broadcast_media_scan(adb_cmd, device_id, remote_path, creationflags)
        except Exception:
            pass


class LinkImportError(Exception):
    pass


class LimitReachedError(Exception):
    pass
