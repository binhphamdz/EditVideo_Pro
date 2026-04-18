import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import requests
import time
from datetime import datetime
from moviepy.editor import VideoFileClip

# Import Google Drive API (Dành cho OAuth2)
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class SubtitleTab:
    def __init__(self, parent, main_app):
        self.parent = parent
        self.main_app = main_app
        # ID Thư mục bác vừa gửi
        self.folder_id = "1K3iG8kCf8BEGYps9Q1pXWShuukGsEgas" 
        self.setup_ui()

    def setup_ui(self):
        container = tk.Frame(self.parent, bg="#f4f6f9")
        container.pack(fill="both", expand=True)

        tk.Label(container, text="📝 MÁY BÓC BĂNG & TẠO PHỤ ĐỀ (DRIVE OAUTH + OHFREE)", 
                 font=("Arial", 14, "bold"), bg="#f4f6f9", fg="#2980b9").pack(pady=(20, 10))

        # --- KHUNG 1: CẤU HÌNH API & COOKIE ---
        config_fr = tk.LabelFrame(container, text=" 1. Cấu Hình Chìa Khóa ", 
                                  font=("Arial", 10, "bold"), bg="#ffffff", padx=15, pady=10)
        config_fr.pack(fill="x", padx=20, pady=5)

        fr_row1 = tk.Frame(config_fr, bg="#ffffff")
        fr_row1.pack(fill="x", pady=5)
        tk.Label(fr_row1, text="File client_secret.json:", bg="#ffffff", font=("Arial", 9, "bold"), width=20, anchor="w").pack(side="left")
        self.ent_creds = tk.Entry(fr_row1, width=45)
        self.ent_creds.insert(0, self.main_app.config.get("client_secret", ""))
        self.ent_creds.pack(side="left", padx=5)
        tk.Button(fr_row1, text="📂 Chọn File", bg="#3498db", fg="white", font=("Arial", 8, "bold"), command=self.pick_creds).pack(side="left")

        fr_row2 = tk.Frame(config_fr, bg="#ffffff")
        fr_row2.pack(fill="x", pady=5)
        tk.Label(fr_row2, text="Cookie OhFree:", bg="#ffffff", font=("Arial", 9, "bold"), width=20, anchor="w").pack(side="left")
        self.ent_cookie = tk.Entry(fr_row2, width=55)
        self.ent_cookie.insert(0, self.main_app.config.get("ohfree_cookie", ""))
        self.ent_cookie.pack(side="left", padx=5)
        
        tk.Button(config_fr, text="💾 Lưu Cấu Hình", bg="#2c3e50", fg="white", 
                  font=("Arial", 8, "bold"), command=self.save_config).pack(anchor="e", pady=5)

        # --- KHUNG 2: CHỌN VIDEO ---
        input_fr = tk.LabelFrame(container, text=" 2. Chọn Video Cần Tách Phụ Đề ", 
                                 font=("Arial", 10, "bold"), bg="#ffffff", padx=15, pady=10)
        input_fr.pack(fill="x", padx=20, pady=5)

        fr_row3 = tk.Frame(input_fr, bg="#ffffff")
        fr_row3.pack(fill="x", pady=5)
        self.ent_video = tk.Entry(fr_row3, width=60, font=("Arial", 10))
        self.ent_video.pack(side="left", padx=5, fill="x", expand=True)
        tk.Button(fr_row3, text="🎬 Chọn Video", bg="#e67e22", fg="white", 
                  font=("Arial", 9, "bold"), command=self.pick_video).pack(side="right")

        # --- KHUNG 3: ĐIỀU KHIỂN & NHẬT KÝ ---
        action_fr = tk.Frame(container, bg="#f4f6f9")
        action_fr.pack(fill="x", padx=20, pady=5)

        self.btn_run = tk.Button(action_fr, text="🚀 BẮT ĐẦU XUẤT PHỤ ĐỀ (SRT)", 
                                 bg="#27ae60", fg="white", font=("Arial", 12, "bold"), 
                                 pady=10, command=self.start_process)
        self.btn_run.pack(fill="x", pady=(0, 10))

        log_fr = tk.LabelFrame(container, text=" 3. Nhật Ký Hoạt Động ", 
                               font=("Arial", 10, "bold"), bg="#ffffff", padx=15, pady=10)
        log_fr.pack(fill="both", expand=True, padx=20, pady=5)

        self.txt_log = tk.Text(log_fr, bg="#1e272e", fg="#2ecc71", font=("Consolas", 10), state="disabled", height=15)
        self.txt_log.pack(fill="both", expand=True)

    def pick_creds(self):
        f_path = filedialog.askopenfilename(title="Chọn file client_secret.json", filetypes=[("JSON Files", "*.json")])
        if f_path:
            self.ent_creds.delete(0, tk.END)
            self.ent_creds.insert(0, f_path)

    def pick_video(self):
        f_path = filedialog.askopenfilename(title="Chọn Video", filetypes=[("Video Files", "*.mp4 *.mov *.avi")])
        if f_path:
            self.ent_video.delete(0, tk.END)
            self.ent_video.insert(0, f_path)

    def save_config(self):
        self.main_app.config["client_secret"] = self.ent_creds.get().strip()
        self.main_app.config["ohfree_cookie"] = self.ent_cookie.get().strip()
        self.main_app.save_config()
        messagebox.showinfo("Thành công", "Đã lưu cấu hình API!")

    def add_log(self, msg):
        self.main_app.root.after(0, self._insert_log, msg)

    def _insert_log(self, msg):
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def format_srt_time(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def json_to_srt(self, words_list, output_path):
        self.add_log("✍️ Đang chuyển đổi dữ liệu AI sang định dạng SRT...")
        srt_content = ""
        chunk = []
        chunk_index = 1
        min_duration = 4.0
        max_duration = 6.0

        def flush_chunk():
            nonlocal srt_content, chunk, chunk_index
            if not chunk:
                return

            start_t = self.format_srt_time(chunk[0]['start_time'])
            end_t = self.format_srt_time(chunk[-1]['end_time'])
            text = " ".join(w['word'] for w in chunk)
            text = (text.replace(" ,", ",")
                        .replace(" .", ".")
                        .replace(" !", "!")
                        .replace(" ?", "?")
                        .replace(" :", ":")
                        .strip())

            srt_content += f"{chunk_index}\n{start_t} --> {end_t}\n{text}\n\n"
            chunk_index += 1
            chunk = []

        for word_data in words_list:
            word = word_data.get('word', '').strip()
            if word in ['<start>', '<end>', '']:
                continue

            entry = {
                'word': word,
                'start_time': float(word_data.get('start_time', 0.0)),
                'end_time': float(word_data.get('end_time', 0.0))
            }
            chunk.append(entry)

            chunk_duration = chunk[-1]['end_time'] - chunk[0]['start_time']
            is_sentence_end = any(word.endswith(p) for p in ['.', '?', '!', ';', ':'])
            is_soft_break = word.endswith(',')

            if chunk_duration >= max_duration or len(chunk) >= 16:
                flush_chunk()
            elif chunk_duration >= min_duration and (is_sentence_end or is_soft_break):
                flush_chunk()

        flush_chunk()

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        self.add_log(f"✅ HOÀN TẤT: File phụ đề nằm tại thư mục video gốc!")

    def get_drive_service(self, client_secret_path):
        """Hàm này dùng để mở trình duyệt xin quyền (Lần đầu tiên) và lưu token"""
        SCOPES = ['https://www.googleapis.com/auth/drive.file']
        creds = None
        # token.json lưu thẻ bài sau khi đăng nhập thành công
        token_path = os.path.join(os.getcwd(), 'token.json')
        
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                self.add_log("🔐 Lần đầu sử dụng: Tool sẽ mở trình duyệt để sếp đăng nhập Gmail...")
                flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
                
        return build('drive', 'v3', credentials=creds)

    def start_process(self):
        video_path = self.ent_video.get().strip()
        client_secret_path = self.ent_creds.get().strip()
        cookie = self.ent_cookie.get().strip()

        if not video_path or not os.path.exists(video_path):
            return messagebox.showerror("Lỗi", "Vui lòng chọn Video!")
        if not client_secret_path or not os.path.exists(client_secret_path):
            return messagebox.showerror("Lỗi", "Thiếu file client_secret.json!")
        if not cookie:
            return messagebox.showerror("Lỗi", "Chưa nhập Cookie OhFree!")

        self.save_config()
        self.btn_run.config(state="disabled", text="⏳ ĐANG CHẠY QUY TRÌNH TỰ ĐỘNG...", bg="#95a5a6")
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.config(state="disabled")

        threading.Thread(target=self._run_workflow, args=(video_path, client_secret_path, cookie), daemon=True).start()

    def _run_workflow(self, video_path, client_secret_path, cookie):
        temp_audio = os.path.join(os.path.dirname(video_path), f"temp_{int(time.time())}.mp3")
        srt_output = os.path.splitext(video_path)[0] + ".srt"
        file_id = None
        drive_service = None

        try:
            # 1. TÁCH AUDIO (MoviePy)
            self.add_log("🎬 Bước 1: Đang tách Audio từ Video gốc...")
            video = VideoFileClip(video_path)
            video.audio.write_audiofile(temp_audio, logger=None)
            video.close()

            # 2. XÁC THỰC OAUTH & UPLOAD LÊN DRIVE
            self.add_log("☁️ Bước 2: Đang bơm MP3 lên Google Drive (Bằng User thật)...")
            drive_service = self.get_drive_service(client_secret_path)

            file_metadata = {
                'name': f"voice_{datetime.now().strftime('%H%M%S')}.mp3",
                'parents': [self.folder_id]
            }
            media = MediaFileUpload(temp_audio, mimetype='audio/mpeg')
            
            file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            file_id = file.get('id')
            
            # Cấp quyền Anyone can read
            drive_service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
            
            drive_link = f"https://drive.google.com/file/d/{file_id}/view?usp=drive_link"
            self.add_log(f"✅ Đã có link Google Drive: {drive_link[:40]}...")

            # 3. GỌI API OHFREE (Dùng Multipart/Form-data)
            self.add_log("🚀 Bước 3: Đang bắn link cho OhFree bóc băng (Vượt Cloudflare)...")
            api_url = "https://tts.ohfree.me/api/mp3-to-text"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "*/*",
                "Cookie": cookie
            }
            files = {'url': (None, drive_link)}
            
            res = requests.post(api_url, headers=headers, files=files, timeout=300)
            
            if res.status_code == 200:
                data_res = res.json()
                if not data_res.get('success'):
                    raise Exception(f"OhFree báo lỗi: {data_res.get('message', 'Không rõ lý do')}")
                
                words_list = data_res.get('data', {}).get('words', [])
                if not words_list:
                    raise Exception("Không tìm thấy dữ liệu 'words' trong phản hồi!")
                
                # 4. CHUYỂN JSON SANG SRT
                self.json_to_srt(words_list, srt_output)
            else:
                self.add_log(f"❌ OhFree từ chối (HTTP {res.status_code})")
                raise Exception(res.text[:200])

        except Exception as e:
            self.add_log(f"❌ LỖI: {str(e)}")
            
        finally:
            self.add_log("🧹 Bước cuối: Đang dọn dẹp file rác...")
            if os.path.exists(temp_audio):
                try: os.remove(temp_audio)
                except: pass
                
            if file_id and drive_service:
                try:
                    drive_service.files().delete(fileId=file_id).execute()
                    self.add_log("✅ Đã xóa file rác trên Google Drive!")
                except: pass
                    
            self.add_log("🎉 HOÀN TẤT!")
            self.main_app.root.after(0, lambda: self.btn_run.config(state="normal", text="🚀 BẮT ĐẦU XUẤT PHỤ ĐỀ (SRT)", bg="#27ae60"))