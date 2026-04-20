import os
import time
import random
import threading
import csv
import shutil
import requests
from datetime import datetime
import concurrent.futures
import telebot
from paths import DEFAULT_PROFILE, get_export_dir

class TelegramBotManager:
    def __init__(self, main_app):
        self.main_app = main_app
        self.bot = None
        self.bot_is_running = False
        self.bot_sessions = {}
        self.session_lock = threading.Lock()  # 🔒 Thread-safety cho sessions

    def get_active_profile_name(self):
        try:
            return self.main_app.get_active_profile_name()
        except Exception:
            return DEFAULT_PROFILE

    def get_live_output_dir(self):
        return get_export_dir(self.get_active_profile_name())

    def get_available_profiles(self):
        try:
            return self.main_app.get_available_profiles()
        except Exception:
            return [self.get_active_profile_name()]

    def switch_profile_from_bot(self, chat_id, target_profile):
        target_profile = str(target_profile or "").strip()
        if not target_profile:
            if self.bot:
                self.bot.send_message(chat_id, "❌ Bác chưa chọn tài khoản đích.")
            return

        def do_switch():
            try:
                current_profile = self.get_active_profile_name()
                if target_profile == current_profile:
                    self.bot.send_message(chat_id, f"ℹ️ Bot đang đứng sẵn ở tài khoản {current_profile} rồi sếp.")
                    return

                self.main_app.switch_profile(target_profile, show_notice=False)
                self.clear_sessions()
                self.bot.send_message(chat_id, f"✅ Đã chuyển bot sang tài khoản {target_profile} thành công.")
            except Exception as exc:
                self.bot.send_message(chat_id, f"❌ Không đổi được tài khoản: {exc}")

        if hasattr(self.main_app, 'root') and self.main_app.root:
            self.main_app.root.after(0, do_switch)
        else:
            do_switch()

    def rename_profile_from_bot(self, chat_id, old_profile, new_profile_name):
        def do_rename():
            try:
                ok, msg = self.main_app.rename_profile(old_profile, new_profile_name)
                self.clear_sessions()
                prefix = "✅" if ok else "❌"
                self.bot.send_message(chat_id, f"{prefix} {msg}")
            except Exception as exc:
                self.bot.send_message(chat_id, f"❌ Không đổi tên được tài khoản: {exc}")

        if hasattr(self.main_app, 'root') and self.main_app.root:
            self.main_app.root.after(0, do_rename)
        else:
            do_rename()

    def clear_sessions(self):
        with self.session_lock:
            self.bot_sessions.clear()

    def stop_telegram_bot(self):
        if self.bot:
            try: self.bot.stop_polling()
            except: pass
        self.clear_sessions()
        self.bot_is_running = False
        self.main_app.bot_is_running = False 

    def restart_telegram_bot(self):
        self.stop_telegram_bot()
        time.sleep(1)
        self.start_telegram_bot()

    def get_bot_stats(self):
        import os, csv
        from datetime import datetime
        from main import EXCEL_LOG_FILE
        
        total = today = da_chuyen = chua_chuyen = 0
        today_str = datetime.now().strftime('%d/%m/%Y')
        excel_file = EXCEL_LOG_FILE 
        
        raw_lines = []
        
        if os.path.exists(excel_file):
            try:
                with open(excel_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    next(reader, None) 
                    for row in reader:
                        if not row or len(row) < 4: continue
                        
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
        """Đọc sổ Excel để lấy chính xác số lần từng Voice đã bị đem ra sử dụng"""
        from main import EXCEL_LOG_FILE
        import os, csv
        usage = {}
        if os.path.exists(EXCEL_LOG_FILE):
            try:
                with open(EXCEL_LOG_FILE, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    next(reader, None) 
                    for row in reader:
                        if len(row) >= 3:
                            key = f"{row[1].strip()}_{row[2].strip()}"
                            usage[key] = usage.get(key, 0) + 1
            except: pass
        return usage
    

    def start_telegram_bot(self):
        if self.bot_is_running:
            print("⚠️ Bot đang chạy rồi, từ chối khởi động đúp!")
            return

        token = self.main_app.config.get("telegram_bot_token", "")
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
                "Sếp cần em giúp gì nào? Đây là các lệnh để điều khiển dàn máy ở nhà:\n\n"
                "📁 /projects - Xem danh sách và bật/tắt Project.\n"
                "🏛️ /account - Đổi tài khoản làm việc ngay trên bot.\n"
                "✏️ /renameaccount - Đổi tên tài khoản hiện tại.\n"
                "🚀 /menu (hoặc /render) - Chọn 1 dự án để lên đơn làm video.\n"
                "📚 /multimenu - Chọn NHIỀU dự án cùng lúc để bốc Voice tự động.\n"
                "🎲 /autobatch - Bốc random TẤT CẢ dự án mỗi nơi vài Voice.\n"
                "📦 /files - Vào kho xem video & trạng thái.\n"
                "☁️ /icloud - Đồng bộ toàn bộ hàng mới sang iCloud.\n"
                "🧹 /clean - Dọn dẹp video cũ trên iCloud.\n"
                "🌐 /web - Bật/Tắt Trạm phát sóng LAN để tải video.\n"
                "💡 *Mẹo nhỏ:* Ở lệnh /projects, sếp cứ gõ số thứ tự (1, 2, 3...) là cúp điện (đóng băng) hoặc mở khóa project ngay lập tức, không cần gõ chữ đâu nha!"
            )
            self.bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

        # =======================================================
        # 2. LỆNH: MENU TƯƠNG TÁC ĐÓNG BĂNG PROJECT BẰNG SỐ
        # =======================================================
        @self.bot.message_handler(commands=['projects', 'toggle'])
        def list_and_toggle_projects(message):
            if not self.main_app.projects:
                return self.bot.send_message(message.chat.id, "❌ Kho chưa có Project nào!")

            current_profile = self.get_active_profile_name()
            sorted_projects = sorted(self.main_app.projects.items(), key=lambda x: x[1]['created_at'], reverse=True)
            msg = f"📁 DANH SÁCH PROJECT - TK {current_profile}:\n\n"
            for idx, (pid, pdata) in enumerate(sorted_projects, 1):
                status = "🟢 Đang mở" if pdata.get('status', 'active') == 'active' else "🔴 Đã Đóng Băng"
                msg += f"{idx}. {pdata['name']} [{status}]\n"

            msg += "\n👉 Nhập MỘT SỐ THỨ TỰ (VD: 1, 2 hoặc 3) để Đóng/Mở băng. (Nhập chữ bất kỳ để hủy)"
            sent_msg = self.bot.send_message(message.chat.id, msg)
            self.bot.register_next_step_handler(sent_msg, process_toggle_step, sorted_projects, current_profile)

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

        @self.bot.message_handler(commands=['web', 'server'])
        def handle_web_server(message):
            chat_id = message.chat.id
            is_currently_on = hasattr(self.main_app.tab4, 'httpd') and self.main_app.tab4.httpd is not None
            
            if is_currently_on:
                self.bot.send_message(chat_id, "⏳ Sếp đợi em xíu, em đang sập cầu dao Trạm phát sóng...")
            else:
                self.bot.send_message(chat_id, "⏳ Sếp đợi em xíu, em đang dọn kho và bật Trạm phát sóng...")
                
            self.main_app.root.after(0, lambda: self.main_app.tab4.toggle_web_server(bot=self.bot, chat_id=chat_id))

        def process_toggle_step(message, sorted_projects, profile_name):
            text = message.text.strip()
            if not text.isdigit():
                return self.bot.send_message(message.chat.id, "✅ Đã hủy thao tác.")

            idx = int(text) - 1 
            if idx < 0 or idx >= len(sorted_projects):
                return self.bot.send_message(message.chat.id, "❌ Số không hợp lệ. Đã hủy thao tác.")

            target_pid, pdata = sorted_projects[idx]
            current = pdata.get('status', 'active')
            new_status = 'disabled' if current == 'active' else 'active'

            if profile_name == self.get_active_profile_name():
                if target_pid in self.main_app.projects:
                    self.main_app.projects[target_pid]['status'] = new_status
                    self.main_app.save_projects()
                    self.main_app.root.after(0, self.main_app.tab1.refresh_project_list)
                    self.main_app.root.after(0, self.main_app.tab2.update_combo_projects)
            else:
                projects_data = self.main_app.load_projects_for_profile(profile_name)
                if target_pid in projects_data:
                    projects_data[target_pid]['status'] = new_status
                    self.main_app.save_projects_for_profile(profile_name, projects_data)

            state_str = "🟢 ĐÃ MỞ KHÓA" if new_status == 'active' else "🔴 ĐÃ ĐÓNG BĂNG"
            self.bot.send_message(message.chat.id, f"✅ {state_str} project trong tài khoản {profile_name}:\n👉 {pdata['name']}")


        # =======================================================
        # CÁC LỆNH KHÁC CỦA SẾP
        # =======================================================
        @self.bot.message_handler(commands=['files', 'kho'])
        def handle_view_files(message):
            chat_id = message.chat.id
            self.bot.send_chat_action(chat_id, 'typing')
            output_dir = self.get_live_output_dir()
            current_profile = self.get_active_profile_name()
            if not os.path.exists(output_dir): return self.bot.send_message(chat_id, "❌ Em không tìm thấy thư mục kho hàng!")

            video_files = [f for f in os.listdir(output_dir) if f.lower().endswith('.mp4')]
            if not video_files: return self.bot.send_message(chat_id, f"🏜️ Kho hàng của tài khoản {current_profile} đang trống trơn sếp ạ!")

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
                        if "Đã chuyển" in line: stt = "Đã chuyển"
                        elif "Chưa chuyển" in line: stt = "Chưa chuyển"
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
            if not session or 'file_map' not in session: return

            try:
                choices = [int(x.strip()) - 1 for x in text.split(',')]
                # ✅ Bounds check - tránh IndexError
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
                icloud_dir = self.main_app.config.get("icloud_path", "")
                folder_name = f"Auto_iCloud_{datetime.now().strftime('%d%m%Y_%H%M')}"
                target_dir = os.path.join(icloud_dir, folder_name)
                os.makedirs(target_dir, exist_ok=True)
                
                success_count = 0
                output_dir = session.get('output_dir', self.get_live_output_dir())
                for target_file in target_files:
                    file_path = os.path.join(output_dir, target_file)
                    if os.path.exists(file_path):
                        target_path = os.path.join(target_dir, f"[{datetime.now().strftime('%Y%m%d_%H%M')}]_{target_file}")
                        shutil.copy2(file_path, target_path)
                        
                        try: self.main_app.tab4.update_excel_status(file_path, "Đã chuyển")
                        except: pass
                        success_count += 1
                
                try: self.main_app.tab4.load_excel_data()
                except: pass
                
                self.bot.send_message(chat_id, f"✅ **Xong rồi sếp ơi!** Đã đẩy thành công {success_count}/{len(target_files)} file vào iCloud mục `{folder_name}`.")
            except Exception as e:
                print(f"⚠️ Lỗi process_file_delivery copy: {e}")
                self.bot.send_message(chat_id, f"❌ Lỗi copy vào iCloud: {str(e)[:50]}")
            finally:
                # 🧹 Cleanup session
                with self.session_lock:
                    self.bot_sessions.pop(chat_id, None)

        @self.bot.message_handler(commands=['autobatch', 'random'])
        def handle_auto_batch(message):
            chat_id = message.chat.id
            self.bot.send_message(chat_id, "🎲 Dạ sếp! Em đang soi sổ Excel để bốc ưu tiên các Voice ÍT DÙNG NHẤT đây...")
            
            voice_usage_db = self.get_voice_usage()
            render_queue = [] 
            
            for pid, pdata in self.main_app.projects.items():
                pname = pdata.get('name', 'Unknown')
                pdir = self.main_app.get_proj_dir(pid)
                vdir = os.path.join(pdir, "Voices")
                
                if os.path.exists(vdir):
                    voices = [f for f in os.listdir(vdir) if f.lower().endswith(('.mp3', '.wav'))]
                    if voices:
                        # Sắp xếp theo usage (ít dùng trước), lấy top 5 voice
                        voices_sorted = sorted(voices, key=lambda v: voice_usage_db.get(f"{pname}_{v}", 0))
                        top_voices = voices_sorted[:min(5, len(voices_sorted))]
                        random.shuffle(top_voices)
                        
                        num_to_pick = min(2, len(top_voices))
                        for chosen_voice in top_voices[:num_to_pick]:
                            render_queue.append((chosen_voice, pdir, pname))
                            voice_usage_db[f"{pname}_{chosen_voice}"] = voice_usage_db.get(f"{pname}_{chosen_voice}", 0) + 1

            if not render_queue: return self.bot.send_message(chat_id, "❌ Kho voice nhà mình trống trơn chưa có file nào sếp ơi!")
            
            self.bot.send_message(chat_id, f"🚀 ĐÃ GOM ĐƯỢC {len(render_queue)} BÀI (Ưu tiên Voice mới/Random)!\nEm tống hết vào máy nổ luồng luôn nha sếp. 🏃‍♀️💨")

            def process_mixed_queue():
                completed = 0
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.main_app.config.get("threads", 2)) as executor:
                    futures = []
                    for item in render_queue:
                        futures.append(executor.submit(self.main_app.tab2._process_single, item[0], item[1], item[2]))
                        # THUẬT TOÁN CHỐNG KẸT: Đợi 1.5s trước khi nổ luồng tiếp theo
                        time.sleep(1.5)
                        
                    for future in concurrent.futures.as_completed(futures):
                        try: 
                            future.result()
                            completed += 1
                        except: pass
                self.bot.send_message(chat_id, f"🎉 DẠ XONG! Chuyến xe Random đã xuất xưởng {completed}/{len(render_queue)} video.\nSếp gõ /icloud để nhận hàng nhé!")
                try:
                    self.main_app.tab4.load_excel_data()
                except Exception as e:
                    print(f"⚠️ Lỗi load_excel_data: {e}")
                
            threading.Thread(target=process_mixed_queue, daemon=True).start()

        @self.bot.message_handler(commands=['multimenu', 'chonnhieu'])
        def handle_multi_menu(message):
            chat_id = message.chat.id
            if not self.main_app.projects: return self.bot.send_message(chat_id, "❌ Kho trống trơn sếp ơi!")
            
            current_profile = self.get_active_profile_name()
            proj_list = [(pid, p.get('name')) for pid, p in self.main_app.projects.items()]
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
            if not sess or 'proj_list' not in sess: return

            try:
                choices = [int(x.strip()) - 1 for x in text.split(',')]
                # ✅ Bounds check - tránh IndexError
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
                pdir = self.main_app.get_proj_dir(pid, profile_name)
                vdir = os.path.join(pdir, "Voices")
                if os.path.exists(vdir):
                    voices = [f for f in os.listdir(vdir) if f.lower().endswith(('.mp3', '.wav'))]
                    if voices:
                        # Sắp xếp theo usage (ít dùng trước), lấy top 5 voice
                        voices_sorted = sorted(voices, key=lambda v: voice_usage_db.get(f"{proj_name}_{v}", 0))
                        top_voices = voices_sorted[:min(5, len(voices_sorted))]
                        random.shuffle(top_voices)
                        
                        num_to_pick = min(random.randint(2, 3), len(top_voices))
                        picked_count = 0
                        
                        for chosen_voice in top_voices[:num_to_pick]:
                            render_queue.append((chosen_voice, pdir, proj_name))
                            voice_usage_db[f"{proj_name}_{chosen_voice}"] = voice_usage_db.get(f"{proj_name}_{chosen_voice}", 0) + 1
                            picked_count += 1
                            
                        msg_log += f"✅ `{proj_name}`: Đã ép nổ {picked_count} video.\n"
                    else:
                        msg_log += f"⚠️ `{proj_name}`: Thư mục chưa copy âm thanh, bỏ qua!\n"
                else:
                    msg_log += f"⚠️ `{proj_name}`: Không có thư mục Voices, bỏ qua!\n"

            if not render_queue:
                return self.bot.send_message(chat_id, msg_log + "\n❌ Túm lại là không bốc được cái voice nào sếp ạ!")

            self.bot.send_message(chat_id, msg_log + f"\n🚀 **TỔNG CỘNG ĐÃ GOM {len(render_queue)} BÀI!**\nEm tống hết vào máy nổ luồng luôn nha sếp! 🏃‍♀️💨", parse_mode="Markdown")

            def process_mixed_queue():
                completed = 0
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.main_app.config.get("threads", 2)) as executor:
                    futures = []
                    for item in render_queue:
                        futures.append(executor.submit(self.main_app.tab2._process_single, item[0], item[1], item[2]))
                        # THUẬT TOÁN CHỐNG KẸT: Đợi 1.5s trước khi nổ luồng tiếp theo
                        time.sleep(1.5)
                        
                    for future in concurrent.futures.as_completed(futures):
                        try: 
                            future.result()
                            completed += 1
                        except: pass
                
                self.bot.send_message(chat_id, f"🎉 DẠ XONG! Chuyến xe Multi-Project đã xuất xưởng {completed}/{len(render_queue)} video.\nSếp gõ /icloud để nhận hàng nhé!")
                try:
                    self.main_app.tab4.load_excel_data()
                except Exception as e:
                    print(f"⚠️ Lỗi load_excel_data: {e}")

            threading.Thread(target=process_mixed_queue, daemon=True).start()
            
        # --- BẮT TỪ KHÓA ---
        @self.bot.message_handler(func=lambda message: not message.text.startswith('/') and any(kw in message.text.lower() for kw in ['dọn dẹp', 'xóa rác']))
        def natural_clean(message): handle_clean_icloud(message)
        @self.bot.message_handler(func=lambda message: not message.text.startswith('/') and any(kw in message.text.lower() for kw in ['làm video', 'lên đơn', 'menu']))
        def natural_menu(message): handle_menu(message)
        @self.bot.message_handler(func=lambda message: not message.text.startswith('/') and any(kw in message.text.lower() for kw in ['vào kho', 'lấy file', 'trạng thái']))
        def natural_files(message): handle_view_files(message)
        @self.bot.message_handler(func=lambda message: not message.text.startswith('/') and any(kw in message.text.lower() for kw in ['đồng bộ', 'đẩy lên', 'sync']))
        def natural_icloud(message): handle_sync_icloud(message)
        @self.bot.message_handler(func=lambda message: not message.text.startswith('/') and any(kw in message.text.lower() for kw in ['đổi tài khoản', 'chuyển tài khoản', 'đổi profile']))
        def natural_account(message): handle_account_switch(message)
        @self.bot.message_handler(func=lambda message: not message.text.startswith('/') and any(kw in message.text.lower() for kw in ['đổi tên tài khoản', 'sửa tên tài khoản', 'đổi tên profile']))
        def natural_rename_account(message): handle_account_rename(message)
        @self.bot.message_handler(func=lambda message: not message.text.startswith('/') and any(kw in message.text.lower() for kw in ['chạy random', 'bốc ngẫu nhiên', 'chạy tự động']))
        def natural_autobatch(message): handle_auto_batch(message)
        @self.bot.message_handler(func=lambda message: not message.text.startswith('/') and any(kw in message.text.lower() for kw in ['chạy nhiều', 'chọn nhiều', 'chạy lô']))
        def natural_multimenu(message): handle_multi_menu(message)

        @self.bot.message_handler(commands=['clean', 'dondep'])
        def handle_clean_icloud(message):
            chat_id = message.chat.id
            icloud_dir = self.main_app.config.get("icloud_path", "")
            if not icloud_dir: 
                return self.bot.send_message(chat_id, "❌ Em chưa thấy thư mục iCloud ở nhà.")
                
            folders_to_delete = [os.path.join(icloud_dir, item) for item in os.listdir(icloud_dir) if (item.startswith("Video_Xuat") or item.startswith("Auto_iCloud")) and os.path.isdir(os.path.join(icloud_dir, item))]
            
            if not folders_to_delete: 
                return self.bot.send_message(chat_id, "✨ iCloud nhà mình đang sạch bong sếp ơi!")
                
            with self.session_lock:
                self.bot_sessions[chat_id] = {'folders_to_delete': folders_to_delete}
            msg_sent = self.bot.send_message(chat_id, f"🧹 TÌM THẤY {len(folders_to_delete)} LÔ HÀNG CŨ!\nSếp nhắn chữ: **XOA** để em phi tang nhé.")
            
            def confirm_clean(m):
                if m.text.strip().upper() == "XOA":
                    deleted = 0
                    for f in folders_to_delete:
                        try:
                            shutil.rmtree(f)
                            deleted += 1
                        except: pass
                    self.bot.send_message(chat_id, f"Đã dọn dẹp xong {deleted} thư mục rác! 🗑️")
                else:
                    self.bot.send_message(chat_id, "Đã hủy dọn dẹp, hàng họ vẫn còn nguyên sếp nhé!")
                # 🧹 Cleanup session
                with self.session_lock:
                    self.bot_sessions.pop(chat_id, None)
                    
            self.bot.register_next_step_handler(msg_sent, confirm_clean)

        @self.bot.message_handler(commands=['menu', 'render'])
        def handle_menu(message):
            chat_id = message.chat.id
            if not self.main_app.projects: return self.bot.send_message(chat_id, "Kho trống trơn sếp ơi!")
            current_profile = self.get_active_profile_name()
            proj_list = [(pid, p.get('name')) for pid, p in self.main_app.projects.items()]
            msg = f"📁 **Dự án nhà mình - {current_profile}:**\n" + "".join([f" {i}. {n}\n" for i, (p, n) in enumerate(proj_list, 1)]) + "\n👇 Sếp nhắn **số thứ tự** Project nhé:"
            with self.session_lock:
                self.bot_sessions[chat_id] = {'proj_list': proj_list, 'profile_name': current_profile}
            self.bot.register_next_step_handler(self.bot.send_message(chat_id, msg, parse_mode="Markdown"), process_project_choice)

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
            pdir = self.main_app.get_proj_dir(pid, profile_name); vdir = os.path.join(pdir, "Voices")
            voices = [f for f in os.listdir(vdir) if f.lower().endswith(('.mp3', '.wav'))] if os.path.exists(vdir) else []
            if not voices: return self.bot.send_message(chat_id, f"Không có voice nào trong {proj_name}!")
            
            with self.session_lock:
                self.bot_sessions[chat_id].update({'pid': pid, 'proj_name': proj_name, 'voice_map': voices, 'proj_dir': pdir})
            
            # --- CẬP NHẬT: HIỆN DANH SÁCH VOICE RÕ RÀNG ---
            msg = f"🎧 **Dự án `{proj_name}` đang có {len(voices)} file âm thanh:**\n\n"
            for i, v in enumerate(voices, 1):
                msg += f" {i}. `{v}`\n"
            msg += "\n👇 Sếp chốt số mấy? (Nhắn các số cách nhau bằng dấu phẩy VD: 1,3)"
            self.bot.register_next_step_handler(self.bot.send_message(chat_id, msg, parse_mode="Markdown"), process_voice_choice)

        def process_voice_choice(message):
            chat_id = message.chat.id
            with self.session_lock:
                sess = self.bot_sessions.get(chat_id)
            if not sess or 'voice_map' not in sess:
                return self.bot.send_message(chat_id, "❌ Session hết hạn, gõ lại lệnh /menu nhé!")
            try:
                choices = [int(x.strip()) - 1 for x in message.text.split(',')]
                # ✅ Bounds check - tránh IndexError
                if any(i < 0 or i >= len(sess['voice_map']) for i in choices):
                    return self.bot.send_message(chat_id, "❌ Số không hợp lệ sếp ơi!")
                selected = [sess['voice_map'][i] for i in choices]
            except ValueError:
                return self.bot.send_message(chat_id, "Sai cú pháp!")
            except Exception as e:
                print(f"⚠️ Lỗi process_voice_choice: {e}")
                return self.bot.send_message(chat_id, f"❌ Lỗi: {str(e)[:50]}")
            
            self.bot.send_message(chat_id, f"🚀 Bắt đầu xào nấu {len(selected)} video!")
            
            # --- CẬP NHẬT: ĐA LUỒNG CÓ THẢ CỬA NGẮT QUÃNG 1.5 GIÂY ---
            def run_menu_batch():
                completed = 0
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.main_app.config.get("threads", 2)) as executor:
                    futures = []
                    for v in selected:
                        futures.append(executor.submit(self.main_app.tab2._process_single, v, sess['proj_dir'], sess['proj_name']))
                        time.sleep(1.5) # Cứu tinh chống kẹt file
                    
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            future.result()
                            completed += 1
                        except: pass
                        
                self.bot.send_message(chat_id, f"🎉 DẠ XONG đơn của sếp ({completed}/{len(selected)} video)!")
                try:
                    self.main_app.tab4.load_excel_data()
                except Exception as e:
                    print(f"⚠️ Lỗi load_excel_data: {e}")
                finally:
                    # 🧹 Cleanup session
                    with self.session_lock:
                        self.bot_sessions.pop(chat_id, None)
                
            threading.Thread(target=run_menu_batch, daemon=True).start()

        @self.bot.message_handler(commands=['icloud', 'sync'])
        def handle_sync_icloud(message):
            self.bot.reply_to(message, "Dạ rõ! Đang ném vào iCloud cho sếp... 📦💨")
            threading.Thread(target=self.main_app.tab4.auto_sync_icloud, args=(self.bot, message.chat.id), daemon=True).start()

        @self.bot.message_handler(func=lambda message: not message.text.startswith('/'))
        def handle_free_chat(message):
            chat_id = message.chat.id
            user_text = message.text
            groq_key = self.main_app.config.get("groq_key", "").strip()
            if not groq_key: return self.bot.reply_to(message, "Sếp ơi chưa có Key Llama 3.3 ở Tab 2!")
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
                    
                    payload = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_text}], "temperature": 0.7}
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

        def run_bot():
            self.bot_is_running = True
            self.main_app.bot_is_running = True 
            try:
                print("🤖 Thư ký AI đã lên sóng (Đã có Menu Đóng Băng)...")
                self.bot.infinity_polling()
            except Exception as e: print(f"Lỗi Bot: {e}")
            self.bot_is_running = False
            self.main_app.bot_is_running = False 

        import threading
        threading.Thread(target=run_bot, daemon=True).start()