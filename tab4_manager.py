import os
import csv
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import shutil
import unicodedata
from datetime import datetime
import socket
import threading
import http.server
import socketserver

from shopee_export import delete_shopee_jobs

class ManagerTab:
    def __init__(self, parent, main_app):
        self.parent = parent
        self.main_app = main_app
        self.setup_ui()
        
        # Hẹn giờ 100ms nạp dữ liệu ngay khi vừa bật phần mềm
        self.parent.after(100, self.load_excel_data)

    def setup_ui(self):
        # 1. CĂN CHỈNH LẠI FONT CHỮ CHO BẢNG TREEVIEW
        style = ttk.Style()
        style.theme_use("clam")
        
        style.configure("Treeview", font=("Arial", 11), rowheight=35, background="#ffffff", fieldbackground="#ffffff", foreground="#2c3e50")
        style.configure("Treeview.Heading", font=("Arial", 12, "bold"), background="#34495e", foreground="white")
        style.map("Treeview", background=[("selected", "#3498db")], foreground=[("selected", "white")])

        tk.Label(
            self.parent, 
            text="📊 QUẢN LÝ THÀNH PHẨM & TRẠNG THÁI XUẤT XƯỞNG", 
            font=("Arial", 15, "bold"), 
            bg="#f4f6f9", 
            fg="#2980b9"
        ).pack(pady=(20, 10))

        # 2. KHUNG BẢNG TREEVIEW
        table_frame = tk.Frame(self.parent, bg="#ffffff", bd=1, relief="solid")
        table_frame.pack(fill="both", expand=True, padx=20, pady=5)

        cols = ("Date", "Project", "Voice", "Path", "Status")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="extended")
        
        self.tree.heading("Date", text="Ngày Tạo")
        self.tree.heading("Project", text="Tên Project")
        self.tree.heading("Voice", text="File Voice")
        self.tree.heading("Path", text="Đường Dẫn")
        self.tree.heading("Status", text="Trạng Thái")

        self.tree.column("Date", width=140, anchor="center")
        self.tree.column("Project", width=250, anchor="w")
        self.tree.column("Voice", width=200, anchor="w")
        self.tree.column("Path", width=350, anchor="w")
        self.tree.column("Status", width=130, anchor="center")

        # THIẾT LẬP MÀU TRẠNG THÁI
        self.tree.tag_configure("done", foreground="#27ae60", font=("Arial", 11, "bold"))    
        self.tree.tag_configure("pending", foreground="#000000", font=("Arial", 11))         

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # KÉO CHUỘT ĐỂ BÔI ĐEN
        self.tree.bind("<B1-Motion>", self.drag_to_select)

        # MENU CHUỘT PHẢI
        self.context_menu = tk.Menu(self.parent, tearoff=0, font=("Arial", 11))
        self.context_menu.add_command(label="▶ Xem Video này", command=self.open_video)
        self.context_menu.add_command(label="☁️ Gửi iPhone (Các video đang bôi đen)", command=self.send_selected_to_iphone)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🗑️ Xóa sạch khỏi máy", command=self.delete_video)
        
        self.tree.bind("<Button-3>", self.show_context_menu)

        # 3. THANH CÔNG CỤ PHÍA DƯỚI
        btn_frame = tk.Frame(self.parent, bg="#f4f6f9")
        btn_frame.pack(fill="x", padx=20, pady=10)
        
        tk.Button(
            btn_frame, 
            text="🚀 GỬI IPHONE HÀNG LOẠT", 
            bg="#0984e3", 
            fg="white", 
            font=("Arial", 12, "bold"), 
            padx=20, 
            pady=5,
            command=self.send_selected_to_iphone
        ).pack(side="left")

        # =======================================================
        # [MỚI] NÚT BẬT TRẠM PHÁT SÓNG WIFI NỘI BỘ
        # =======================================================
        self.btn_web = tk.Button(
            btn_frame, 
            text="🌐 Bật Web Server (LAN)", 
            bg="#8e44ad", 
            fg="white", 
            font=("Arial", 11, "bold"), 
            padx=15,
            pady=5,
            command=self.toggle_web_server
        )
        self.btn_web.pack(side="left", padx=10)
        # =======================================================
        
        tk.Button(btn_frame, text="📑 Mở File Excel", bg="#636e72", fg="white", font=("Arial", 10, "bold"), command=self.open_excel).pack(side="right", padx=5)
        tk.Button(btn_frame, text="📂 Mở Kho Chứa", bg="#636e72", fg="white", font=("Arial", 10, "bold"), command=self.open_folder).pack(side="right", padx=10)
        
        tk.Label(
            btn_frame, 
            text="* Mẹo: Bác nhấp giữ chuột trái rồi kéo một đường là bôi đen được cả mảng!", 
            font=("Arial", 10, "italic"), 
            bg="#f4f6f9", 
            fg="#c0392b"
        ).pack(side="right", padx=20)


    # ================= CÁC HÀM XỬ LÝ SỰ KIỆN =================

    def drag_to_select(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_add(item)

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def load_excel_data(self):
        """Đọc file Excel và nhồi vào bảng - BỎ QUÉT FILE RÁC & TỰ TẠO TIÊU ĐỀ"""
        from main import EXCEL_LOG_FILE
        import os, csv
        
        # 1. Xóa sạch bảng UI để chuẩn bị load lại
        for item in self.tree.get_children(): 
            self.tree.delete(item)
            
        # 2. CHỐT CHẶN TIÊU ĐỀ: Nếu file chưa có hoặc bị xóa trắng, tự động tạo file và nạp Tên Cột vào
        header = ["Ngày Tạo", "Tên Project", "File Voice", "Đường Dẫn", "Trạng Thái"]
        if not os.path.exists(EXCEL_LOG_FILE) or os.path.getsize(EXCEL_LOG_FILE) == 0:
            with open(EXCEL_LOG_FILE, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                
        # 3. Đọc dữ liệu từ sổ lên giao diện
        try:
            with open(EXCEL_LOG_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                next(reader, None) # Bỏ qua dòng tiêu đề lúc hiển thị lên UI
                
                rows = list(reader)
                rows.reverse() # Lật ngược lại để video mới nhất nảy lên trên cùng
                
                for r in rows:
                    if len(r) >= 4: # Có trong sổ Excel là hiện hết lên Tool
                        status = r[4] if len(r) > 4 else "Chưa chuyển"
                        tag = "done" if status == "Đã chuyển" else "pending"
                        self.tree.insert("", "end", values=(r[0], r[1], r[2], r[3], status), tags=(tag,))
        except Exception as e: 
            print("Lỗi load bảng:", e)
            
    def open_video(self):
        selected = self.tree.selection()
        if not selected: 
            return
        path = self.tree.item(selected[0])['values'][3]
        if os.path.exists(path): 
            os.startfile(path)

    def send_selected_to_iphone(self):
        selected_items = self.tree.selection()
        
        if not selected_items:
            messagebox.showwarning("Chú ý", "Bác phải bôi đen các video muốn chuyển đã chứ!")
            return

        icloud_dir = self.main_app.config.get("icloud_path", "")
        
        if not icloud_dir or not os.path.exists(icloud_dir):
            icloud_dir = filedialog.askdirectory(title="Chọn thư mục iCloud Drive")
            if not icloud_dir: 
                return
            self.main_app.config["icloud_path"] = icloud_dir
            self.main_app.save_config()

        folder_timestamp = datetime.now().strftime("%d%m%Y_%H%M") 
        folder_name = f"Video_Xuat_Tu_Tool_{folder_timestamp}"
        target_dir = os.path.join(icloud_dir, folder_name)
        os.makedirs(target_dir, exist_ok=True)
        
        success_count = 0
        file_timestamp = datetime.now().strftime("%Y%m%d_%H%M") 

        # ========================================================
        # [MỚI] ÉP IPHONE XẾP XEN KẼ VIDEO
        # ========================================================
        import random
        # Chuyển tuple sang list để xáo trộn
        items_list = list(selected_items)
        random.shuffle(items_list)

        # Dùng enumerate để sinh số thứ tự (1, 2, 3...)
        for idx, item_id in enumerate(items_list, 1):
            values = list(self.tree.item(item_id)['values'])
            path = values[3]
            
            if os.path.exists(path):
                original_name = os.path.basename(path)
                # Đắp thêm số thứ tự {idx:02d} (vd: 01, 02, 03) vào tên file
                new_name = f"{idx:02d}_[{file_timestamp}]_{original_name}"
                target_path = os.path.join(target_dir, new_name)
                
                try:
                    shutil.copy2(path, target_path)
                    self.update_excel_status(path, "Đã chuyển")
                    success_count += 1
                except Exception as e: 
                    print(f"Lỗi khi copy {original_name}: {e}")
                    continue
        
        self.load_excel_data() 
        messagebox.showinfo("Thành công", f"Báo cáo sếp: Đã tạo thư mục '{folder_name}' và bắn {success_count} video đã xáo trộn vào đó an toàn!")

    def auto_sync_icloud(self, bot=None, chat_id=None):
        from main import EXCEL_LOG_FILE
        if not os.path.exists(EXCEL_LOG_FILE): return
        
        icloud_dir = self.main_app.config.get("icloud_path", "")
        if not icloud_dir or not os.path.exists(icloud_dir):
            if bot and chat_id:
                bot.send_message(chat_id, "❌ Lỗi: PC chưa cài đặt thư mục iCloud! Bác hãy mở Tool trên máy tính, chuyển thử 1 video để cài đặt thư mục trước nhé.")
            return

        pending_files = []
        try:
            with open(EXCEL_LOG_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                next(reader, None)
                for r in reader:
                    if len(r) >= 4 and os.path.exists(r[3]):
                        status = r[4] if len(r) > 4 else "Chưa chuyển"
                        if status != "Đã chuyển":
                            pending_files.append(r[3])
        except: pass

        if not pending_files:
            if bot and chat_id:
                bot.send_message(chat_id, "🤷‍♂️ Kho không có video nào mới (Tất cả đã được chuyển rồi)!")
            return

        folder_timestamp = datetime.now().strftime("%d%m%Y_%H%M") 
        folder_name = f"Auto_iCloud_{folder_timestamp}"
        target_dir = os.path.join(icloud_dir, folder_name)
        os.makedirs(target_dir, exist_ok=True)
        
        success_count = 0
        file_timestamp = datetime.now().strftime("%Y%m%d_%H%M") 

        # ========================================================
        # [MỚI] ÉP IPHONE XẾP XEN KẼ VIDEO TỪ BOT
        # ========================================================
        import random
        random.shuffle(pending_files)

        for idx, path in enumerate(pending_files, 1):
            original_name = os.path.basename(path)
            # Gắn đầu số 01, 02... vào file
            new_name = f"{idx:02d}_[{file_timestamp}]_{original_name}"
            target_path = os.path.join(target_dir, new_name)
            try:
                shutil.copy2(path, target_path)
                self.update_excel_status(path, "Đã chuyển")
                success_count += 1
            except:
                continue
        
        try: self.main_app.root.after(0, self.load_excel_data)
        except: pass
        
        if bot and chat_id:
            bot.send_message(
                chat_id, 
                f"☁️ Đã đồng bộ và XÁO TRỘN thành công {success_count} video mới sang iCloud!\n"
                f"📂 Tên thư mục: {folder_name}\n"
                f"📱 Bác mở app Tệp (Files) trên iPhone đợi xíu là có hàng, chọn video từ trên xuống dưới là tự xen kẽ nhé!"
            )
            

    def update_excel_status(self, file_path, new_status):
        from main import EXCEL_LOG_FILE
        header = ["Ngày Tạo", "Tên Project", "File Voice", "Đường Dẫn", "Trạng Thái"]
        rows = []
        
        if os.path.exists(EXCEL_LOG_FILE):
            with open(EXCEL_LOG_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                next(reader, None) # Bỏ qua header cũ
                
                for r in reader:
                    if len(r) >= 4 and r[3] == file_path:
                        if len(r) == 4: r.append(new_status)
                        else: r[4] = new_status
                    rows.append(r)
            
            with open(EXCEL_LOG_FILE, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header) # Luôn ghi header mới lên đầu
                writer.writerows(rows)

    def delete_video(self):
        selected = self.tree.selection()
        if not selected: 
            return
        
        if not messagebox.askyesno("Xác nhận mạnh", "Bác có chắc muốn phi tang TẤT CẢ các video đang bôi đen không?"): 
            return
        
        from main import EXCEL_LOG_FILE
        deleted_paths = [self.tree.item(i)['values'][3] for i in selected]
        deleted_video_names = [os.path.basename(path) for path in deleted_paths]
        
        for path in deleted_paths:
            try:
                if os.path.exists(path): 
                    os.remove(path)
            except Exception as e: 
                print(f"Không xóa được {path}: {e}")
            
        header = ["Ngày Tạo", "Tên Project", "File Voice", "Đường Dẫn", "Trạng Thái"]
        rows = []
        if os.path.exists(EXCEL_LOG_FILE):
            with open(EXCEL_LOG_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                next(reader, None)
                for r in reader:
                    if len(r) >= 4 and r[3] not in deleted_paths: 
                        rows.append(r)
            
            with open(EXCEL_LOG_FILE, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(rows)

        try:
            delete_shopee_jobs(deleted_video_names, config=self.main_app.config)
            if hasattr(self.main_app, "tab11"):
                self.main_app.root.after(0, self.main_app.tab11.refresh_jobs_preview)
        except Exception as e:
            print(f"Không xóa được job Shopee tương ứng: {e}")
                
        self.load_excel_data()

    def open_folder(self):
        from main import GLOBAL_OUT_DIR
        if os.path.exists(GLOBAL_OUT_DIR):
            os.startfile(GLOBAL_OUT_DIR)

    def open_excel(self):
        from main import EXCEL_LOG_FILE
        if os.path.exists(EXCEL_LOG_FILE): 
            os.startfile(EXCEL_LOG_FILE)

    # ================= WEB SERVER LAN =================

    def get_local_ip(self):
        """Hàm tự động mò địa chỉ IP của máy tính sếp trong mạng Wifi"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Không cần kết nối thật, chỉ mượn đường để lấy IP
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    def toggle_web_server(self, bot=None, chat_id=None):
        """Bật/Tắt Trạm phát sóng (Bản Tối Thượng: Hỗ trợ điều khiển qua Telegram)"""
        import urllib.parse
        import html
        import os
        import csv
        import random 
        import zipfile 
        
        # HÀM PHỤ: Xử lý giao diện an toàn không bị đơ Tool
        def update_ui_and_notify(is_on, msg):
            if is_on: self.btn_web.config(text="🔴 Đang phát (Tắt Server)", bg="#c0392b")
            else: self.btn_web.config(text="🌐 Bật Web Server (LAN)", bg="#8e44ad")
            
            # Nếu Bot gọi thì nhắn qua Telegram, nếu người bấm thì hiện Messagebox
            if bot and chat_id: bot.send_message(chat_id, msg)
            else: messagebox.showinfo("Trạm Phát Sóng", msg)

        if hasattr(self, 'httpd') and self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except: pass
            self.httpd = None
            self.main_app.root.after(0, lambda: update_ui_and_notify(False, "🔌 Đã TẮT Trạm phát sóng Web Server!"))
        else:
            from main import GLOBAL_OUT_DIR, EXCEL_LOG_FILE
            abs_dir = os.path.abspath(GLOBAL_OUT_DIR)
            os.makedirs(abs_dir, exist_ok=True)
            
            PORT = 8000
            tab_instance = self 
            
            class MyHttpRequestHandler(http.server.SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=abs_dir, **kwargs)

                # Bùa bịt miệng chống Crash khi chạy file .exe có --noconsole
                def log_message(self, format, *args): pass

                def end_headers(self):
                    if '?action=download' in self.path:
                        raw_filename = urllib.parse.unquote(os.path.basename(self.path.split('?')[0]))
                        safe_filename = urllib.parse.quote(raw_filename)
                        self.send_header('Content-Disposition', f"attachment; filename*=UTF-8''{safe_filename}")
                    super().end_headers()

                def do_GET(self):
                    parsed_path = urllib.parse.urlparse(self.path)
                    
                    if parsed_path.path == '/download_all':
                        mp4_files = [f for f in os.listdir(abs_dir) if f.lower().endswith('.mp4')]
                        if mp4_files:
                            random.shuffle(mp4_files)
                            zip_path = os.path.join(abs_dir, "Tong_Hop_Video.zip")
                            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zipf:
                                for idx, f_name in enumerate(mp4_files, 1):
                                    random_name_in_zip = f"{idx:03d}_{f_name}"
                                    zipf.write(os.path.join(abs_dir, f_name), random_name_in_zip)
                                    f_path = os.path.normpath(os.path.join(abs_dir, f_name))
                                    tab_instance.update_excel_status(f_path, "Đã chuyển")
                            try: tab_instance.main_app.root.after(0, tab_instance.load_excel_data)
                            except: pass
                        self.send_response(200)
                        self.send_header('Content-type', 'text/plain')
                        self.end_headers()
                        self.wfile.write(b"OK")
                        return

                    if parsed_path.path == '/mark_done':
                        query = urllib.parse.parse_qs(parsed_path.query)
                        if 'file' in query:
                            file_name = query['file'][0]
                            file_path = os.path.normpath(os.path.join(abs_dir, file_name))
                            tab_instance.update_excel_status(file_path, "Đã chuyển")
                            try: tab_instance.main_app.root.after(0, tab_instance.load_excel_data)
                            except: pass
                        self.send_response(200)
                        self.send_header('Content-type', 'text/plain')
                        self.end_headers()
                        self.wfile.write(b"OK")
                        return

                    if parsed_path.path == '/delete_file':
                        query = urllib.parse.parse_qs(parsed_path.query)
                        if 'file' in query:
                            file_name = query['file'][0]
                            file_path = os.path.normpath(os.path.join(abs_dir, file_name))
                            try:
                                if os.path.exists(file_path): os.remove(file_path)
                            except: pass
                            if os.path.exists(EXCEL_LOG_FILE):
                                try:
                                    with open(EXCEL_LOG_FILE, 'r', encoding='utf-8-sig') as f:
                                        reader = csv.reader(f)
                                        header = next(reader, None)
                                        rows = [r for r in reader if len(r) >= 4 and r[3] != file_path]
                                    with open(EXCEL_LOG_FILE, 'w', encoding='utf-8-sig', newline='') as f:
                                        writer = csv.writer(f)
                                        if header: writer.writerow(header)
                                        writer.writerows(rows)
                                except: pass
                            try: tab_instance.main_app.root.after(0, tab_instance.load_excel_data)
                            except: pass
                        self.send_response(200)
                        self.send_header('Content-type', 'text/plain')
                        self.end_headers()
                        self.wfile.write(b"OK")
                        return

                    if parsed_path.path == '/' or parsed_path.path == '':
                        try: file_list = os.listdir(abs_dir)
                        except OSError:
                            self.send_error(404, "Không đọc được thư mục")
                            return

                        mp4_files = [f for f in file_list if f.lower().endswith('.mp4')]
                        random.shuffle(mp4_files)

                        status_map = {}
                        if os.path.exists(EXCEL_LOG_FILE):
                            try:
                                with open(EXCEL_LOG_FILE, 'r', encoding='utf-8-sig') as f:
                                    reader = csv.reader(f)
                                    next(reader, None)
                                    for r in reader:
                                        if len(r) >= 5: status_map[os.path.basename(r[3])] = r[4]
                            except: pass

                        html_code = f"""
                        <!DOCTYPE html>
                        <html lang="vi">
                        <head>
                            <meta charset="utf-8">
                            <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
                            <title>Kho Video</title>
                            <style>
                                body {{ font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif; background-color: #f0f2f5; margin: 0; padding: 15px; color: #1c1e21; }}
                                .container {{ max-width: 600px; margin: auto; }}
                                .header {{ text-align: center; margin-bottom: 20px; background: white; padding: 15px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
                                .header h2 {{ margin: 0; color: #2c3e50; font-size: 22px; }}
                                .header p {{ margin: 5px 0 15px 0; color: #e67e22; font-size: 15px; font-weight: bold; }}
                                .btn-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }}
                                .btn-shuffle {{ background: #f39c12; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: bold; font-size: 14px; cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                                .btn-download-all {{ background: #8e44ad; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: bold; font-size: 14px; cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                                .card {{ background: white; border-radius: 12px; padding: 15px; margin-bottom: 12px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); display: flex; flex-direction: column; gap: 12px; border-left: 5px solid #3498db; transition: 0.3s opacity; }}
                                .card.done-card {{ border-left: 5px solid #27ae60; opacity: 0.85; }}
                                .file-name {{ font-weight: 600; font-size: 14px; word-break: break-word; line-height: 1.4; color: #34495e; }}
                                .btn-group {{ display: flex; gap: 6px; }}
                                .btn-view {{ flex: 1.2; text-align: center; background: #e0e6ed; color: #2c3e50; border: none; padding: 10px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: bold; }}
                                .btn-mark {{ flex: 1.8; text-align: center; background: #3498db; color: white; border: none; padding: 10px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: bold; transition: 0.2s; }}
                                .btn-mark.done {{ background: #27ae60; }}
                                .btn-del {{ flex: 0.6; text-align: center; background: #e74c3c; color: white; border: none; padding: 10px; border-radius: 6px; cursor: pointer; font-size: 15px; transition: 0.2s; }}
                            </style>
                            <script>
                                function downloadAll() {{
                                    let btn = document.getElementById('btn-dl-all');
                                    btn.innerHTML = '⏳ Đang nén ZIP...'; btn.disabled = true;
                                    fetch('/download_all').then(() => {{
                                        btn.innerHTML = '✅ Đã nén xong!';
                                        window.location.href = '/Tong_Hop_Video.zip?action=download';
                                        setTimeout(() => window.location.reload(), 2000);
                                    }}).catch(() => alert('Lỗi nén file!'));
                                }}
                                function markDone(encodedFileName, btnId, cardId, downloadUrl) {{
                                    let btn = document.getElementById(btnId);
                                    btn.className = 'btn-mark done'; btn.innerHTML = '⏳ Đang lấy link...';
                                    document.getElementById(cardId).className = 'card done-card';
                                    fetch('/mark_done?file=' + encodedFileName).then(() => {{
                                        btn.innerHTML = '✅ Đã Lưu & Chốt'; window.location.href = downloadUrl;
                                    }}).catch(() => {{
                                        btn.innerHTML = '✅ Đã Lưu & Chốt'; window.location.href = downloadUrl;
                                    }});
                                }}
                                function deleteFile(encodedFileName, cardId) {{
                                    if(confirm("⚠️ Sếp muốn XÓA VĨNH VIỄN video này?")) {{
                                        let card = document.getElementById(cardId);
                                        card.style.opacity = '0.3';
                                        fetch('/delete_file?file=' + encodedFileName).then(() => card.remove());
                                    }}
                                }}
                            </script>
                        </head>
                        <body>
                            <div class="container">
                                <div class="header">
                                    <h2>🎬 KHO VIDEO CỦA SẾP</h2>
                                    <p>Tổng số: {len(mp4_files)} thành phẩm</p>
                                    <div class="btn-grid">
                                        <button class="btn-shuffle" onclick="window.location.reload()">🔀 TRỘN LỘN XỘN</button>
                                        <button id="btn-dl-all" class="btn-download-all" onclick="downloadAll()">📦 TẢI TẤT CẢ (ZIP)</button>
                                    </div>
                                </div>
                        """
                        
                        if not mp4_files:
                            html_code += """<div class="card" style="text-align: center; color: #e74c3c;">🏜️ Kho hiện đang trống! Cắm máy render thêm đi sếp.</div>"""
                        else:
                            for i, f_name in enumerate(mp4_files):
                                safe_name = html.escape(f_name)
                                url_path = urllib.parse.quote(f_name)
                                stt = status_map.get(f_name, "Chưa chuyển")
                                is_done = "Đã" in stt
                                
                                card_class = "card done-card" if is_done else "card"
                                btn_mark_class = "btn-mark done" if is_done else "btn-mark"
                                btn_mark_text = "✅ Đã Lưu & Chốt" if is_done else "⬇️ Tải Về Máy"
                                
                                html_code += f"""
                                <div class="{card_class}" id="card_{i}">
                                    <div class="file-name">📼 {safe_name}</div>
                                    <div class="btn-group">
                                        <a href="/{url_path}" class="btn-view" target="_blank">▶ Xem</a>
                                        <div id="btn_{i}" class="{btn_mark_class}" onclick="markDone('{url_path}', 'btn_{i}', 'card_{i}', '/{url_path}?action=download')">{btn_mark_text}</div>
                                        <div class="btn-del" onclick="deleteFile('{url_path}', 'card_{i}')">🗑️</div>
                                    </div>
                                </div>
                                """
                                
                        html_code += """
                            </div>
                        </body>
                        </html>
                        """
                        encoded = html_code.encode('utf-8', 'replace')
                        self.send_response(200)
                        self.send_header("Content-type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(encoded)))
                        self.end_headers()
                        self.wfile.write(encoded)
                        return
                    else:
                        super().do_GET()

            try:
                socketserver.TCPServer.allow_reuse_address = True
                self.httpd = socketserver.TCPServer(("0.0.0.0", PORT), MyHttpRequestHandler)
                ip = self.get_local_ip()
                import threading
                threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
                
                msg_success = (f"🎉 TRẠM PHÁT SÓNG ĐÃ BẬT!\n\n"
                               f"🌐 LAN Wifi: http://{ip}:{PORT}\n\n"
                               f"🚀 Nếu dùng Tailscale (4G), hãy dùng link:\n"
                               f"👉 http://desktop-su041vb:8000")
                
                self.main_app.root.after(0, lambda: update_ui_and_notify(True, msg_success))
            except Exception as e:
                self.main_app.root.after(0, lambda: update_ui_and_notify(False, f"❌ Lỗi: Không thể bật Server: {e}"))