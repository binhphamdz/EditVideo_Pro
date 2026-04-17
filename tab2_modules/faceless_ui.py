import os
import random
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import concurrent.futures
from datetime import datetime

from .ai_services import get_transcription, get_director_timeline
from .video_engine import render_faceless_video
from paths import BASE_PATH, resource_path

# ==========================================
# 1. TẠO Ổ KHÓA CHỐNG KẸT FILE JSON (CỰC QUAN TRỌNG)
# ==========================================
json_save_lock = threading.Lock()

class FacelessTab:
    def __init__(self, parent, main_app):
        self.parent = parent
        self.main_app = main_app
        self.completed_count = 0
        self.setup_ui()

    def setup_ui(self):
        top_container = tk.Frame(self.parent, bg="#f4f6f9")
        top_container.pack(fill="x", padx=10, pady=5)

        # CỘT TRÁI
        top_frame = tk.LabelFrame(top_container, text=" 1. Cấu Hình & API ", font=("Arial", 11, "bold"), bg="#ffffff", padx=15, pady=10)
        top_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        fr_row1 = tk.Frame(top_frame, bg="#ffffff")
        fr_row1.pack(fill="x", pady=5)
        tk.Label(fr_row1, text="Chọn Project:", bg="#ffffff", font=("Arial", 9, "bold")).pack(side="left")
        self.combo_proj = ttk.Combobox(fr_row1, state="readonly", width=35, font=("Arial", 10))
        self.combo_proj.pack(side="left", padx=5)
        self.combo_proj.bind("<<ComboboxSelected>>", self.on_project_select)

        # [MỚI] CONTAINER CHỨA VOICE, TRANSITIONS, TỐC ĐỘ NẰM NGANG
        fr_voice_trans_container = tk.Frame(top_frame, bg="#ffffff")
        fr_voice_trans_container.pack(fill="both", expand=True, pady=5)

        # ===== TRÁI: CHỌN VOICE =====
        fr_voice = tk.LabelFrame(fr_voice_trans_container, text="Chọn Voice (Ctrl):", bg="#ffffff", font=("Arial", 9, "bold"), padx=5, pady=5)
        fr_voice.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        self.lst_voices = tk.Listbox(fr_voice, selectmode=tk.MULTIPLE, height=6, width=22, font=("Arial", 10), exportselection=False)
        scroll_voice = ttk.Scrollbar(fr_voice, orient="vertical", command=self.lst_voices.yview)
        self.lst_voices.configure(yscrollcommand=scroll_voice.set)
        self.lst_voices.pack(side="left", fill="both", expand=True)
        scroll_voice.pack(side="left", fill="y")

        # ===== GIỮA: CHỌN HIỆU ỨNG CHUYỂN CẢNH =====
        fr_trans_container = tk.LabelFrame(fr_voice_trans_container, text="Chọn Hiệu Ứng (Ctrl):", bg="#ffffff", font=("Arial", 9, "bold"), padx=5, pady=5)
        fr_trans_container.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # Danh sách hiệu ứng với mô tả
        self.transitions = {
            "fade": "⬜ Mờ dần (Fade)",
            "slide_left": "⬅️ Trượt Trái",
            "slide_right": "➡️ Trượt Phải",
            "slide_up": "⬆️ Trượt Lên",
            "slide_down": "⬇️ Trượt Xuống",
            "wipe_left": "⬅️ Quét Trái",
            "wipe_right": "➡️ Quét Phải",
            "hlslice": "🔀 Vụt Ngang (TikTok)",
            "vsplit": "🔀 Vụt Dọc (TikTok)",
            "zoom_in": "🔍 Phóng To",
            "zoom_out": "🔍 Thu Nhỏ",
            "diagonal": "↗️ Chéo",
            "cross_fade": "✨ Mờ Chéo",
        }
        
        self.lst_trans = tk.Listbox(fr_trans_container, selectmode=tk.MULTIPLE, height=6, width=20, font=("Arial", 9), exportselection=False)
        for trans_key, trans_display in self.transitions.items():
            self.lst_trans.insert(tk.END, trans_display)
        
        # Load saved transitions
        saved_trans = self.main_app.config.get("selected_transitions", ["fade"])
        for idx, (trans_key, trans_display) in enumerate(self.transitions.items()):
            if trans_key in saved_trans:
                self.lst_trans.selection_set(idx)
        
        scroll_trans = ttk.Scrollbar(fr_trans_container, orient="vertical", command=self.lst_trans.yview)
        self.lst_trans.configure(yscrollcommand=scroll_trans.set)
        self.lst_trans.pack(side="left", fill="both", expand=True)
        scroll_trans.pack(side="left", fill="y")
        
        # Gắn auto-save cho transitions
        self.lst_trans.bind("<<ListboxSelect>>", self._save_selected_transitions)
        
        # ===== PHẢI: SLIDER TỐC ĐỘ CHUYỂN CẢNH =====
        fr_trans_speed = tk.LabelFrame(fr_voice_trans_container, text="Tốc Độ (s):", bg="#ffffff", font=("Arial", 9, "bold"), padx=5, pady=5)
        fr_trans_speed.pack(side="left", fill="both", padx=(0, 0))
        
        self.scale_trans_dur = tk.Scale(fr_trans_speed, from_=0.3, to=2.0, resolution=0.1, orient="vertical", bg="#ffffff", length=180)
        self.scale_trans_dur.set(self.main_app.config.get("trans_duration", 0.5))
        self.scale_trans_dur.pack(fill="both", expand=True)
        self.scale_trans_dur.bind("<ButtonRelease-1>", self._save_config_auto)
        
        # Label hiển thị giá trị hiện tại
        self.lbl_trans_dur = tk.Label(fr_trans_speed, text=f"{self.scale_trans_dur.get():.1f}s", bg="#ffffff", font=("Arial", 10, "bold"), fg="#c0392b")
        self.lbl_trans_dur.pack(pady=(5, 0))
        
        # Update label khi slider thay đổi
        def update_trans_dur_label(val):
            self.lbl_trans_dur.config(text=f"{float(val):.1f}s")
        
        self.scale_trans_dur.config(command=update_trans_dur_label)

        fr_row2 = tk.Frame(top_frame, bg="#ffffff")
        fr_row2.pack(fill="x", pady=5)
        tk.Label(fr_row2, text="Groq Key:", bg="#ffffff", font=("Arial", 9)).pack(side="left")
        self.ent_groq = tk.Entry(fr_row2, width=25)
        self.ent_groq.insert(0, self.main_app.config.get("groq_key", ""))
        self.ent_groq.pack(side="left", padx=5)
        tk.Label(fr_row2, text="Kie Key:", bg="#ffffff", font=("Arial", 9)).pack(side="left", padx=(10, 5))
        self.ent_kie = tk.Entry(fr_row2, width=25)
        self.ent_kie.insert(0, self.main_app.config.get("kie_key", ""))
        self.ent_kie.pack(side="left", padx=5)

        fr_row3 = tk.Frame(top_frame, bg="#ffffff")
        fr_row3.pack(fill="x", pady=5)
        tk.Label(fr_row3, text="Font Bìa:", bg="#ffffff", font=("Arial", 9, "bold")).pack(side="left")
        self.ent_font = tk.Entry(fr_row3, width=25)
        self.ent_font.insert(0, self.main_app.config.get("font_path", ""))
        self.ent_font.pack(side="left", padx=5)
        tk.Button(fr_row3, text="📂 Chọn Font", bg="#3498db", fg="white", font=("Arial", 8, "bold"), command=self.pick_font).pack(side="left")

        fr_row_srt = tk.Frame(top_frame, bg="#ffffff")
        fr_row_srt.pack(fill="x", pady=5)
        tk.Label(fr_row_srt, text="Bóc Băng Bằng:", bg="#ffffff", font=("Arial", 9, "bold"), fg="#8e44ad").pack(side="left")
        self.boc_bang_mode = tk.StringVar(value=self.main_app.config.get("boc_bang_mode", "groq"))
        tk.Radiobutton(fr_row_srt, text="Groq (Nhanh)", variable=self.boc_bang_mode, value="groq", bg="#ffffff").pack(side="left", padx=5)
        tk.Radiobutton(fr_row_srt, text="OhFree (Chuẩn)", variable=self.boc_bang_mode, value="ohfree", bg="#ffffff").pack(side="left", padx=5)

        fr_row_thread = tk.Frame(top_frame, bg="#ffffff")
        fr_row_thread.pack(fill="x", pady=5)
        tk.Label(fr_row_thread, text="Số Luồng:", bg="#ffffff", font=("Arial", 9, "bold"), fg="#c0392b").pack(side="left")
        self.spin_threads = ttk.Spinbox(fr_row_thread, from_=1, to=5, width=5, font=("Arial", 10, "bold"))
        self.spin_threads.set(self.main_app.config.get("threads", 2))
        self.spin_threads.pack(side="left", padx=5)

        # CỘT PHẢI
        adj_frame = tk.LabelFrame(top_container, text=" ⚙️ Tùy Chỉnh ", font=("Arial", 11, "bold"), bg="#ffffff", padx=15, pady=10)
        adj_frame.pack(side="right", fill="y", padx=(5, 0))
        tk.Label(adj_frame, text="Âm lượng Broll (%):", bg="#ffffff", font=("Arial", 9, "bold"), fg="#27ae60").pack(anchor="w", pady=(2, 2))
        self.scale_broll_vol = tk.Scale(adj_frame, from_=0, to=100, resolution=5, orient="horizontal", bg="#ffffff", length=200)
        self.scale_broll_vol.set(self.main_app.config.get("broll_vol", 30))
        self.scale_broll_vol.pack(anchor="w")

        tk.Label(adj_frame, text="Tốc độ Video (x):", bg="#ffffff", font=("Arial", 9, "bold")).pack(anchor="w", pady=(0, 2))
        self.scale_speed = tk.Scale(adj_frame, from_=0.5, to=3.0, resolution=0.1, orient="horizontal", bg="#ffffff", length=200)
        self.scale_speed.set(self.main_app.config.get("video_speed", 1.0))
        self.scale_speed.pack(anchor="w")
        
        tk.Label(adj_frame, text="Max Auto Speed:", bg="#ffffff", font=("Arial", 9, "bold")).pack(anchor="w", pady=(2, 2))
        self.scale_auto_speed = tk.Scale(adj_frame, from_=1.0, to=3.0, resolution=0.1, orient="horizontal", bg="#ffffff", length=200)
        self.scale_auto_speed.set(self.main_app.config.get("auto_speed_max", 1.4))
        self.scale_auto_speed.pack(anchor="w")

        tk.Label(adj_frame, text="Sáng (1.0 = Gốc):", bg="#ffffff", font=("Arial", 9, "bold")).pack(anchor="w", pady=(2, 2))
        self.scale_bright = tk.Scale(adj_frame, from_=0.5, to=2.0, resolution=0.1, orient="horizontal", bg="#ffffff", length=200)
        self.scale_bright.set(self.main_app.config.get("video_bright", 1.0))
        self.scale_bright.pack(anchor="w")

        self.use_trans = tk.BooleanVar(value=self.main_app.config.get("use_trans", True))
        tk.Checkbutton(adj_frame, text="Hiệu ứng Slide", variable=self.use_trans, bg="#ffffff").pack(anchor="w", pady=(5, 0))

        self.use_sfx = tk.BooleanVar(value=self.main_app.config.get("use_sfx", True))
        tk.Checkbutton(adj_frame, text="Âm chuyển cảnh", variable=self.use_sfx, bg="#ffffff").pack(anchor="w")

        # [MỚI] Gắn auto-save vào các slider và checkbox
        self.scale_broll_vol.bind("<ButtonRelease-1>", self._save_config_auto)
        self.scale_speed.bind("<ButtonRelease-1>", self._save_config_auto)
        self.scale_auto_speed.bind("<ButtonRelease-1>", self._save_config_auto)
        self.scale_bright.bind("<ButtonRelease-1>", self._save_config_auto)
        self.use_trans.trace_add("write", self._save_config_auto)
        self.use_sfx.trace_add("write", self._save_config_auto)
        self.ent_groq.bind("<KeyRelease>", self._save_config_auto)
        self.ent_kie.bind("<KeyRelease>", self._save_config_auto)
        self.ent_font.bind("<KeyRelease>", self._save_config_auto)
        self.spin_threads.bind("<KeyRelease>", self._save_config_auto)
        self.boc_bang_mode.trace_add("write", self._save_config_auto)

        # LOG VÀ NÚT RENDER
        mid_frame = tk.LabelFrame(self.parent, text=" 2. Log Tiến Trình ", font=("Arial", 11, "bold"), bg="#ffffff", padx=15, pady=5)
        mid_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.txt_log = tk.Text(mid_frame, bg="#1e272e", fg="#2ecc71", font=("Consolas", 10), state="disabled")
        self.txt_log.pack(fill="both", expand=True, pady=5)

        bot_frame = tk.Frame(self.parent, bg="#f4f6f9")
        bot_frame.pack(fill="x", padx=10, pady=5)
        self.btn_run_batch = tk.Button(bot_frame, text="🚀 BẤM RENDER (ĐA LUỒNG)", bg="#c0392b", fg="white", font=("Arial", 14, "bold"), pady=10, command=self.start_batch_process)
        self.btn_run_batch.pack(fill="x")

    def _save_config_auto(self, event=None):
        """[MỚI] Tự động lưu config khi bất kỳ setting nào thay đổi"""
        try:
            self.main_app.config["broll_vol"] = self.scale_broll_vol.get()
            self.main_app.config["video_speed"] = self.scale_speed.get()
            self.main_app.config["auto_speed_max"] = self.scale_auto_speed.get()
            self.main_app.config["video_bright"] = self.scale_bright.get()
            self.main_app.config["use_trans"] = self.use_trans.get()
            self.main_app.config["use_sfx"] = self.use_sfx.get()
            self.main_app.config["groq_key"] = self.ent_groq.get().strip()
            self.main_app.config["kie_key"] = self.ent_kie.get().strip()
            self.main_app.config["font_path"] = self.ent_font.get().strip()
            self.main_app.config["boc_bang_mode"] = self.boc_bang_mode.get()
            self.main_app.config["trans_duration"] = self.scale_trans_dur.get()  # [MỚI] Lưu tốc độ chuyển cảnh
            try:
                self.main_app.config["threads"] = int(self.spin_threads.get())
            except ValueError:
                pass
            self.main_app.save_config()
        except Exception as e:
            print(f"⚠️ Lỗi auto-save config: {e}")

    def _update_broll_stats(self, pid, timeline, voice_name):
        """[MỚI] Cộng usage_count cho các video đã dùng & refresh tab BRoll"""
        try:
            with json_save_lock:
                project_data = self.main_app.get_project_data(pid)
                total_vids_updated = 0
                
                for row in timeline:
                    # Lấy MẢNG video từ timeline
                    vid_names = row.get("video_files", [])
                    
                    # Backcompat: Hỗ trợ key cũ 'video_file' (lẻ)
                    if "video_file" in row and row.get("video_file"):
                        single_vid = row["video_file"]
                        if isinstance(single_vid, str) and single_vid not in vid_names:
                            vid_names.append(single_vid)
                    
                    # Cộng điểm cho từng video
                    for vid_name in vid_names:
                        if vid_name and vid_name in project_data.get('videos', {}):
                            current_usage = project_data['videos'][vid_name].get('usage_count', 0)
                            project_data['videos'][vid_name]['usage_count'] = current_usage + 1
                            total_vids_updated += 1
                
                # Lưu dữ liệu
                self.main_app.save_project_data(pid, project_data)
            
            # Log feedback
            if total_vids_updated > 0:
                self.add_log(f"✅ [{voice_name}] Cộng điểm ({total_vids_updated} video) & lưu thành công.")
            else:
                self.add_log(f"⚠️ [{voice_name}] Không cộng được video nào (timeline có thể không hợp lệ).")
            
            # Refresh tab BRoll (nếu đó là project đang xem)
            if self.main_app.tab1.current_project_id == pid:
                self.main_app.root.after(0, lambda: self.main_app.tab1.render_video_list())
                self.add_log(f"🔄 [{voice_name}] Đang cập nhật giao diện BRoll...")
        
        except Exception as e:
            self.add_log(f"❌ Lỗi cập nhật điểm BRoll: {e}")
            print(f"❌ Lỗi _update_broll_stats: {e}")

    def update_combo_projects(self):
        proj_list = []
        self.pid_map = {}
        for pid, pdata in self.main_app.projects.items():
            if pdata.get('status', 'active') == 'active':
                name = pdata.get('name', 'Unknown')
                proj_list.append(name)
                self.pid_map[name] = pid
                
        self.combo_proj.config(values=proj_list)
        if proj_list: 
            self.combo_proj.current(0)
            self.on_project_select(None)

    def on_project_select(self, event):
        self.lst_voices.delete(0, tk.END)
        proj_name = self.combo_proj.get()
        if not proj_name: return
        voice_dir = os.path.join(self.main_app.get_proj_dir(self.pid_map[proj_name]), "Voices")
        if os.path.exists(voice_dir):
            for f in os.listdir(voice_dir):
                if f.lower().endswith(('.mp3', '.wav')): self.lst_voices.insert(tk.END, f)

    def _save_selected_transitions(self, event=None):
        """[MỚI] Lưu transitions đã chọn vào config"""
        selected_indices = self.lst_trans.curselection()
        selected_trans_keys = [list(self.transitions.keys())[i] for i in selected_indices]
        self.main_app.config["selected_transitions"] = selected_trans_keys if selected_trans_keys else ["fade"]
        self._save_config_auto()  # Gồi hàm auto-save

    def pick_font(self):
        f_path = filedialog.askopenfilename(title="Chọn Font", filetypes=[("Font Files", "*.ttf *.otf")])
        if f_path:
            self.ent_font.delete(0, tk.END)
            self.ent_font.insert(0, f_path)
            self.main_app.config["font_path"] = f_path
            self.main_app.save_config()

    def add_log(self, msg):
        self.main_app.root.after(0, self._insert_log, msg)

    def _insert_log(self, msg):
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    # ================= BOT VÀ RENDER =================
    def auto_render_from_bot(self, bot, chat_id):
        proj_name = self.combo_proj.get()
        if not proj_name: return bot.send_message(chat_id, "❌ Bác chưa chọn Project trên Tool!")
        pid = self.pid_map[proj_name]
        proj_dir = self.main_app.get_proj_dir(pid)
        voice_dir = os.path.join(proj_dir, "Voices")
        all_voices = [f for f in os.listdir(voice_dir) if f.lower().endswith(('.mp3', '.wav'))] if os.path.exists(voice_dir) else []
        if not all_voices: return bot.send_message(chat_id, "❌ Kho Voice trống!")

        import random
        random.shuffle(all_voices)

        self.main_app.config["app_base_path"] = BASE_PATH 

        bot.send_message(chat_id, f"🎬 ĐẠO DIỄN AI NHẬN LỆNH!\n📁 Project: {proj_name}\n🎙️ {len(all_voices)} video. Đang xào nấu...")
        threading.Thread(target=self._run_multithread_batch, args=(all_voices, proj_dir, proj_name, bot, chat_id), daemon=True).start()

    def start_batch_process(self):
        proj_name = self.combo_proj.get()
        selected_indices = self.lst_voices.curselection()
        selected_trans = self.lst_trans.curselection()  # [MỚI] Kiểm tra transitions
        
        if not proj_name or not selected_indices: 
            return messagebox.showwarning("Lỗi", "Vui lòng chọn Project và bôi đen Voice!")
        
        if not selected_trans:
            return messagebox.showwarning("Lỗi", "Vui lòng chọn ít nhất 1 Hiệu Ứng Chuyển Cảnh!")
        
        # [CẬP NHẬT] Gọi hàm auto-save để lưu toàn bộ config
        self._save_config_auto()
        self._save_selected_transitions()  # [MỚI] Lưu transitions
        self.main_app.config["app_base_path"] = BASE_PATH
        self.main_app.save_config()

        voices = [self.lst_voices.get(i) for i in selected_indices]
        import random
        random.shuffle(voices)

        proj_dir = self.main_app.get_proj_dir(self.pid_map[proj_name])
        
        self.btn_run_batch.config(state="disabled", text="⏳ ĐANG RENDER...")
        threading.Thread(target=self._run_multithread_batch, args=(voices, proj_dir, proj_name, None, None), daemon=True).start()

    def _run_multithread_batch(self, voices, proj_dir, proj_name, bot=None, chat_id=None):
        self.completed_count = 0
        num_threads = self.main_app.config.get("threads", 2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Truyền thêm tham số thời gian delay để chống kẹt
            futures = [executor.submit(self._process_single, v, proj_dir, proj_name) for v in voices]
            for future in concurrent.futures.as_completed(futures):
                try: future.result()
                except Exception as exc: self.add_log(f"❌ LUỒNG CRASH: {exc}")
        
        try:
            self.add_log("🧹 Đang dọn dẹp bộ nhớ FFmpeg ngầm...")
            os.system("taskkill /f /im ffmpeg-win-x86_64-v7.1.exe /T >nul 2>&1")
            os.system("taskkill /f /im ffmpeg.exe /T >nul 2>&1")
        except: pass
        
        self.add_log("=========================================")
        self.add_log(f"🎉 HOÀN TẤT! Thành công: {self.completed_count}/{len(voices)}.")
        self.main_app.root.after(0, lambda: self.btn_run_batch.config(state="normal", text="🚀 BẤM RENDER (ĐA LUỒNG)"))
        if bot and chat_id: bot.send_message(chat_id, f"🎉 Đã xuất xưởng {self.completed_count}/{len(voices)} video. Nhắn /icloud để nhận hàng!")
        
        try: self.main_app.tab4.load_excel_data()
        except: pass

    def _process_single(self, voice_name, proj_dir, proj_name):
        from main import GLOBAL_OUT_DIR, EXCEL_LOG_FILE 
        try:
            voice_path = os.path.join(proj_dir, "Voices", voice_name)
            out_file = os.path.join(GLOBAL_OUT_DIR, f"[{proj_name}] {os.path.splitext(voice_name)[0]}_{datetime.now().strftime('%H%M%S')}.mp4")
            
            pid = self.pid_map[proj_name]
            
            # 1. Bóc băng [CẬP NHẬT] Dùng cache từ Tab 1 nếu có sẵn
            try:
                # [MỚI] Cố gắng dùng cache từ Tab 1
                voice_text = self.main_app.tab1.get_voice_srt_or_extract(pid, voice_name, voice_path)
                self.add_log(f"[{voice_name}] ✅ Dùng SRT (cache hoặc extract mới)")
            except Exception as e:
                # Fallback: Nếu Tab 1 không có, extract trực tiếp
                self.add_log(f"[{voice_name}] ⚠️ Fallback extract: {str(e)[:50]}")
                voice_text = get_transcription(voice_path, voice_name, self.main_app.config.get("boc_bang_mode", "groq"), self.main_app.config, self.add_log)
            
            # =======================================================
            # [Ổ KHÓA SỐ 1] Ghi trí nhớ điểm Broll
            # =======================================================
            with json_save_lock:
                project_data = self.main_app.get_project_data(pid)
                broll_data = project_data.get('videos', {})
                
                broll_text = ""
                for v, info in broll_data.items():
                    dur = round(info.get('duration', 0) / self.main_app.config.get('video_speed', 1.0), 1)
                    desc = info.get('description', '')
                    usage = info.get('usage_count', 0) 
                    broll_text += f"- File: '{v}' (Dài {dur}s) | Đã dùng: {usage} lần | Mô tả: {desc}\n"

            # 3. Gọi AI Đạo Diễn (Gọi API thì không được bọc khóa vì nó tốn thời gian, để AI tự chạy song song)
            timeline = get_director_timeline(voice_text, broll_text, self.main_app.config, self.add_log, voice_name)
            
            # =======================================================
            # [Ổ KHÓA SỐ 2] Ghi điểm sử dụng Broll và Voice sau khi AI xử lý xong
            # =======================================================
            self._update_broll_stats(pid, timeline, voice_name)

            # 5. Render Video (Giai đoạn này mất thời gian nên chạy tự do ngoài ổ khóa)
            render_faceless_video(voice_name, voice_path, timeline, proj_dir, proj_name, self.main_app.config, out_file, GLOBAL_OUT_DIR, EXCEL_LOG_FILE, self.add_log, broll_data)

            self.completed_count += 1
            self.add_log(f"✅ THÀNH CÔNG: Đã lưu {voice_name}!")
            
            # =======================================================
            # [Ổ KHÓA SỐ 3] - BẢO VỆ TUYỆT ĐỐI SỐ LẦN DÙNG VOICE
            # =======================================================
            try:
                with json_save_lock:
                    fresh_p_data = self.main_app.get_project_data(pid) 
                    
                    if "voice_usage" not in fresh_p_data: 
                        fresh_p_data["voice_usage"] = {}
                        
                    fresh_p_data["voice_usage"][voice_name] = fresh_p_data["voice_usage"].get(voice_name, 0) + 1
                    self.main_app.save_project_data(pid, fresh_p_data)
                    
                self.main_app.root.after(0, self.main_app.tab1.load_voices)
            except Exception as e:
                self.add_log(f"⚠️ Lỗi cập nhật số lần dùng Voice: {e}")

        except Exception as e:
            self.add_log(f"❌ LỖI {voice_name}: {e}")