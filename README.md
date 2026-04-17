# 🎬 EditVideo Pro - AI Video Editing & Auto Upload Tool

**EditVideo Pro** là công cụ tạo video faceless tự động bằng AI, hỗ trợ download video TikTok, tạo kịch bản, và đăng video lên TikTok hoàn toàn tự động.

## 🎯 Tính Năng Chính

### 📥 Tab 1: Tải Video Từ TikTok
- Tải hàng loạt video TikTok bằng **yt-dlp** hoặc **TikWM API**
- Hỗ trợ multi-threading (tải 5-10 video song song)
- Chống spam tự động (retry 5 lần)

### 🎨 Tab 2: Tạo Video Faceless (AI Đạo Diễn)
- **AI Script Generation**: Tạo kịch bản tự động từ từ khóa
- **Computer Vision**: Tự động chọn B-roll phù hợp
- **Speech Synthesis**: Tạo voice-over bằng AI
- **Auto Subtitles**: Thêm phụ đề tự động
- **Video Rendering**: Ghép nối & render video chuẩn TikTok

### 🚀 Tab 5: Đăng Video Lên TikTok (MỚI)
- **Đăng hàng loạt video** lên TikTok tự động
- **Template Caption**: Tùy chỉnh tiêu đề, mô tả, hashtag
- **Selenium Automation**: Tự động click, upload, chỉnh quyền riêng tư
- **Anti-Spam**: Delay giữa các upload (180-300s)
- **Web Headless**: Chế độ ẩn browser

### 🤖 Tab 8: Telegram Bot
- Điều khiển toàn bộ công cụ qua Telegram
- `/autobatch`: Bốc random voice & render tự động
- `/multimenu`: Chọn nhiều project & render
- `/icloud`: Đồng bộ video lên iCloud

---

## 📋 Cài Đặt

### 1. Clone Repository
```bash
git clone https://github.com/binhphamdz/EditVideo_Pro.git
cd EditVideo_Pro
```

### 2. Tạo Virtual Environment
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 3. Cài Dependencies
```bash
pip install -r requirements.txt
```

### 4. Setup Selenium ChromeDriver
```bash
# Download từ: https://chromedriver.chromium.org/
# Đặt trong thư mục project hoặc thêm vào PATH
```

### 5. Setup API Keys
Tạo file `.env` hoặc nhập trong ứng dụng:
- **Groq API Key**: https://console.groq.com
- **Google Credentials**: https://console.cloud.google.com (cho Drive & YouTube)
- **Telegram Bot Token**: https://t.me/BotFather

### 6. Chạy Ứng Dụng
```bash
python main.py
```

---

## 🚀 Hướng Dẫn Upload Video Lên TikTok

### Bước 1: Đăng Nhập
1. Mở Tab **📤 Đăng Video Lên TikTok**
2. Bấm **🔐 Đăng Nhập TikTok**
3. Cửa sổ Chrome sẽ mở, đăng nhập TikTok (hỗ trợ 2FA)
4. Nhấn `Enter` trong terminal sau khi login

### Bước 2: Chọn Video
- **📁 Chọn Từ Kho Video**: Tự động load từ `Workspace_Data/Kho_Video_Xuat_Xuong`
- **➕ Thêm File**: Chọn video thủ công
- **🗑️ Xóa Danh Sách**: Reset danh sách

### Bước 3: Cấu Hình Caption
```
📝 Tiêu đề:     🎬 {filename} | #quochoai #viral
📣 Mô tả:       Video #{index} được tạo bởi AI Editor!
#️⃣ Hashtag:    #quochoai #viral #trending #aieditor
```

**Template Variables:**
- `{filename}` - Tên file video (không .mp4)
- `{index}` - Số thứ tự video (1, 2, 3...)

### Bước 4: Điều Chỉnh Delay
- **Default**: 180 giây (3 phút)
- **Khuyến nghị**: 180-300 giây (chống bị spam-flag)
- **Minimum**: 30 giây (rủi ro cao)

### Bước 5: Đăng Video
1. Bấm **🚀 ĐĂNG TOÀN BỘ VIDEO**
2. Xem log real-time trong **Nhật Ký Upload**
3. Chờ hết đợi... (tùy số video)

---

## 📊 Cấu Trúc Project

```
EditVideo_Pro/
├── main.py                    # Entry point
├── requirements.txt           # Dependencies
├── .gitignore                # Ignore data files
│
├── tab1_broll.py             # B-Roll Manager
├── tab2_*.py                 # Faceless Video Creator (AI)
├── tab4_manager.py           # Video Manager & Excel Logger
├── tab5_tiktok.py           # TikTok Download & Upload (MỚI)
├── tab6_subtitle.py         # Subtitle Generator
├── tab7_script.py           # Script Generator
├── tab8_telegram.py         # Telegram Bot UI
├── tab9_script_analysis.py  # Script Analysis
├── tab10_config.py          # Configuration UI
│
├── tab1_modules/
│   ├── ai_vision.py         # Computer Vision (chọn B-roll)
│   └── thumbnail_maker.py   # Thumbnail Generator
│
├── tab2_modules/
│   ├── faceless_ui.py       # Main UI
│   ├── ai_services.py       # AI Integration
│   └── video_engine.py      # Video Rendering
│
├── tab5_modules/            # (MỚI)
│   └── tiktok_uploader.py   # Selenium Upload Automation
│
├── tab7_modules/
│   ├── ai_kie.py            # AI Content Creator
│   └── scraper.py           # Web Scraper
│
├── bot_telegram.py          # Telegram Bot Handler
├── paths.py                 # Project Paths
│
├── Font/                    # Custom Fonts
├── Workspace_Data/
│   ├── Kho_Video_Xuat_Xuong/  # Output Videos
│   ├── Kho_Kich_Ban/          # Scripts Storage
│   └── Danh_Sach_Video.csv    # Video Log
└── TikTok_Downloads/        # Downloaded TikToks
```

---

## 🔧 Troubleshooting

### ❌ `selenium.common.exceptions.WebDriverException`
**Giải pháp:**
```bash
pip install webdriver-manager
```

### ❌ `ChromeDriver version mismatch`
**Giải pháp:**
```bash
# Cập nhật Chrome browser và tải ChromeDriver matching version
# hoặc dùng webdriver-manager (tự động)
pip install --upgrade webdriver-manager
```

### ❌ `selenium.common.exceptions.TimeoutException`
- Đợi thêm (chậm mạng)
- Kiểm tra login TikTok
- Cập nhật TikTok web UI (có thể thay đổi)

### ❌ Upload thất bại - 2FA
- TikTok hiện đang sử dụng 2FA
- Selenium tự động chờ bạn hoàn thành login thủ công
- Nhấn Enter trong terminal sau khi xác thực

---

## 📚 API & Dependencies

| Lib | Version | Mục Đích |
|-----|---------|---------|
| `moviepy` | 1.0.3 | Video Processing |
| `yt-dlp` | 2024.1.1 | Download TikTok |
| `selenium` | 4.15.2 | TikTok Web Automation |
| `groq` | 0.9.0 | AI Script Generation |
| `google-auth` | 2.x | Google Drive Integration |
| `pyTelegramBotAPI` | 4.15.0 | Telegram Bot |

---

## 💡 Tips & Tricks

### Độc Lập Từng Tab
- Mỗi tab có thể dùng riêng lẻ (không phải chạy full)
- Bấm Alt+Tab để chuyển tab nhanh

### Tối Ưu Uploading
```python
# Tab 📤 Upload
Delay: 180s (3 phút)  # Safe
Headless: False       # Theo dõi progress
Template: "{filename} | #viral"
```

### Logs & Debugging
- Kiểm tra `Workspace_Data/Danh_Sach_Video.csv` để track video
- Xem log real-time trong tab (màu xanh = success, đỏ = error)

---

## 🚀 Next Features (Roadmap)

- [ ] TikTok Shop Integration (Auto-commerce)
- [ ] Instagram/YouTube Auto-Post
- [ ] Advanced Analytics Dashboard
- [ ] Cloud Storage Sync (S3, GCS)
- [ ] Multi-account Management
- [ ] Discord Bot Integration

---

## 📝 License

MIT License - Free to use for educational & personal projects

---

## 👨‍💻 Author

**Phạm Văn Bình** - AI Video Editor
- 📞 0345.26.22.29
- 📧 2020phambinh@gmail.com
- 🔗 https://github.com/binhphamdz

---

## 🙏 Acknowledgments

- **MoviePy** - Video editing library
- **yt-dlp** - Video downloader
- **Selenium** - Web automation
- **Groq API** - LLM inference
- **TikTok Community** - For inspiration

---

**Hãy ⭐ Star repository nếu bạn thích công cụ này!**
