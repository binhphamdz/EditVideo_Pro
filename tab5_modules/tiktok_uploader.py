"""
🎬 TikTok Auto Uploader - Upload video tự động lên TikTok bằng Selenium
Hỗ trợ: Batch upload, hashtag tự động, delay chống spam
"""

import os
import time
import threading
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
import random


class TikTokUploader:
    def __init__(self, callback_log=None):
        """
        Args:
            callback_log: Function để log messages. Signature: callback_log(msg)
        """
        self.driver = None
        self.callback_log = callback_log or print
        self.is_logged_in = False
        self.uploading = False

    def log(self, msg):
        """Log message với timestamp"""
        ts = datetime.now().strftime("%H:%M:%S")
        self.callback_log(f"[{ts}] {msg}")

    def init_driver(self, headless=False):
        """Khởi tạo Selenium Chrome driver"""
        try:
            options = Options()
            if headless:
                options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )

            self.driver = webdriver.Chrome(options=options)
            self.log("✅ Chrome driver khởi tạo thành công")
            return True
        except Exception as e:
            self.log(f"❌ Lỗi khởi tạo Chrome: {e}")
            return False

    def login(self, wait_manual=True):
        """
        Đăng nhập TikTok (hỗ trợ manual login để tránh 2FA)
        Args:
            wait_manual: Nếu True, chờ user nhấn Enter sau khi login
        """
        try:
            if not self.driver:
                self.init_driver(headless=False)

            self.log("🔐 Mở trang TikTok để đăng nhập...")
            self.driver.get("https://www.tiktok.com/upload")
            
            if wait_manual:
                self.log("👤 Vui lòng đăng nhập vào TikTok trong cửa sổ Chrome")
                self.log("⏸️ Nhấn Enter trong terminal sau khi đăng nhập xong...")
                input()
                
            # Kiểm tra đã login hay chưa
            time.sleep(3)
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
                )
                self.is_logged_in = True
                self.log("✅ Đã đăng nhập TikTok thành công!")
                return True
            except:
                self.log("❌ Login thất bại hoặc hết time")
                return False
        except Exception as e:
            self.log(f"❌ Lỗi login: {e}")
            return False

    def upload_video(self, video_path, title="", description="", hashtags=""):
        """
        Upload 1 video lên TikTok
        Args:
            video_path: Đường dẫn file video
            title: Tiêu đề video
            description: Mô tả video
            hashtags: Hashtag (cách nhau bằng space, vd: "#quochp #viral")
        Returns:
            True nếu upload thành công
        """
        if not self.is_logged_in:
            self.log("⚠️ Chưa đăng nhập! Vui lòng login trước")
            return False

        if not os.path.exists(video_path):
            self.log(f"❌ File không tồn tại: {video_path}")
            return False

        try:
            self.uploading = True
            video_name = os.path.basename(video_path)
            self.log(f"🚀 Bắt đầu upload: {video_name}")

            # === BƯỚC 1: Upload file ===
            self.log("1️⃣ Chọn file video...")
            file_input = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
            )
            file_input.send_keys(os.path.abspath(video_path))
            self.log("✅ File đã chọn")

            # === BƯỚC 2: Chờ upload hoàn thành & chỉnh sửa ===
            time.sleep(5)
            self.log("2️⃣ Chờ video xử lý...")
            
            # Chờ nút "Next" xuất hiện
            try:
                next_btn = WebDriverWait(self.driver, 60).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(text(), 'Next') or contains(., 'Tiếp tục')]")
                    )
                )
                next_btn.click()
                self.log("✅ Bấm Next")
            except:
                self.log("⚠️ Không tìm thấy nút Next, tiếp tục...")

            # === BƯỚC 3: Nhập text ===
            time.sleep(3)
            self.log("3️⃣ Nhập mô tả...")
            
            # Tìm và fill caption/description
            caption_xpath_options = [
                "//textarea[@placeholder*='caption' or @placeholder*='caption']",
                "//textarea[@placeholder*='Describe' or @placeholder*='Mô tả']",
                "//textarea",
                "//div[@contenteditable='true']"
            ]
            
            caption_text = f"{title}\n\n{description}\n\n{hashtags}".strip()
            
            caption_filled = False
            for xpath in caption_xpath_options:
                try:
                    caption_elem = WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, xpath))
                    )
                    caption_elem.click()
                    time.sleep(1)
                    caption_elem.clear()
                    caption_elem.send_keys(caption_text)
                    self.log(f"✅ Nhập mô tả: {caption_text[:50]}...")
                    caption_filled = True
                    break
                except:
                    continue

            if not caption_filled:
                self.log("⚠️ Không tìm thấy ô nhập mô tả")

            # === BƯỚC 4: Chỉnh quyền riêng tư ===
            time.sleep(2)
            self.log("4️⃣ Chỉnh quyền riêng tư (Public)...")
            try:
                privacy_selector = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Public') or contains(text(), 'Công khai')]"))
                )
                privacy_selector.click()
                self.log("✅ Đặt thành Public")
            except:
                self.log("⚠️ Không thể thay đổi quyền riêng tư")

            # === BƯỚC 5: Post ===
            time.sleep(3)
            self.log("5️⃣ Nhấn Post/Upload...")
            try:
                post_btn = WebDriverWait(self.driver, 20).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(text(), 'Post') or contains(text(), 'Đăng') or contains(text(), 'Upload')]")
                    )
                )
                post_btn.click()
                self.log("✅ Nhấn Post")
                
                # Chờ thông báo thành công
                time.sleep(10)
                try:
                    success = self.driver.find_element(By.XPATH, "//span[contains(text(), 'successfully') or contains(text(), 'thành công')]")
                    self.log(f"🎉 THÀNH CÔNG: {video_name}")
                    return True
                except:
                    self.log("⚠️ Không chắc upload thành công, nhưng không có lỗi")
                    return True
                    
            except Exception as e:
                self.log(f"❌ Lỗi nhấn Post: {e}")
                return False

        except Exception as e:
            self.log(f"❌ Lỗi upload: {e}")
            return False
        finally:
            self.uploading = False
            # Reload để upload video tiếp theo
            time.sleep(3)
            self.driver.get("https://www.tiktok.com/upload")

    def upload_batch(self, video_files, title_template="", description_template="", hashtags="", delay_seconds=180):
        """
        Upload batch video
        Args:
            video_files: List đường dẫn video
            title_template: Template tiêu đề (có thể có {filename}, {index})
            description_template: Template mô tả
            hashtags: Hashtag chung
            delay_seconds: Delay giữa các upload (chống spam)
        """
        success = 0
        failed = 0

        for idx, video_file in enumerate(video_files, 1):
            if not os.path.exists(video_file):
                self.log(f"⏭️ Bỏ qua: File không tồn tại {video_file}")
                failed += 1
                continue

            filename = os.path.splitext(os.path.basename(video_file))[0]
            
            # Thay thế template
            title = title_template.format(filename=filename, index=idx)
            description = description_template.format(filename=filename, index=idx)

            self.log(f"\n{'='*60}")
            self.log(f"📌 VIDEO {idx}/{len(video_files)}")
            self.log(f"{'='*60}")

            if self.upload_video(video_file, title, description, hashtags):
                success += 1
            else:
                failed += 1

            # Delay giữa các upload
            if idx < len(video_files):
                self.log(f"⏳ Chờ {delay_seconds}s trước upload tiếp theo...")
                for remaining in range(delay_seconds, 0, -1):
                    if remaining % 10 == 0:
                        self.log(f"   Còn {remaining}s...")
                    time.sleep(1)

        self.log(f"\n{'='*60}")
        self.log(f"🎊 BATCH UPLOAD XONG!")
        self.log(f"✅ Thành công: {success}")
        self.log(f"❌ Thất bại: {failed}")
        self.log(f"{'='*60}")

    def close(self):
        """Đóng browser"""
        if self.driver:
            self.driver.quit()
            self.log("🔌 Đã đóng Chrome")
