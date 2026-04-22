"""
Bot Telegram Web Adapter - Phiên bản độc lập cho FastAPI server
Sử dụng web_services thay vì GUI desktop
"""
import os
import time
import random
import threading
import csv
import shutil
import json
import ast
import requests
from datetime import datetime
from typing import Any, Dict, Optional
import telebot

from paths import (
    DEFAULT_PROFILE,
    get_excel_log_file,
    get_export_dir,
    get_all_profiles,
    get_active_profile,
    set_active_profile,
    sanitize_profile_name,
    get_profile_dir,
    get_projects_list_file,
)
from web_services import (
    load_app_config,
    save_app_config,
    list_projects,
    list_project_voices,
    start_real_render_job,
    ensure_active_profile,
    switch_workspace,
    rename_workspace_entry,
    list_manager_videos,
    send_manager_videos_to_icloud,
)


class WebBotTelegramManager:
    """
    Telegram Bot Manager cho web server (FastAPI)
    Không phụ thuộc tkinter, dùng web_services để thao tác
    """
    
    def __init__(self):
        self.bot: Any = None
        self.bot_is_running = False
        self.bot_sessions: Dict[int, Dict[str, Any]] = {}
        self.session_lock = threading.Lock()
        self.notification_callback: Optional[Any] = None  # Callback để gửi thông báo
        
    def set_notification_callback(self, callback):
        """Đặt callback để gửi thông báo (dùng để notify login/approval)"""
        self.notification_callback = callback
        
    def send_admin_notification(self, message: str):
        """Gửi thông báo đến admin (nếu có callback)"""
        if self.notification_callback:
            try:
                self.notification_callback(message)
            except Exception as e:
                print(f"⚠️ Lỗi gửi thông báo admin: {e}")
    
    def get_active_profile_name(self) -> str:
        """Lấy profile đang active"""
        try:
            return get_active_profile()
        except Exception:
            return DEFAULT_PROFILE
    
    def get_available_profiles(self):
        """Lấy danh sách tất cả profiles"""
        try:
            return get_all_profiles()
        except Exception:
            return [self.get_active_profile_name()]
    
    def switch_profile_from_bot(self, chat_id, target_profile):
        """Chuyển profile từ bot"""
        target_profile = str(target_profile or "").strip()
        if not target_profile:
            if self.bot:
                self.bot.send_message(chat_id, "❌ Bác chưa chọn tài khoản đích.")
            return
        
        try:
            current_profile = self.get_active_profile_name()
            if target_profile == current_profile:
                self.bot.send_message(chat_id, f"ℹ️ Bot đang đứng sẵn ở tài khoản {current_profile} rồi sếp.")
                return
            
            # Chuyển profile
            set_active_profile(target_profile)
            self.clear_sessions()
            self.bot.send_message(chat_id, f"✅ Đã chuyển bot sang tài khoản {target_profile} thành công.")
        except Exception as exc:
            self.bot.send_message(chat_id, f"❌ Không đổi được tài khoản: {exc}")
    
    def rename_profile_from_bot(self, chat_id, old_profile, new_profile_name):
        """Đổi tên profile từ bot"""
        try:
            result = rename_workspace_entry(old_profile, new_profile_name, actor_username="telegram_bot")
            self.clear_sessions()
            if result.get("ok"):
                self.bot.send_message(chat_id, f"✅ {result.get('message', 'Đã đổi tên tài khoản.')}")
            else:
                self.bot.send_message(chat_id, f"❌ {result.get('message', 'Không đổi được tên.')}")
        except Exception as exc:
            self.bot.send_message(chat_id, f"❌ Không đổi tên được tài khoản: {exc}")
    
    def clear_sessions(self):
        """Xóa tất cả sessions"""
        with self.session_lock:
            self.bot_sessions.clear()
    
    def stop_telegram_bot(self):
        """Dừng bot"""
        if self.bot:
            try:
                self.bot.stop_polling()
            except:
                pass
        self.clear_sessions()
        self.bot_is_running = False
    
    def restart_telegram_bot(self):
        """Khởi động lại bot"""
        self.stop_telegram_bot()
        time.sleep(1)
        self.start_telegram_bot()
    
    def get_bot_stats(self):
        """Lấy thống kê từ Excel log"""
        total = today = da_chuyen = chua_chuyen = 0
        today_str = datetime.now().strftime('%d/%m/%Y')
        excel_file = get_excel_log_file(self.get_active_profile_name())
        
        raw_lines = []
        
        if os.path.exists(excel_file):
            try:
                with open(excel_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    for row in reader:
                        if not row or len(row) < 4:
                            continue
                        
                        total += 1
                        if row[0].startswith(today_str):
                            today += 1
                        
                        status = row[4].strip() if len(row) > 4 else "Chưa chuyển"
                        if "Đã" in status:
                            da_chuyen += 1
                        else:
                            chua_chuyen += 1
                        
                        raw_lines.append(",".join(row))
            except Exception as e:
                print("Lỗi đọc Excel của Bot:", e)
        
        return total, today, da_chuyen, chua_chuyen, raw_lines
    
    def get_voice_usage(self):
        """Đọc sổ Excel để lấy số lần từng Voice đã được sử dụng"""
        excel_log_file = get_excel_log_file(self.get_active_profile_name())
        usage = {}
        if os.path.exists(excel_log_file):
            try:
                with open(excel_log_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    for row in reader:
                        if len(row) >= 3:
                            key = f"{row[1].strip()}_{row[2].strip()}"
                            usage[key] = usage.get(key, 0) + 1
            except:
                pass
        return usage

    def _get_project_id(self, project_row: Dict[str, Any]) -> str:
        """Tương thích cả dữ liệu mới (id) và cũ (project_id)."""
        return str(project_row.get("project_id") or project_row.get("id") or "").strip()

    def _get_project_name(self, project_row: Dict[str, Any], fallback_id: str = "") -> str:
        project_name = str(project_row.get("name") or "").strip()
        return project_name or fallback_id or "Unknown"
    
    def start_telegram_bot(self):
        """Khởi động bot Telegram"""
        if self.bot_is_running:
            print("⚠️ Bot đang chạy rồi, từ chối khởi động đúp!")
            return
        
        config = load_app_config()
        token = config.get("telegram_bot_token", "")
        if not token:
            print("⚠️ Chưa có Token Telegram, Bot đang ngủ.")
            return
        
        self.bot = telebot.TeleBot(token)
        self.bot_sessions = {}
        
        # =======================================================
        # 1. LỆNH: SÁCH HƯỚNG DẪN (/help hoặc /start)
        # =======================================================
        @self.bot.message_handler(commands=['help', 'start'])
        def send_help_menu(message):
            current_profile = self.get_active_profile_name()
            help_text = (
                "🤖 *TRỢ LÝ ĐẠO DIỄN AI KÍNH CHÀO SẾP!* 🎬\n\n"
                f"🏛️ Tài khoản đang điều khiển: *{current_profile}*\n\n"
                "Sếp cần em giúp gì nào? Đây là các lệnh để điều khiển hệ thống:\n\n"
                "📁 /projects - Xem danh sách và bật/tắt Project.\n"
                "🏛️ /account - Đổi tài khoản làm việc ngay trên bot.\n"
                "✏️ /renameaccount - Đổi tên tài khoản hiện tại.\n"
                "🚀 /menu (hoặc /render) - Chọn 1 dự án để lên đơn làm video.\n"
                "� /multimenu - Chọn NHIỀU dự án cùng lúc để bốc Voice tự động.\n"
                "🎲 /autobatch - Bốc random TẤT CẢ dự án mỗi nơi vài Voice.\n"
                "📦 /files - Vào kho xem video & trạng thái.\n"
                "☁️ /icloud - Đồng bộ toàn bộ hàng mới sang iCloud.\n"
                "🧹 /clean - Dọn dẹp video cũ trên iCloud.\n"
                "💡 *Mẹo nhỏ:* Ở lệnh /projects, sếp cứ gõ số thứ tự (1, 2, 3...) là cúp điện (đóng băng) hoặc mở khóa project ngay lập tức!"
            )
            self.bot.send_message(message.chat.id, help_text, parse_mode='Markdown')
        
        # =======================================================
        # 2. LỆNH: QUẢN LÝ PROJECT
        # =======================================================
        @self.bot.message_handler(commands=['projects', 'toggle'])
        def list_and_toggle_projects(message):
            current_profile = self.get_active_profile_name()
            projects_data = list_projects(current_profile)
            
            if not projects_data:
                return self.bot.send_message(message.chat.id, "❌ Kho chưa có Project nào!")
            
            sorted_projects = sorted(projects_data, key=lambda x: x.get('created_at', ''), reverse=True)
            
            msg = f"📁 DANH SÁCH PROJECT - TK {current_profile}:\n\n"
            for idx, pdata in enumerate(sorted_projects, 1):
                status = "🟢 Đang mở" if pdata.get('status', 'active') == 'active' else "🔴 Đã Đóng Băng"
                msg += f"{idx}. {pdata['name']} [{status}]\n"
            
            msg += "\n👉 Nhập MỘT SỐ THỨ TỰ (VD: 1, 2 hoặc 3) để Đóng/Mở băng. (Nhập chữ bất kỳ để hủy)"
            sent_msg = self.bot.send_message(message.chat.id, msg)
            self.bot.register_next_step_handler(sent_msg, process_toggle_step, sorted_projects, current_profile)
        
        def process_toggle_step(message, sorted_projects, profile_name):
            text = message.text.strip()
            if not text.isdigit():
                return self.bot.send_message(message.chat.id, "✅ Đã hủy thao tác.")
            
            idx = int(text) - 1
            if idx < 0 or idx >= len(sorted_projects):
                return self.bot.send_message(message.chat.id, "❌ Số không hợp lệ. Đã hủy thao tác.")
            
            target_project = sorted_projects[idx]
            current = target_project.get('status', 'active')
            new_status = 'disabled' if current == 'active' else 'active'
            target_pid = self._get_project_id(target_project)
            if not target_pid:
                return self.bot.send_message(message.chat.id, "❌ Không xác định được mã project để cập nhật.")
            
            # Cập nhật status trong file
            try:
                projects_file = get_projects_list_file(profile_name)
                with open(projects_file, 'r', encoding='utf-8') as f:
                    all_projects = {}
                    try:
                        all_projects = json.load(f)
                    except:
                        f.seek(0)
                        all_projects = ast.literal_eval(f.read())
                
                if target_pid in all_projects:
                    all_projects[target_pid]['status'] = new_status
                    with open(projects_file, 'w', encoding='utf-8') as f:
                        json.dump(all_projects, f, ensure_ascii=False, indent=4)
                
                state_str = "🟢 ĐÃ MỞ KHÓA" if new_status == 'active' else "🔴 ĐÃ ĐÓNG BĂNG"
                self.bot.send_message(message.chat.id, f"✅ {state_str} project trong tài khoản {profile_name}:\n👉 {target_project['name']}")
            except Exception as e:
                self.bot.send_message(message.chat.id, f"❌ Lỗi cập nhật project: {e}")
        
        # =======================================================
        # 3. LỆNH: CHUYỂN TÀI KHOẢN
        # =======================================================
        @self.bot.message_handler(commands=['account', 'accounts', 'profile', 'taikhoan'])
        def handle_account_switch(message):
            chat_id = message.chat.id
            profiles = self.get_available_profiles()
            current_profile = self.get_active_profile_name()
            
            if not profiles:
                return self.bot.send_message(chat_id, "❌ Chưa có tài khoản nào để đổi sếp ơi.")
            
            msg = f"🏛️ TÀI KHOẢN HIỆN TẠI: {current_profile}\n\n"
            msg += "Danh sách tài khoản đang có:\n"
            for idx, name in enumerate(profiles, 1):
                icon = "✅" if name == current_profile else "▫️"
                msg += f"{idx}. {icon} {name}\n"
            msg += "\n👉 Sếp nhắn số thứ tự hoặc gõ đúng tên tài khoản để đổi nhé."
            
            with self.session_lock:
                self.bot_sessions[chat_id] = {'profile_options': profiles}
            
            sent_msg = self.bot.send_message(chat_id, msg)
            self.bot.register_next_step_handler(sent_msg, process_account_switch)
        
        def process_account_switch(message):
            chat_id = message.chat.id
            text = message.text.strip()
            with self.session_lock:
                session = self.bot_sessions.get(chat_id)
            
            if not session or 'profile_options' not in session:
                return self.bot.send_message(chat_id, "❌ Phiên chọn tài khoản đã hết hạn, sếp gõ lại lệnh giúp em nhé.")
            
            profiles = session.get('profile_options', [])
            target_profile = None
            
            if text.isdigit():
                idx = int(text) - 1
                if 0 <= idx < len(profiles):
                    target_profile = profiles[idx]
            else:
                for name in profiles:
                    if name.casefold() == text.casefold():
                        target_profile = name
                        break
            
            with self.session_lock:
                self.bot_sessions.pop(chat_id, None)
            
            if not target_profile:
                return self.bot.send_message(chat_id, "❌ Em không thấy tài khoản đó. Bác gõ lại lệnh rồi chọn lại giúp em nhé.")
            
            self.bot.send_message(chat_id, f"⏳ Đang chuyển sang tài khoản {target_profile}...")
            self.switch_profile_from_bot(chat_id, target_profile)
        
        # =======================================================
        # 4. LỆNH: ĐỔI TÊN TÀI KHOẢN
        # =======================================================
        @self.bot.message_handler(commands=['renameaccount', 'renameprofile', 'doiten'])
        def handle_account_rename(message):
            chat_id = message.chat.id
            current_profile = self.get_active_profile_name()
            sent_msg = self.bot.send_message(chat_id, f"✏️ Tài khoản hiện tại là: {current_profile}\n\n👉 Sếp nhắn tên mới để em đổi ngay nhé.")
            self.bot.register_next_step_handler(sent_msg, process_account_rename, current_profile)
        
        def process_account_rename(message, old_profile):
            chat_id = message.chat.id
            new_profile_name = message.text.strip()
            if not new_profile_name:
                return self.bot.send_message(chat_id, "❌ Tên mới đang bị trống, sếp gõ lại giúp em nhé.")
            self.bot.send_message(chat_id, f"⏳ Đang đổi tên tài khoản {old_profile}...")
            self.rename_profile_from_bot(chat_id, old_profile, new_profile_name)
        
        # =======================================================
        # 5. LỆNH: XEM FILE TRONG KHO
        # =======================================================
        @self.bot.message_handler(commands=['files', 'kho'])
        def handle_view_files(message):
            chat_id = message.chat.id
            self.bot.send_chat_action(chat_id, 'typing')
            
            current_profile = self.get_active_profile_name()
            output_dir = get_export_dir(current_profile)
            
            if not os.path.exists(output_dir):
                return self.bot.send_message(chat_id, "❌ Em không tìm thấy thư mục kho hàng!")
            
            video_files = [f for f in os.listdir(output_dir) if f.lower().endswith('.mp4')]
            if not video_files:
                return self.bot.send_message(chat_id, f"🏜️ Kho hàng của tài khoản {current_profile} đang trống trơn sếp ạ!")
            
            video_files.sort(key=lambda x: os.path.getmtime(os.path.join(output_dir, x)), reverse=True)
            _, _, _, _, raw_lines = self.get_bot_stats()
            
            msg = f"📊 **KHO THÀNH PHẨM - {current_profile} ({len(video_files)} video):**\n\n"
            file_map = []
            
            for i, f_name in enumerate(video_files[:15], 1):
                file_map.append(f_name)
                tail_code = f_name[-12:] if len(f_name) > 12 else f_name
                stt = "Chưa rõ"
                for line in reversed(raw_lines):
                    if tail_code in line:
                        if "Đã chuyển" in line:
                            stt = "Đã chuyển"
                        elif "Chưa chuyển" in line:
                            stt = "Chưa chuyển"
                        break
                
                icon = "🟢" if "Đã" in stt else "🟡"
                msg += f"{i}. {icon} `{f_name}` *(Trạng thái: {stt})*\n"
            
            msg += "\n👉 Sếp muốn ném file nào vào iCloud thì **nhắn lại các số thứ tự (cách nhau bằng dấu phẩy)** nhé (VD: 1,3,5)!"
            with self.session_lock:
                self.bot_sessions[chat_id] = {'file_map': file_map, 'output_dir': output_dir, 'profile_name': current_profile}
            msg_sent = self.bot.send_message(chat_id, msg, parse_mode="Markdown")
            self.bot.register_next_step_handler(msg_sent, process_file_delivery)
        
        def process_file_delivery(message):
            chat_id = message.chat.id
            text = message.text.strip()
            with self.session_lock:
                session = self.bot_sessions.get(chat_id)
            if not session or 'file_map' not in session:
                return
            
            try:
                choices = [int(x.strip()) - 1 for x in text.split(',')]
                if any(i < 0 or i >= len(session['file_map']) for i in choices):
                    return self.bot.send_message(chat_id, "❌ Số không hợp lệ sếp ơi!")
                target_files = [session['file_map'][i] for i in choices]
            except ValueError:
                return self.bot.send_message(chat_id, "❌ Sếp gõ sai cú pháp rồi (VD chuẩn: 1,3,5)!")
            except Exception as e:
                print(f"⚠️ Lỗi process_file_delivery: {e}")
                return self.bot.send_message(chat_id, f"❌ Lỗi: {str(e)[:50]}")
            
            self.bot.send_message(chat_id, f"🚀 Đang gom {len(target_files)} file ném thẳng vào iCloud Drive...")
            self.bot.send_chat_action(chat_id, 'upload_document')
            
            try:
                config = load_app_config()
                icloud_dir = config.get("icloud_path", "")
                folder_name = f"Auto_iCloud_{datetime.now().strftime('%d%m%Y_%H%M')}"
                target_dir = os.path.join(icloud_dir, folder_name)
                os.makedirs(target_dir, exist_ok=True)
                
                success_count = 0
                output_dir = session.get('output_dir', get_export_dir(session.get('profile_name', DEFAULT_PROFILE)))
                for target_file in target_files:
                    file_path = os.path.join(output_dir, target_file)
                    if os.path.exists(file_path):
                        target_path = os.path.join(target_dir, f"[{datetime.now().strftime('%Y%m%d_%H%M')}]_{target_file}")
                        shutil.copy2(file_path, target_path)
                        success_count += 1
                
                self.bot.send_message(chat_id, f"✅ **Xong rồi sếp ơi!** Đã đẩy thành công {success_count}/{len(target_files)} file vào iCloud mục `{folder_name}`.")
            except Exception as e:
                print(f"⚠️ Lỗi process_file_delivery copy: {e}")
                self.bot.send_message(chat_id, f"❌ Lỗi copy vào iCloud: {str(e)[:50]}")
            finally:
                with self.session_lock:
                    self.bot_sessions.pop(chat_id, None)
        
        # =======================================================
        # 6. LỆNH: RENDER VIDEO
        # =======================================================
        @self.bot.message_handler(commands=['menu', 'render'])
        def handle_menu(message):
            chat_id = message.chat.id
            current_profile = self.get_active_profile_name()
            projects_data = list_projects(current_profile)
            
            if not projects_data:
                return self.bot.send_message(chat_id, "Kho trống trơn sếp ơi!")
            
            proj_list = [
                (self._get_project_id(p), self._get_project_name(p, self._get_project_id(p)))
                for p in projects_data
                if self._get_project_id(p)
            ]

            if not proj_list:
                return self.bot.send_message(chat_id, "❌ Không tìm thấy project hợp lệ để chạy.")
            
            msg = f"📁 **Dự án nhà mình - {current_profile}:**\n"
            msg += "".join([f" {i}. {n}\n" for i, (p, n) in enumerate(proj_list, 1)])
            msg += "\n👇 Sếp nhắn **số thứ tự** Project nhé:"
            
            with self.session_lock:
                self.bot_sessions[chat_id] = {'proj_list': proj_list, 'profile_name': current_profile}
            
            sent_msg = self.bot.send_message(chat_id, msg, parse_mode="Markdown")
            self.bot.register_next_step_handler(sent_msg, process_project_choice)
        
        def process_project_choice(message):
            chat_id = message.chat.id
            try:
                with self.session_lock:
                    sess = self.bot_sessions.get(chat_id)
                if not sess or 'proj_list' not in sess:
                    return self.bot.send_message(chat_id, "❌ Session hết hạn, gõ lại lệnh /menu nhé!")
                
                idx = int(message.text.strip()) - 1
                if idx < 0 or idx >= len(sess['proj_list']):
                    return self.bot.send_message(chat_id, "❌ Số không hợp lệ sếp ơi!")
                
                pid, proj_name = sess['proj_list'][idx]
            except ValueError:
                return self.bot.send_message(chat_id, "Sếp gõ sai số rồi!")
            except Exception as e:
                print(f"⚠️ Lỗi process_project_choice: {e}")
                return self.bot.send_message(chat_id, f"❌ Lỗi: {str(e)[:50]}")
            
            profile_name = sess.get('profile_name', self.get_active_profile_name())
            
            # Lấy danh sách voices
            voices = list_project_voices(pid, profile_name)
            
            if not voices:
                return self.bot.send_message(chat_id, f"Không có voice nào trong {proj_name}!")
            
            with self.session_lock:
                self.bot_sessions[chat_id].update({
                    'pid': pid,
                    'proj_name': proj_name,
                    'voice_map': voices,
                })
            
            msg = f"🎧 **Dự án `{proj_name}` đang có {len(voices)} file âm thanh:**\n\n"
            for i, v in enumerate(voices, 1):
                msg += f" {i}. `{v}`\n"
            msg += "\n👇 Sếp chốt số mấy? (Nhắn các số cách nhau bằng dấu phẩy VD: 1,3)"
            
            sent_msg = self.bot.send_message(chat_id, msg, parse_mode="Markdown")
            self.bot.register_next_step_handler(sent_msg, process_voice_choice)
        
        def process_voice_choice(message):
            chat_id = message.chat.id
            with self.session_lock:
                sess = self.bot_sessions.get(chat_id)
            if not sess or 'voice_map' not in sess:
                return self.bot.send_message(chat_id, "❌ Session hết hạn, gõ lại lệnh /menu nhé!")
            
            try:
                choices = [int(x.strip()) - 1 for x in message.text.split(',')]
                if any(i < 0 or i >= len(sess['voice_map']) for i in choices):
                    return self.bot.send_message(chat_id, "❌ Số không hợp lệ sếp ơi!")
                selected = [sess['voice_map'][i] for i in choices]
            except ValueError:
                return self.bot.send_message(chat_id, "Sai cú pháp!")
            except Exception as e:
                print(f"⚠️ Lỗi process_voice_choice: {e}")
                return self.bot.send_message(chat_id, f"❌ Lỗi: {str(e)[:50]}")
            
            self.bot.send_message(chat_id, f"🚀 Bắt đầu xào nấu {len(selected)} video!")
            
            # Tạo render jobs cho web
            def run_menu_batch():
                completed = 0
                profile_name = sess.get('profile_name', self.get_active_profile_name())
                
                for voice_name in selected:
                    try:
                        # Gọi hàm render từ web_services
                        result = start_real_render_job(
                            project_id=sess['pid'],
                            profile_name=profile_name,
                            voice_names=[voice_name],
                            created_by="telegram_bot"
                        )
                        
                        if result.get("ok"):
                            completed += 1
                        time.sleep(1.5)  # Chống kẹt
                    except Exception as e:
                        print(f"⚠️ Lỗi render {voice_name}: {e}")
                
                self.bot.send_message(chat_id, f"🎉 DẠ XONG đơn của sếp ({completed}/{len(selected)} video)!")
                
                with self.session_lock:
                    self.bot_sessions.pop(chat_id, None)
            
            threading.Thread(target=run_menu_batch, daemon=True).start()
        
        # =======================================================
        # 7. LỆNH: ĐỒNG BỘ ICLOUD
        # =======================================================
        @self.bot.message_handler(commands=['icloud', 'sync'])
        def handle_sync_icloud(message):
            self.bot.reply_to(message, "Dạ rõ! Đang ném vào iCloud cho sếp... 📦💨")
            
            def do_sync():
                try:
                    current_profile = self.get_active_profile_name()
                    # Lấy danh sách tất cả videos
                    output_dir = get_export_dir(current_profile)
                    video_files = []
                    if os.path.exists(output_dir):
                        video_files = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.lower().endswith('.mp4')]
                    
                    if not video_files:
                        return self.bot.send_message(message.chat.id, "📦 Kho trống, không có gì để đồng bộ sếp ơi!")
                    
                    result = send_manager_videos_to_icloud(video_files, current_profile)
                    
                    if result.get("ok"):
                        self.bot.send_message(message.chat.id, f"✅ Đã đồng bộ {result.get('synced', 0)} video lên iCloud!")
                    else:
                        self.bot.send_message(message.chat.id, f"❌ Lỗi đồng bộ: {result.get('message', 'Unknown')}")
                except Exception as e:
                    self.bot.send_message(message.chat.id, f"❌ Lỗi: {e}")
            
            threading.Thread(target=do_sync, daemon=True).start()
        
        # =======================================================
        # 8. LỆNH: CHỌN NHIỀU PROJECT ĐỂ RENDER
        # =======================================================
        @self.bot.message_handler(commands=['multimenu', 'chonnhieu'])
        def handle_multi_menu(message):
            chat_id = message.chat.id
            current_profile = self.get_active_profile_name()
            projects_data = list_projects(current_profile)
            
            if not projects_data:
                return self.bot.send_message(chat_id, "❌ Kho trống trơn sếp ơi!")
            
            proj_list = [
                (self._get_project_id(p), self._get_project_name(p, self._get_project_id(p)))
                for p in projects_data
                if self._get_project_id(p)
            ]

            if not proj_list:
                return self.bot.send_message(chat_id, "❌ Không tìm thấy project hợp lệ để chạy.")
            msg = f"📁 **CHỌN NHIỀU DỰ ÁN ĐỂ CHẠY TỰ ĐỘNG - {current_profile}:**\n\n"
            for i, (p, n) in enumerate(proj_list, 1):
                msg += f" {i}. {n}\n"
            msg += "\n👇 Sếp nhắn **các số thứ tự** cách nhau bằng dấu phẩy nhé (VD: 1,3,5):"
            
            with self.session_lock:
                self.bot_sessions[chat_id] = {'proj_list': proj_list, 'profile_name': current_profile}
            msg_sent = self.bot.send_message(chat_id, msg, parse_mode="Markdown")
            self.bot.register_next_step_handler(msg_sent, process_multi_project_choice)
        
        def process_multi_project_choice(message):
            chat_id = message.chat.id
            text = message.text.strip()
            with self.session_lock:
                sess = self.bot_sessions.get(chat_id)
            if not sess or 'proj_list' not in sess:
                return
            
            try:
                choices = [int(x.strip()) - 1 for x in text.split(',')]
                if any(i < 0 or i >= len(sess['proj_list']) for i in choices):
                    return self.bot.send_message(chat_id, "❌ Số không hợp lệ sếp ơi!")
                selected_projects = [sess['proj_list'][i] for i in choices]
            except ValueError:
                return self.bot.send_message(chat_id, "❌ Sếp gõ sai cú pháp rồi (VD chuẩn: 1,3,5)!")
            except Exception as e:
                print(f"⚠️ Lỗi process_multi_project_choice: {e}")
                return self.bot.send_message(chat_id, f"❌ Lỗi: {str(e)[:50]}")
            
            voice_usage_db = self.get_voice_usage()
            render_queue = []
            msg_log = "🎲 **Báo cáo kết quả đi chợ (Ưu tiên Voice ít dùng):**\n"
            
            profile_name = sess.get('profile_name', self.get_active_profile_name())
            for pid, proj_name in selected_projects:
                voices = list_project_voices(pid, profile_name)
                if voices:
                    # Sắp xếp theo usage (ít dùng trước), lấy top 5 voice
                    voices_sorted = sorted(voices, key=lambda v: voice_usage_db.get(f"{proj_name}_{v}", 0))
                    top_voices = voices_sorted[:min(5, len(voices_sorted))]
                    random.shuffle(top_voices)
                    
                    num_to_pick = min(random.randint(2, 3), len(top_voices))
                    picked_count = 0
                    
                    for chosen_voice in top_voices[:num_to_pick]:
                        render_queue.append((pid, chosen_voice, proj_name))
                        voice_usage_db[f"{proj_name}_{chosen_voice}"] = voice_usage_db.get(f"{proj_name}_{chosen_voice}", 0) + 1
                        picked_count += 1
                    
                    msg_log += f"✅ `{proj_name}`: Đã ép nổ {picked_count} video.\n"
                else:
                    msg_log += f"⚠️ `{proj_name}`: Không có voice, bỏ qua!\n"
            
            if not render_queue:
                return self.bot.send_message(chat_id, msg_log + "\n❌ Túm lại là không bốc được cái voice nào sếp ạ!")
            
            self.bot.send_message(chat_id, msg_log + f"\n🚀 **TỔNG CỘNG ĐÃ GOM {len(render_queue)} BÀI!**\nEm tống hết vào máy nổ luồng luôn nha sếp! 🏃‍♀️💨", parse_mode="Markdown")
            
            def process_mixed_queue():
                completed = 0
                for pid, voice_name, proj_name in render_queue:
                    try:
                        result = start_real_render_job(
                            project_id=pid,
                            profile_name=profile_name,
                            voice_names=[voice_name],
                            created_by="telegram_bot"
                        )
                        if result.get("ok"):
                            completed += 1
                        time.sleep(1.5)
                    except Exception as e:
                        print(f"⚠️ Lỗi render {proj_name}/{voice_name}: {e}")
                
                self.bot.send_message(chat_id, f"🎉 DẠ XONG! Chuyến xe Multi-Project đã xuất xưởng {completed}/{len(render_queue)} video.\nSếp gõ /icloud để nhận hàng nhé!")
                
                with self.session_lock:
                    self.bot_sessions.pop(chat_id, None)
            
            threading.Thread(target=process_mixed_queue, daemon=True).start()
        
        # =======================================================
        # 9. LỆNH: AUTO BATCH - RANDOM TẤT CẢ PROJECT
        # =======================================================
        @self.bot.message_handler(commands=['autobatch', 'random'])
        def handle_auto_batch(message):
            chat_id = message.chat.id
            self.bot.send_message(chat_id, "🎲 Dạ sếp! Em đang soi sổ Excel để bốc ưu tiên các Voice ÍT DÙNG NHẤT đây...")
            
            current_profile = self.get_active_profile_name()
            projects_data = list_projects(current_profile)
            
            if not projects_data:
                return self.bot.send_message(chat_id, "❌ Kho trống trơn sếp ơi!")
            
            voice_usage_db = self.get_voice_usage()
            render_queue = []
            
            for pdata in projects_data:
                pid = self._get_project_id(pdata)
                if not pid:
                    continue
                pname = self._get_project_name(pdata, pid)
                
                voices = list_project_voices(pid, current_profile)
                if voices:
                    # Sắp xếp theo usage (ít dùng trước), lấy top 5 voice
                    voices_sorted = sorted(voices, key=lambda v: voice_usage_db.get(f"{pname}_{v}", 0))
                    top_voices = voices_sorted[:min(5, len(voices_sorted))]
                    random.shuffle(top_voices)
                    
                    num_to_pick = min(2, len(top_voices))
                    for chosen_voice in top_voices[:num_to_pick]:
                        render_queue.append((pid, chosen_voice, pname))
                        voice_usage_db[f"{pname}_{chosen_voice}"] = voice_usage_db.get(f"{pname}_{chosen_voice}", 0) + 1
            
            if not render_queue:
                return self.bot.send_message(chat_id, "❌ Kho voice nhà mình trống trơn chưa có file nào sếp ơi!")
            
            self.bot.send_message(chat_id, f"🚀 ĐÃ GOM ĐƯỢC {len(render_queue)} BÀI (Ưu tiên Voice mới/Random)!\nEm tống hết vào máy nổ luồng luôn nha sếp. 🏃‍♀️💨")
            
            def process_mixed_queue():
                completed = 0
                for pid, voice_name, proj_name in render_queue:
                    try:
                        result = start_real_render_job(
                            project_id=pid,
                            profile_name=current_profile,
                            voice_names=[voice_name],
                            created_by="telegram_bot"
                        )
                        if result.get("ok"):
                            completed += 1
                        time.sleep(1.5)
                    except Exception as e:
                        print(f"⚠️ Lỗi render {proj_name}/{voice_name}: {e}")
                
                self.bot.send_message(chat_id, f"🎉 DẠ XONG! Chuyến xe Random đã xuất xưởng {completed}/{len(render_queue)} video.\nSếp gõ /icloud để nhận hàng nhé!")
            
            threading.Thread(target=process_mixed_queue, daemon=True).start()
        
        # =======================================================
        # 10. LỆNH: DỌN DẸP ICLOUD
        # =======================================================
        @self.bot.message_handler(commands=['clean', 'dondep'])
        def handle_clean_icloud(message):
            chat_id = message.chat.id
            config = load_app_config()
            icloud_dir = config.get("icloud_path", "")
            
            if not icloud_dir:
                return self.bot.send_message(chat_id, "❌ Em chưa thấy thư mục iCloud ở nhà.")
            
            if not os.path.exists(icloud_dir):
                return self.bot.send_message(chat_id, "❌ Thư mục iCloud không tồn tại!")
            
            folders_to_delete = [
                os.path.join(icloud_dir, item)
                for item in os.listdir(icloud_dir)
                if (item.startswith("Video_Xuat") or item.startswith("Auto_iCloud"))
                and os.path.isdir(os.path.join(icloud_dir, item))
            ]
            
            if not folders_to_delete:
                return self.bot.send_message(chat_id, "✨ iCloud nhà mình đang sạch bong sếp ơi!")
            
            with self.session_lock:
                self.bot_sessions[chat_id] = {'folders_to_delete': folders_to_delete}
            
            msg_sent = self.bot.send_message(
                chat_id,
                f"🧹 TÌM THẤY {len(folders_to_delete)} LÔ HÀNG CŨ!\nSếp nhắn chữ: **XOA** để em phi tang nhé."
            )
            
            def confirm_clean(m):
                if m.text.strip().upper() == "XOA":
                    deleted = 0
                    for f in folders_to_delete:
                        try:
                            shutil.rmtree(f)
                            deleted += 1
                        except Exception as e:
                            print(f"⚠️ Lỗi xóa {f}: {e}")
                    self.bot.send_message(chat_id, f"Đã dọn dẹp xong {deleted} thư mục rác! 🗑️")
                else:
                    self.bot.send_message(chat_id, "Đã hủy dọn dẹp, hàng họ vẫn còn nguyên sếp nhé!")
                
                with self.session_lock:
                    self.bot_sessions.pop(chat_id, None)
            
            self.bot.register_next_step_handler(msg_sent, confirm_clean)
        
        # =======================================================
        # 11. CHAT TỰ DO VỚI AI
        # =======================================================
        @self.bot.message_handler(func=lambda message: not message.text.startswith('/'))
        def handle_free_chat(message):
            chat_id = message.chat.id
            user_text = message.text
            config = load_app_config()
            groq_key = config.get("groq_key", "").strip()
            
            if not groq_key:
                return self.bot.reply_to(message, "Sếp ơi chưa có Key Llama 3.3 trong config!")
            
            self.bot.send_chat_action(chat_id, 'typing')
            
            total_vids, today_vids, da_chuyen, chua_chuyen, _ = self.get_bot_stats()
            
            def fetch_ai_reply():
                try:
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                    
                    sys_prompt = (
                        f"Bạn là nữ thư ký AI 'Trợ Lý Video' quản lý xưởng edit. Xưng em, gọi sếp. "
                        f"Báo cáo kho hiện tại: Tổng đã SX {total_vids} video (Riêng hôm nay làm được: {today_vids}). "
                        f"TÌNH TRẠNG KHO: Đã đẩy lên iCloud {da_chuyen} video. CÒN TỒN TRONG MÁY {chua_chuyen} video (Chưa chuyển). "
                        f"Nhiệm vụ: Trả lời tự nhiên, hài hước, ngắn gọn. Nếu sếp hỏi tình hình, hãy báo cáo đúng số liệu trên. "
                        f"Nếu thấy còn hàng tồn (chưa chuyển), hãy nịnh sếp gõ lệnh /icloud để em đẩy đi cho sạch kho."
                    )
                    
                    payload = {
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": user_text}
                        ],
                        "temperature": 0.7
                    }
                    
                    res = requests.post(url, headers=headers, json=payload, timeout=15)
                    if res.status_code == 200:
                        try:
                            self.bot.reply_to(message, res.json()["choices"][0]["message"]["content"])
                        except (KeyError, IndexError) as e:
                            print(f"⚠️ Lỗi parse AI response: {e}")
                            self.bot.reply_to(message, "Ui não em đang lag 😵‍💫")
                    else:
                        print(f"⚠️ Groq API error: {res.status_code}")
                        self.bot.reply_to(message, "Ui não em đang lag 😵‍💫")
                except requests.exceptions.Timeout:
                    print("⚠️ Timeout khi gọi Groq API")
                    self.bot.reply_to(message, "Mạng kém quá em không rep được! 🥲")
                except requests.exceptions.RequestException as e:
                    print(f"⚠️ Lỗi network: {e}")
                    self.bot.reply_to(message, "Mạng kém quá em không rep được! 🥲")
                except Exception as e:
                    print(f"⚠️ Lỗi fetch_ai_reply: {e}")
                    self.bot.reply_to(message, "Có lỗi gì đó rồi sếp ơi! 😭")
            
            threading.Thread(target=fetch_ai_reply, daemon=True).start()
        
        # =======================================================
        # BẮT ĐẦU POLLING
        # =======================================================
        def run_bot():
            self.bot_is_running = True
            try:
                print("🤖 [WEB] Bot Telegram đã lên sóng từ server FastAPI...")
                self.bot.infinity_polling()
            except Exception as e:
                print(f"Lỗi Bot Web: {e}")
            self.bot_is_running = False
        
        threading.Thread(target=run_bot, daemon=True).start()


# Singleton instance
_bot_manager_instance: Optional[WebBotTelegramManager] = None


def get_bot_manager() -> WebBotTelegramManager:
    """Lấy bot manager singleton"""
    global _bot_manager_instance
    if _bot_manager_instance is None:
        _bot_manager_instance = WebBotTelegramManager()
    return _bot_manager_instance


def send_telegram_notification(message: str, admin_chat_id: Optional[int] = None):
    """
    Gửi thông báo qua Telegram bot
    Nếu không có admin_chat_id, sẽ broadcast cho tất cả admin
    """
    bot_manager = get_bot_manager()
    if bot_manager.bot and bot_manager.bot_is_running:
        try:
            # TODO: Lưu danh sách admin_chat_id vào config hoặc database
            # Tạm thời gửi cho tất cả users đã chat với bot
            # Hoặc có thể lưu admin_chat_id vào config
            config = load_app_config()
            admin_ids = config.get("telegram_admin_chat_ids", [])
            
            if admin_chat_id:
                bot_manager.bot.send_message(admin_chat_id, message)
            elif admin_ids:
                for chat_id in admin_ids:
                    try:
                        bot_manager.bot.send_message(chat_id, message)
                    except:
                        pass
            else:
                print(f"⚠️ Không có admin chat ID để gửi thông báo: {message}")
        except Exception as e:
            print(f"⚠️ Lỗi gửi Telegram notification: {e}")
