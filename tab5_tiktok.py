import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import requests
from datetime import datetime
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed 

from tab5_modules.tiktok_uploader import TikTokUploader

# Import vũ khí hạt nhân
try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

class TikTokTab:
    def __init__(self, parent, main_app):
        self.parent = parent
        self.main_app = main_app
        self.uploader = None
        self.setup_ui()

    def setup_ui(self):
        # Tạo notebook (tabbed interface)
        notebook = ttk.Notebook(self.parent, width=900, height=700)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Tab 1: Download
        tab_download = tk.Frame(notebook, bg="#f4f6f9")
        notebook.add(tab_download, text="📥 Tải Video Từ TikTok", compound="left")
        self.setup_download_tab(tab_download)
        
        # Tab 2: Upload
        tab_upload = tk.Frame(notebook, bg="#f4f6f9")
        notebook.add(tab_upload, text="📤 Đăng Video Lên TikTok", compound="left")
        self.setup_upload_tab(tab_upload)

    def setup_download_tab(self, parent):
        """UI cho tab Download"""
        tk.Label(parent, text="🎵 MÁY HÚT TIKTOK (TÍCH HỢP YT-DLP)", font=("Arial", 14, "bold"), bg="#f4f6f9", fg="#2980b9").pack(pady=(20, 10))

        # --- KHUNG 1: NHẬP LINK ---
        input_fr = tk.LabelFrame(parent, text=" 1. Dán Danh Sách Link (Mỗi link 1 dòng) ", font=("Arial", 10, "bold"), bg="#ffffff", padx=15, pady=10)
        input_fr.pack(fill="x", padx=20, pady=5)

        self.txt_urls = tk.Text(input_fr, height=6, font=("Arial", 10), bg="#fdfdfd")
        self.txt_urls.pack(fill="x", pady=5)

        # --- KHUNG 2: CẤU HÌNH LUỒNG & CHỌN VŨ KHÍ ---
        config_fr = tk.Frame(parent, bg="#f4f6f9")
        config_fr.pack(fill="x", padx=20, pady=5)

        tk.Label(config_fr, text="Số luồng hút:", font=("Arial", 10, "bold"), bg="#f4f6f9").pack(side="left")
        self.spin_threads = tk.Spinbox(config_fr, from_=1, to=10, width=5, font=("Arial", 10, "bold"))
        self.spin_threads.insert(0, "5") 
        self.spin_threads.pack(side="left", padx=10)

        # TÙY CHỌN: CHỌN ĐỘNG CƠ TẢI
        self.use_ytdlp = tk.BooleanVar(value=HAS_YTDLP)
        chk_ytdlp = tk.Checkbutton(config_fr, text="🔥 Dùng lõi yt-dlp (Không bị giới hạn tốc độ)", variable=self.use_ytdlp, font=("Arial", 10, "bold"), bg="#f4f6f9", fg="#c0392b")
        chk_ytdlp.pack(side="left", padx=20)
        if not HAS_YTDLP:
            chk_ytdlp.config(state="disabled", text="❌ Lõi yt-dlp chưa cài (Hãy gõ: pip install yt-dlp)")

        # --- KHUNG 3: ĐIỀU KHIỂN & TRẠNG THÁI ---
        action_fr = tk.Frame(parent, bg="#f4f6f9")
        action_fr.pack(fill="x", padx=20, pady=5)

        self.btn_download = tk.Button(action_fr, text="📥 HÚT TOÀN BỘ VIDEO", bg="#27ae60", fg="white", font=("Arial", 12, "bold"), pady=8, command=self.start_download)
        self.btn_download.pack(fill="x", pady=(0, 10))

        # --- KHUNG 4: NHẬT KÝ ---
        log_fr = tk.LabelFrame(parent, text=" 2. Nhật Ký Hoạt Động ", font=("Arial", 10, "bold"), bg="#ffffff", padx=15, pady=10)
        log_fr.pack(fill="both", expand=True, padx=20, pady=5)

        self.txt_log_download = tk.Text(log_fr, bg="#1e272e", fg="#2ecc71", font=("Consolas", 10), state="disabled", height=10)
        self.txt_log_download.pack(fill="both", expand=True)

        bot_fr = tk.Frame(parent, bg="#f4f6f9")
        bot_fr.pack(fill="x", padx=20, pady=10)
        tk.Button(bot_fr, text="📂 Mở Thư Mục Chứa Video", bg="#34495e", fg="white", font=("Arial", 10, "bold"), command=self.open_download_folder).pack(side="right")

    def setup_upload_tab(self, parent):
        """UI cho tab Upload"""
        tk.Label(parent, text="🚀 ĐẠO DIỄN AI - ĐĂNG VIDEO LÊN TIKTOK TỰ ĐỘNG", font=("Arial", 14, "bold"), bg="#f4f6f9", fg="#e74c3c").pack(pady=(20, 10))

        # --- KHUNG 1: CHỌN VIDEO ---
        select_fr = tk.LabelFrame(parent, text=" 1. Chọn Video Để Đăng ", font=("Arial", 10, "bold"), bg="#ffffff", padx=15, pady=10)
        select_fr.pack(fill="x", padx=20, pady=5)

        btn_select_fr = tk.Frame(select_fr, bg="#ffffff")
        btn_select_fr.pack(fill="x", pady=5)
        
        tk.Button(btn_select_fr, text="📁 Chọn Từ Kho Video", bg="#3498db", fg="white", font=("Arial", 10, "bold"), command=self.select_videos_from_folder).pack(side="left", padx=5)
        tk.Button(btn_select_fr, text="➕ Thêm File", bg="#9b59b6", fg="white", font=("Arial", 10, "bold"), command=self.add_videos_manual).pack(side="left", padx=5)
        tk.Button(btn_select_fr, text="🗑️ Xóa Danh Sách", bg="#e74c3c", fg="white", font=("Arial", 10, "bold"), command=self.clear_video_list).pack(side="left", padx=5)

        self.listbox_videos = tk.Listbox(select_fr, height=5, font=("Arial", 9), bg="#fdfdfd")
        self.listbox_videos.pack(fill="both", expand=True, pady=5)
        self.video_files = []

        # --- KHUNG 2: TEMPLATE TEXT ---
        text_fr = tk.LabelFrame(parent, text=" 2. Mẫu Văn Bản (Caption) ", font=("Arial", 10, "bold"), bg="#ffffff", padx=15, pady=10)
        text_fr.pack(fill="both", expand=True, padx=20, pady=5)

        tk.Label(text_fr, text="📝 Tiêu đề (có thể dùng {filename}, {index}):", font=("Arial", 9, "bold"), bg="#ffffff").pack(anchor="w")
        self.entry_title = tk.Entry(text_fr, font=("Arial", 10), bg="#fdfdfd")
        self.entry_title.pack(fill="x", pady=5)
        self.entry_title.insert(0, "🎬 {filename} | #quochoai #viral")

        tk.Label(text_fr, text="📣 Mô tả thêm:", font=("Arial", 9, "bold"), bg="#ffffff").pack(anchor="w")
        self.txt_description = tk.Text(text_fr, height=4, font=("Arial", 9), bg="#fdfdfd")
        self.txt_description.pack(fill="both", expand=True, pady=5)
        self.txt_description.insert("1.0", "Video #{index} được tạo bởi AI Editor!\n\n🔥 Like + Follow + Share để ủng hộ kênh!")

        tk.Label(text_fr, text="#️⃣ Hashtag (cách nhau bằng space):", font=("Arial", 9, "bold"), bg="#ffffff").pack(anchor="w", pady=(10, 0))
        self.entry_hashtags = tk.Entry(text_fr, font=("Arial", 10), bg="#fdfdfd")
        self.entry_hashtags.pack(fill="x", pady=5)
        self.entry_hashtags.insert(0, "#quochoai #viral #trending #aieditor")

        # --- KHUNG 3: CẤU HÌNH & ĐIỀU KHIỂN ---
        config_fr = tk.LabelFrame(parent, text=" 3. Cấu Hình Upload ", font=("Arial", 10, "bold"), bg="#ffffff", padx=15, pady=10)
        config_fr.pack(fill="x", padx=20, pady=5)

        delay_fr = tk.Frame(config_fr, bg="#ffffff")
        delay_fr.pack(fill="x", pady=5)
        tk.Label(delay_fr, text="⏱️ Delay giữa các upload (giây):", font=("Arial", 9, "bold"), bg="#ffffff").pack(side="left")
        self.spin_delay = tk.Spinbox(delay_fr, from_=30, to=600, width=5, font=("Arial", 10, "bold"))
        self.spin_delay.insert(0, "180")
        self.spin_delay.pack(side="left", padx=10)
        tk.Label(delay_fr, text="(Chống spam, khuyến nghị 180-300s)", font=("Arial", 8), bg="#ffffff", fg="#7f8c8d").pack(side="left")

        self.chk_headless = tk.BooleanVar(value=False)
        tk.Checkbutton(config_fr, text="👻 Chế độ Headless (ẩn Chrome)", variable=self.chk_headless, font=("Arial", 9, "bold"), bg="#ffffff").pack(anchor="w", pady=5)

        # --- NƯỚC NẤU & NƯỚC RỬA CHÉN ---
        action_fr = tk.Frame(config_fr, bg="#ffffff")
        action_fr.pack(fill="x", pady=10)

        self.btn_login = tk.Button(action_fr, text="🔐 Đăng Nhập TikTok", bg="#27ae60", fg="white", font=("Arial", 11, "bold"), pady=8, command=self.tiktok_login)
        self.btn_login.pack(side="left", padx=5)

        self.btn_upload = tk.Button(action_fr, text="🚀 ĐĂNG TOÀN BỘ VIDEO", bg="#e74c3c", fg="white", font=("Arial", 11, "bold"), pady=8, command=self.start_upload_batch)
        self.btn_upload.pack(side="left", padx=5)

        # --- NHẬT KÝ ---
        log_fr = tk.LabelFrame(parent, text=" 4. Nhật Ký Upload ", font=("Arial", 10, "bold"), bg="#ffffff", padx=15, pady=10)
        log_fr.pack(fill="both", expand=True, padx=20, pady=5)

        self.txt_log_upload = tk.Text(log_fr, bg="#1e272e", fg="#f39c12", font=("Consolas", 9), state="disabled", height=8)
        self.txt_log_upload.pack(fill="both", expand=True)

    def select_videos_from_folder(self):
        """Chọn video từ thư mục Kho_Video_Xuat_Xuong"""
        default_path = os.path.join(self.main_app.config.get("app_base_path", os.getcwd()), "Workspace_Data", "Kho_Video_Xuat_Xuong")
        os.makedirs(default_path, exist_ok=True)
        
        folder = filedialog.askdirectory(initialdir=default_path, title="Chọn thư mục chứa video")
        if not folder:
            return
        
        videos = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(('.mp4', '.mov', '.avi'))]
        if not videos:
            messagebox.showwarning("Thông báo", f"Không tìm thấy video nào trong {folder}")
            return
        
        self.video_files = videos
        self.update_video_list()

    def add_videos_manual(self):
        """Thêm video từ file dialog"""
        files = filedialog.askopenfilenames(
            title="Chọn video",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv"), ("All files", "*.*")]
        )
        if files:
            self.video_files.extend(files)
            self.update_video_list()

    def update_video_list(self):
        """Cập nhật hiển thị danh sách video"""
        self.listbox_videos.delete(0, tk.END)
        for video in self.video_files:
            self.listbox_videos.insert(tk.END, os.path.basename(video))

    def clear_video_list(self):
        """Xóa danh sách video"""
        self.video_files = []
        self.update_video_list()

    def add_log_upload(self, msg):
        """Log cho tab upload"""
        self.main_app.root.after(0, self._insert_log_upload, msg)

    def _insert_log_upload(self, msg):
        """Insert log vào text widget"""
        self.txt_log_upload.config(state="normal")
        self.txt_log_upload.insert(tk.END, f"{msg}\n")
        self.txt_log_upload.see(tk.END)
        self.txt_log_upload.config(state="disabled")

    def tiktok_login(self):
        """Đăng nhập TikTok"""
        if not self.uploader:
            self.uploader = TikTokUploader(callback_log=self.add_log_upload)
        
        self.btn_login.config(state="disabled", text="⏳ Đang mở Chrome...")
        threading.Thread(target=self._login_thread, daemon=True).start()

    def _login_thread(self):
        """Xử lý login trong thread"""
        try:
            headless = self.chk_headless.get()
            if self.uploader.login(wait_manual=True):
                self.add_log_upload("✅ Đã đăng nhập thành công!")
                self.main_app.root.after(0, lambda: self.btn_login.config(state="normal", text="🔐 Đã Đăng Nhập", bg="#27ae60"))
            else:
                self.add_log_upload("❌ Login thất bại!")
                self.main_app.root.after(0, lambda: self.btn_login.config(state="normal", text="🔐 Đăng Nhập TikTok"))
        except Exception as e:
            self.add_log_upload(f"❌ Lỗi: {e}")
            self.main_app.root.after(0, lambda: self.btn_login.config(state="normal", text="🔐 Đăng Nhập TikTok"))

    def start_upload_batch(self):
        """Bắt đầu upload batch"""
        if not self.video_files:
            messagebox.showwarning("Chú ý", "Vui lòng chọn video để đăng!")
            return
        
        if not self.uploader or not self.uploader.is_logged_in:
            messagebox.showwarning("Chú ý", "Vui lòng đăng nhập TikTok trước!")
            return
        
        title_template = self.entry_title.get().strip()
        description = self.txt_description.get("1.0", tk.END).strip()
        hashtags = self.entry_hashtags.get().strip()
        
        try:
            delay = int(self.spin_delay.get())
        except:
            delay = 180
        
        self.btn_upload.config(state="disabled", text=f"⏳ ĐANG ĐĂNG {len(self.video_files)} VIDEO...")
        self.add_log_upload(f"\n{'='*60}")
        self.add_log_upload(f"🎬 CHIẾN DỊCH UPLOAD BẮTĐẦU!")
        self.add_log_upload(f"{'='*60}\n")
        
        threading.Thread(
            target=self.uploader.upload_batch,
            args=(self.video_files, title_template, description, hashtags, delay),
            daemon=True
        ).start()
        
        threading.Thread(target=self._monitor_upload, daemon=True).start()

    def _monitor_upload(self):
        """Monitor tình trạng upload"""
        while self.uploader and self.uploader.uploading:
            time.sleep(1)
        
        self.main_app.root.after(0, lambda: self.btn_upload.config(state="normal", text="🚀 ĐĂNG TOÀN BỘ VIDEO"))

    def add_log(self, msg):
        """Log cho tab download (cũ)"""
        self.main_app.root.after(0, self._insert_log, msg)

    def _insert_log(self, msg):
        """Insert log vào text widget download"""
        self.txt_log_download.config(state="normal")
        self.txt_log_download.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.txt_log_download.see(tk.END)
        self.txt_log_download.config(state="disabled")

    def clean_filename(self, title):
        clean = re.sub(r'[\\/*?:"<>|]', "", title)
        return clean[:50].strip()

    def start_download(self):
        raw_urls = self.txt_urls.get("1.0", tk.END).splitlines()
        valid_urls = [u.strip() for u in raw_urls if "tiktok.com" in u.strip()]

        if not valid_urls:
            return messagebox.showwarning("Chú ý", "Bác chưa dán link hợp lệ nào (mỗi link 1 dòng nhé)!")

        try:
            threads = int(self.spin_threads.get())
            if threads > 20: threads = 20 
        except:
            threads = 5

        engine_name = "yt-dlp" if self.use_ytdlp.get() else "TikWM"
        self.btn_download.config(state="disabled", text=f"⏳ ĐANG HÚT {len(valid_urls)} VIDEO BẰNG {engine_name.upper()}...", bg="#7f8c8d")
        
        threading.Thread(target=self._process_batch, args=(valid_urls, threads), daemon=True).start()

    def _process_batch(self, urls, max_workers):
        self.add_log(f"🚀 Bắt đầu chiến dịch hút {len(urls)} video với {max_workers} luồng song song!")
        
        success_count = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(self._download_single, url, index): url for index, url in enumerate(urls)}
            
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    res = future.result()
                    if res: success_count += 1
                except Exception as e:
                    self.add_log(f"❌ Lỗi ngoài ý muốn với link {url[:30]}... : {e}")

        self.add_log(f"🎉 CHIẾN DỊCH HOÀN TẤT! Đã vác về kho {success_count}/{len(urls)} video.")
        self.main_app.root.after(0, lambda: self.btn_download.config(state="normal", text="📥 HÚT TOÀN BỘ VIDEO", bg="#27ae60"))

    def _download_single(self, url, index):
        save_dir = os.path.join(os.getcwd(), "TikTok_Downloads")
        os.makedirs(save_dir, exist_ok=True)
        
        is_success = False

        if self.use_ytdlp.get():
            try:
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]', 
                    'merge_output_format': 'mp4',
                    'outtmpl': os.path.join(save_dir, '%(title).50s_[%(id)s].%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                    'nocheckcertificate': True
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info.get('vcodec') == 'none' and not info.get('requested_formats'):
                        raise Exception("Giỏ Hàng/Slideshow")
                        
                    ydl.download([url])
                    downloaded_file = ydl.prepare_filename(info)
                    
                self.add_log(f"✅ XONG (yt-dlp): {os.path.basename(downloaded_file)}")
                return True
            except Exception:
                self.add_log(f"⚠️ [Bẻ Lái] yt-dlp đụng Giỏ Hàng, đẩy link sang TikWM: {url[:20]}...")
                is_success = False

        if not is_success:
            time.sleep(index * 1.5)
            
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    api_url = "https://www.tikwm.com/api/"
                    payload = {"url": url, "count": 12, "cursor": 0, "web": 1, "hd": 1}
                    
                    res = requests.post(api_url, data=payload, timeout=20) 
                    
                    if res.status_code != 200:
                        raise Exception("Server TikWM ngâm kết nối.")
                    
                    data = res.json()
                    if data.get("code") != 0:
                        error_msg = data.get("msg", "Link sai hoặc video riêng tư.")
                        raise Exception(error_msg)

                    vid_data = data.get("data", {})
                    play_url = vid_data.get("play")
                    title = vid_data.get("title", "TikTok_Video")
                    
                    if not play_url:
                        raise Exception("Không tìm thấy link MP4.")

                    if play_url.startswith("/"):
                        play_url = "https://www.tikwm.com" + play_url

                    safe_title = self.clean_filename(title)
                    if not safe_title: safe_title = f"Video_{datetime.now().strftime('%H%M%S_%f')}" 
                    
                    file_name = f"{safe_title}.mp4"
                    save_path = os.path.join(save_dir, file_name)

                    base_name, ext = os.path.splitext(file_name)
                    counter = 1
                    while os.path.exists(save_path):
                        file_name = f"{base_name}_{counter}{ext}"
                        save_path = os.path.join(save_dir, file_name)
                        counter += 1

                    vid_res = requests.get(play_url, stream=True, timeout=30)
                    if vid_res.status_code == 200:
                        with open(save_path, 'wb') as f:
                            for chunk in vid_res.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        
                        self.add_log(f"✅ XONG (TikWM): {file_name[:40]}...")
                        return True
                    else:
                        raise Exception(f"Lỗi kéo MP4 (HTTP {vid_res.status_code})")

                except Exception as e:
                    err_str = str(e)
                    if "1 request/second" in err_str and attempt < max_retries - 1:
                        self.add_log(f"⚠️ [Thử {attempt+1}/5] Nghẽn TikWM, nghỉ 3s rồi múc lại: {url[:25]}...")
                        time.sleep(3)
                        continue 
                    
                    self.add_log(f"❌ THẤT BẠI ({url[:30]}...): {e}")
                    return False
                
    def open_download_folder(self):
        save_dir = os.path.join(os.getcwd(), "TikTok_Downloads")
        os.makedirs(save_dir, exist_ok=True)
        os.startfile(save_dir)