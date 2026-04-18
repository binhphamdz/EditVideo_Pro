import os
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import threading
from datetime import datetime
import subprocess
import gc
from PIL import Image, ImageTk

# Gọi 2 thằng đệ ra làm việc
from tab1_modules.thumbnail_maker import ThumbnailHandler
from tab1_modules.ai_vision import AIVisionHandler
from tab2_modules.ai_services import get_transcription

class BRollTab:
    def __init__(self, parent, main_app):
        self.parent = parent
        self.main_app = main_app
        self.current_project_id = None
        self.photo_refs = {} 
        self.desc_entries = {} 
        self.thumb_labels = {}  # [MỚI] Dictionary lưu thumbnail labels
        self.product_link_entries = []
        
        # [MỚI] Biến lưu trữ trạng thái Checkbox
        self.check_vars_act = {} # Checkbox tab Đang dùng
        self.check_vars_tr = {}  # Checkbox tab Thùng rác
        
        # Bổ nhiệm 2 đệ tử
        self.thumb_handler = ThumbnailHandler(self)
        self.ai_handler = AIVisionHandler(self)
        
        self.setup_ui()

    def setup_ui(self):
        # =========================================================
        # CỘT TRÁI: DANH SÁCH PROJECT
        # =========================================================
        left_frame = tk.Frame(self.parent, bg="#ffffff", width=280)
        left_frame.pack(side="left", fill="y", padx=10, pady=10)
        left_frame.pack_propagate(False) 
        
        tk.Label(left_frame, text="📁 KHO PROJECT", font=("Arial", 12, "bold"), bg="#ffffff", fg="#2c3e50").pack(pady=10)
        
        self.tree_proj = ttk.Treeview(left_frame, columns=("name",), show="headings", selectmode="browse")
        self.tree_proj.heading("name", text="Tên Project")
        self.tree_proj.column("name", width=250, anchor="w")
        self.tree_proj.pack(fill="both", expand=True, padx=5, pady=5)
        self.tree_proj.bind("<<TreeviewSelect>>", self.on_select_project)
        
        tk.Button(left_frame, text="➕ TẠO PROJECT TRỐNG", bg="#27ae60", fg="white", font=("Arial", 9, "bold"), pady=8, command=self.add_project_dialog).pack(fill="x", padx=5, pady=5)
        # ... (Dưới nút Xóa Project ở Cột Trái)
        tk.Button(left_frame, text="🗑️ Xóa Project", bg="#e74c3c", fg="white", font=("Arial", 9, "bold"), command=self.delete_project).pack(fill="x", padx=5, pady=(0, 5))
        
        # [MỚI THÊM] NÚT ĐÓNG BĂNG PROJECT
        self.btn_toggle_proj = tk.Button(left_frame, text="⏸️ Đóng Băng Project", bg="#f39c12", fg="white", font=("Arial", 9, "bold"), command=self.toggle_project_status)
        self.btn_toggle_proj.pack(fill="x", padx=5, pady=(0, 5))

        # =========================================================
        # CỘT PHẢI: KHÔNG GIAN LÀM VIỆC CHÍNH
        # =========================================================
        self.right_frame = tk.Frame(self.parent, bg="#f4f6f9")
        self.right_frame.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=10)
        
        # --- HEADER: TÊN PROJECT ---
        header_fr = tk.Frame(self.right_frame, bg="#ffffff", padx=15, pady=10)
        header_fr.pack(fill="x", pady=(0, 10))
        
        self.lbl_proj_name = tk.Label(header_fr, text="Chưa chọn Project nào", font=("Arial", 16, "bold"), bg="#ffffff", fg="#2980b9")
        self.lbl_proj_name.pack(side="left")
        tk.Button(header_fr, text="✏️ Đổi Tên", command=self.rename_project, bg="#ecf0f1", font=("Arial", 8)).pack(side="left", padx=10)

        # --- BẢNG ĐIỀU KHIỂN CHUNG ---
        control_panel = tk.Frame(self.right_frame, bg="#f4f6f9")
        control_panel.pack(fill="x", pady=(0, 10))

        # 1. KHUNG QUẢN LÝ VOICE
        fr_voice = tk.LabelFrame(control_panel, text=" 🎙️ Danh Sách Voice ", font=("Arial", 10, "bold"), bg="#ffffff", padx=10, pady=5)
        fr_voice.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # [NÂNG CẤP] Bảng Treeview rộng rãi, có chia cột rõ ràng
        self.tree_voices = ttk.Treeview(fr_voice, columns=("name", "usage"), show="headings", height=8)
        self.tree_voices.heading("name", text="Tên Voice")
        self.tree_voices.heading("usage", text="Số Lần Dùng")
        
        # Chỉnh độ rộng cột cho to ra
        self.tree_voices.column("name", width=350, anchor="w")
        self.tree_voices.column("usage", width=120, anchor="center")
        
        scroll_voice_tab1 = ttk.Scrollbar(fr_voice, orient="vertical", command=self.tree_voices.yview)
        self.tree_voices.configure(yscrollcommand=scroll_voice_tab1.set)
        
        self.tree_voices.pack(side="left", padx=(5, 0), fill="both", expand=True, pady=5)
        scroll_voice_tab1.pack(side="left", fill="y", pady=5)

        btn_v_fr = tk.Frame(fr_voice, bg="#ffffff")
        btn_v_fr.pack(side="left", padx=10, pady=5, anchor="n")
        
        tk.Button(btn_v_fr, text="➕ Thêm", bg="#f39c12", fg="white", font=("Arial", 8, "bold"), width=8, command=self.import_voice).pack(pady=(0, 5))
        tk.Button(btn_v_fr, text="▶ Nghe", bg="#3498db", fg="white", font=("Arial", 8, "bold"), width=8, command=self.play_voice).pack(pady=(0, 5))
        tk.Button(btn_v_fr, text="🗑️ Xóa", bg="#e74c3c", fg="white", font=("Arial", 8, "bold"), width=8, command=self.delete_voice).pack()

        # 2. KHUNG CÔNG CỤ CẢNH TRÁM
        fr_tools = tk.LabelFrame(control_panel, text=" 🛠️ Quản Lý Cảnh Trám ", font=("Arial", 10, "bold"), bg="#ffffff", padx=10, pady=5)
        fr_tools.pack(side="right", fill="both", expand=True, padx=(5, 0))

        self.btn_add_broll = tk.Button(fr_tools, text="📥 Nạp Cảnh Trám", bg="#16a085", fg="white", font=("Arial", 10, "bold"), command=self.import_broll, height=2)
        self.btn_add_broll.pack(fill="x", padx=10, pady=(5, 10))

        btn_ai_fr = tk.Frame(fr_tools, bg="#ffffff")
        btn_ai_fr.pack(fill="x", padx=10)

        self.btn_refresh_all = tk.Button(fr_tools, text="🔄 Làm mới TOÀN BỘ ảnh", bg="#34495e", fg="white", font=("Arial", 9, "bold"), command=self.refresh_all_thumbnails)
        self.btn_refresh_all.pack(fill="x", padx=10, pady=(0, 5))

        self.btn_auto_tag = tk.Button(btn_ai_fr, text="🧠 AI TỰ NHÌN & ĐIỀN", bg="#d35400", fg="white", font=("Arial", 9, "bold"), command=self.start_auto_tag, height=2)
        self.btn_auto_tag.pack(side="left", fill="x", expand=True, padx=(0, 5))

        # [MỚI THÊM] BỘ ĐẾM SỐ LƯỢNG MÔ TẢ TRỐNG
        self.lbl_missing_desc = tk.Label(btn_ai_fr, text="Đang tính...", font=("Arial", 10, "bold"), fg="#c0392b", bg="#ffffff")
        self.lbl_missing_desc.pack(side="left", padx=10)

        self.btn_save_tags = tk.Button(btn_ai_fr, text="💾 LƯU MÔ TẢ", bg="#8e44ad", fg="white", font=("Arial", 9, "bold"), command=self.save_all_descriptions, height=2)
        self.btn_save_tags.pack(side="right", fill="x", expand=True, padx=(5, 0))


        # [MỚI THÊM] KHUNG ĐIỀN THÔNG TIN SẢN PHẨM/BỐI CẢNH
        tk.Label(fr_tools, text="📝 Bối cảnh / Thông tin SP (Giúp AI nhìn chuẩn hơn):", bg="#ffffff", font=("Arial", 9, "bold"), fg="#2980b9").pack(anchor="w", padx=10, pady=(5, 0))
        self.txt_context = tk.Text(fr_tools, height=3, font=("Arial", 10), bg="#fdfefe", bd=1, relief="solid", wrap="word")
        self.txt_context.pack(fill="both", expand=True, padx=10, pady=(2, 5))
        self.txt_context.bind("<KeyRelease>", self._on_context_change)

        # [MỚI] KHUNG CHỌN ẢNH SẢN PHẨM MẪU (REF IMAGES)
        fr_ref = tk.Frame(fr_tools, bg="#ffffff")
        fr_ref.pack(fill="x", padx=10, pady=(0, 5))

        self.btn_ref1 = tk.Button(fr_ref, text="🖼️ Ảnh Mẫu 1", bg="#f39c12", fg="white", font=("Arial", 8, "bold"), command=lambda: self.select_ref_image(1))
        self.btn_ref1.pack(side="left", padx=(0, 5))
        self.lbl_ref1 = tk.Label(fr_ref, text="Chưa chọn", bg="#ffffff", font=("Arial", 8), fg="gray")
        self.lbl_ref1.pack(side="left", fill="x", expand=True)

        self.btn_ref2 = tk.Button(fr_ref, text="🖼️ Ảnh Mẫu 2", bg="#f39c12", fg="white", font=("Arial", 8, "bold"), command=lambda: self.select_ref_image(2))
        self.btn_ref2.pack(side="left", padx=(5, 5))
        self.lbl_ref2 = tk.Label(fr_ref, text="Chưa chọn", bg="#ffffff", font=("Arial", 8), fg="gray")
        self.lbl_ref2.pack(side="left", fill="x", expand=True)
        
        # Nút xóa ảnh mẫu
        tk.Button(fr_ref, text="❌", bg="#e74c3c", fg="white", font=("Arial", 8), command=self.clear_ref_images).pack(side="right")

        # [MỚI] KHUNG THÔNG TIN SẢN PHẨM / LINK SHOPEE
        fr_product_info = tk.LabelFrame(
            self.right_frame,
            text=" Thông tin Shopee & Quản lý Job Hàng Loạt ",
            font=("Arial", 10, "bold"),
            bg="#ffffff",
            padx=12,
            pady=8,
        )
        fr_product_info.pack(fill="x", pady=(0, 10))

        row_name = tk.Frame(fr_product_info, bg="#ffffff")
        row_name.pack(fill="x", pady=(0, 6))
        tk.Label(
            row_name,
            text="Tên sản phẩm:",
            bg="#ffffff",
            fg="#8e44ad",
            font=("Arial", 10, "bold"),
            width=18,
            anchor="w",
        ).pack(side="left")
        self.ent_product_name = tk.Entry(row_name, font=("Arial", 10))
        self.ent_product_name.pack(side="left", fill="x", expand=True)
        self.ent_product_name.bind("<KeyRelease>", self._on_product_info_change)

        self.product_link_entries = []
        for idx in range(6):
            row_link = tk.Frame(fr_product_info, bg="#ffffff")
            row_link.pack(fill="x", pady=2)
            tk.Label(
                row_link,
                text=f"Link sản phẩm {idx + 1}:",
                bg="#ffffff",
                font=("Arial", 10),
                width=18,
                anchor="w",
            ).pack(side="left")
            ent_link = tk.Entry(row_link, font=("Arial", 10))
            ent_link.pack(side="left", fill="x", expand=True)
            ent_link.bind("<KeyRelease>", self._on_product_info_change)
            self.product_link_entries.append(ent_link)


        # --- [MỚI] THANH QUẢN LÝ HÀNG LOẠT & TÌM KIẾM ---
        bulk_fr = tk.Frame(self.right_frame, bg="#dfe6e9", padx=10, pady=5)
        bulk_fr.pack(fill="x", pady=(0, 5))
        
        tk.Label(bulk_fr, text="⚡ XỬ LÝ NHIỀU FILE:", font=("Arial", 9, "bold"), bg="#dfe6e9").pack(side="left")
        
        tk.Button(bulk_fr, text="☑ Chọn tất cả", font=("Arial", 8), command=self.select_all_broll).pack(side="left", padx=10)
        tk.Button(bulk_fr, text="☐ Bỏ chọn", font=("Arial", 8), command=self.deselect_all_broll).pack(side="left")
        
        # --- Ô TÌM KIẾM ---
        tk.Label(bulk_fr, text="🔍 Tìm tên:", font=("Arial", 9, "bold"), bg="#dfe6e9").pack(side="left", padx=(20, 5))
        self.ent_search = tk.Entry(bulk_fr, width=25, font=("Arial", 10))
        self.ent_search.pack(side="left")
        self.ent_search.bind("<KeyRelease>", lambda e: self.render_video_list()) # Gõ phím là tự động lọc luôn
        
        self.btn_bulk_delete = tk.Button(bulk_fr, text="❌ XÓA VĨNH VIỄN", bg="#ff7675", fg="white", font=("Arial", 8, "bold"), command=self.bulk_delete_forever)
        self.btn_bulk_delete.pack(side="right", padx=5)
        
        self.btn_bulk_trash = tk.Button(bulk_fr, text="🗑️ Bỏ vào Thùng rác", bg="#fab1a0", font=("Arial", 8, "bold"), command=self.bulk_move_to_trash)
        self.btn_bulk_trash.pack(side="right", padx=5)

        # --- KHU VỰC NOTEBOOK CHỨA VIDEO ---
        self.broll_nb = ttk.Notebook(self.right_frame)
        self.broll_nb.pack(fill="both", expand=True)

        self.tab_active = tk.Frame(self.broll_nb, bg="#fdfefe")
        self.tab_trash = tk.Frame(self.broll_nb, bg="#fdfefe")

        self.broll_nb.add(self.tab_active, text=" ✅ Cảnh Đang Dùng ")
        self.broll_nb.add(self.tab_trash, text=" 🗑️ Đã Xóa (Thùng Rác) ")

        # Canvas Tab Active
        self.canvas_act = tk.Canvas(self.tab_active, bg="#fdfefe")
        self.scroll_act = ttk.Scrollbar(self.tab_active, orient="vertical", command=self.canvas_act.yview)
        self.frame_act = tk.Frame(self.canvas_act, bg="#fdfefe")
        self.frame_act.bind("<Configure>", lambda e: self.canvas_act.configure(scrollregion=self.canvas_act.bbox("all")))
        self.frame_act_window = self.canvas_act.create_window((0, 0), window=self.frame_act, anchor="nw")
        self.canvas_act.configure(yscrollcommand=self.scroll_act.set)
        self.canvas_act.bind("<Configure>", self._sync_canvas_window_widths)
        self.canvas_act.pack(side="left", fill="both", expand=True)
        self.scroll_act.pack(side="right", fill="y")

        # Canvas Tab Trash
        self.canvas_tr = tk.Canvas(self.tab_trash, bg="#fdfefe")
        self.scroll_tr = ttk.Scrollbar(self.tab_trash, orient="vertical", command=self.canvas_tr.yview)
        self.frame_tr = tk.Frame(self.canvas_tr, bg="#fdfefe")
        self.frame_tr.bind("<Configure>", lambda e: self.canvas_tr.configure(scrollregion=self.canvas_tr.bbox("all")))
        self.frame_tr_window = self.canvas_tr.create_window((0, 0), window=self.frame_tr, anchor="nw")
        self.canvas_tr.configure(yscrollcommand=self.scroll_tr.set)
        self.canvas_tr.bind("<Configure>", self._sync_canvas_window_widths)
        self.canvas_tr.pack(side="left", fill="both", expand=True)
        self.scroll_tr.pack(side="right", fill="y")

       # --- THAY THẾ CHO LỆNH BIND_ALL CŨ ---
        def _bind_mouse(event):
            self.broll_nb.bind_all("<MouseWheel>", self._on_mousewheel)
            
        def _unbind_mouse(event):
            self.broll_nb.unbind_all("<MouseWheel>")

        # Chỉ bật lăn chuột khi rê chuột vào khu vực Notebook của Tab BRoll
        self.broll_nb.bind("<Enter>", _bind_mouse)
        self.broll_nb.bind("<Leave>", _unbind_mouse)
        self.refresh_project_list()

    # =========================================================
    # [MỚI] CÁC HÀM XỬ LÝ CHỌN VÀ XÓA HÀNG LOẠT
    # =========================================================

    def _get_active_vars(self):
        """Lấy danh sách checkbox của tab đang được mở"""
        selected_tab = self.broll_nb.index(self.broll_nb.select())
        return self.check_vars_act if selected_tab == 0 else self.check_vars_tr

    def select_all_broll(self):
        for var in self._get_active_vars().values():
            var.set(True)

    def deselect_all_broll(self):
        for var in self._get_active_vars().values():
            var.set(False)

    def bulk_move_to_trash(self):
        """Đẩy hàng loạt cảnh vào thùng rác"""
        if self.broll_nb.index(self.broll_nb.select()) != 0:
            return messagebox.showinfo("Chú ý", "Chức năng này chỉ dùng cho bảng 'Cảnh Đang Dùng'!")
            
        selected_vids = [name for name, var in self.check_vars_act.items() if var.get()]
        if not selected_vids:
            return messagebox.showwarning("Chú ý", "Bác chưa chọn cảnh nào để xóa!")
            
        if messagebox.askyesno("Xác nhận", f"Đẩy {len(selected_vids)} cảnh đã chọn vào Thùng rác?"):
            for vid in selected_vids:
                self.move_to_trash(vid, refresh=False) # Gọi xóa nhưng không load lại UI liên tục
            self.render_video_list() # Load lại 1 lần duy nhất ở cuối

    def bulk_delete_forever(self):
        """Quét sạch ổ cứng vĩnh viễn"""
        active_vars = self._get_active_vars()
        is_trash_tab = self.broll_nb.index(self.broll_nb.select()) == 1
        
        selected_vids = [name for name, var in active_vars.items() if var.get()]
        if not selected_vids:
            return messagebox.showwarning("Chú ý", "Bác chưa chọn cảnh nào để xóa!")
            
        if messagebox.askyesno("⚠️ CẢNH BÁO", f"Bác có chắc muốn XÓA VĨNH VIỄN {len(selected_vids)} cảnh này khỏi máy tính?\n(Không thể khôi phục!)"):
            proj_dir = self.main_app.get_proj_dir(self.current_project_id)
            folder_name = "Broll_Trash" if is_trash_tab else "Broll"
            target_dir = os.path.join(proj_dir, folder_name)
            
            p_data = self.main_app.get_project_data(self.current_project_id)
            dict_key = "trash" if is_trash_tab else "videos"
            
            for vid_name in selected_vids:
                # Xóa file Video
                vid_path = os.path.join(target_dir, vid_name)
                if os.path.exists(vid_path):
                    try: os.remove(vid_path)
                    except: pass
                
                # Xóa file Thumbnail
                thumb_path = os.path.join(target_dir, ".thumbnails", f"{vid_name}.jpg")
                if os.path.exists(thumb_path):
                    try: os.remove(thumb_path)
                    except: pass
                
                # Xóa khỏi database
                if vid_name in p_data.get(dict_key, {}):
                    del p_data[dict_key][vid_name]
            
            self.main_app.save_project_data(self.current_project_id, p_data)
            messagebox.showinfo("Thành công", f"Đã tiễn {len(selected_vids)} file về cát bụi!")
            self.render_video_list()

    # =========================================================
    # CÁC HÀM XỬ LÝ SỰ KIỆN & CHỨC NĂNG CƠ BẢN
    # =========================================================

    def _on_mousewheel(self, event):
        try:
            selected_tab = self.broll_nb.index(self.broll_nb.select())
            if selected_tab == 0: 
                self.canvas_act.yview_scroll(int(-1*(event.delta/120)), "units")
            else: 
                self.canvas_tr.yview_scroll(int(-1*(event.delta/120)), "units")
        except: pass

    def _bind_mousewheel_to_all_children(self, parent_widget):
        """Hàm đệ quy đi ép tất cả widget con phải nhả sự kiện cuộn cho Canvas"""
        # Gắn lệnh cuộn cho bản thân widget hiện tại
        parent_widget.bind("<MouseWheel>", self._on_mousewheel)
        
        # Quét tất cả các thành phần con nằm bên trong nó
        for child in parent_widget.winfo_children():
            # Gọi đệ quy để đi sâu vào các lớp bên trong (Frame lồng Frame)
            self._bind_mousewheel_to_all_children(child)

    def _sync_canvas_window_widths(self, event=None):
        try:
            self.canvas_act.itemconfigure(self.frame_act_window, width=self.canvas_act.winfo_width())
            self.canvas_tr.itemconfigure(self.frame_tr_window, width=self.canvas_tr.winfo_width())
        except Exception:
            pass


    def refresh_project_list(self):
        for item in self.tree_proj.get_children(): self.tree_proj.delete(item)
        sorted_projects = sorted(self.main_app.projects.items(), key=lambda x: x[1]['created_at'], reverse=True)
        for pid, pdata in sorted_projects:
            name = pdata['name']
            # Hiện icon khóa nếu đang ẩn
            if pdata.get('status') == 'disabled': name = f"⏸️ {name} (Đã Ẩn)"
            self.tree_proj.insert("", "end", iid=pid, values=(name,))

    def rename_project(self):
        if not self.current_project_id: return
        old_name = self.main_app.projects[self.current_project_id]['name']
        new_name = simpledialog.askstring("Đổi tên", "Nhập tên mới:", initialvalue=old_name)
        if new_name and new_name.strip():
            self.main_app.projects[self.current_project_id]['name'] = new_name.strip()
            self.main_app.save_projects()
            self.lbl_proj_name.config(text=new_name.strip())
            self.refresh_project_list()
            self.tree_proj.selection_set(self.current_project_id)

    def import_broll(self):
        if not self.current_project_id: return
        files = filedialog.askopenfilenames(title="Chọn Video", filetypes=[("Video", "*.mp4 *.mov")])
        if files:
            broll_dir = os.path.join(self.main_app.get_proj_dir(self.current_project_id), "Broll")
            os.makedirs(broll_dir, exist_ok=True)
            for f in files: shutil.copy2(f, os.path.join(broll_dir, os.path.basename(f)))
            self.render_video_list()

    def load_voices(self):
        # Dọn sạch bảng cũ
        for item in self.tree_voices.get_children(): 
            self.tree_voices.delete(item)
            
        if not self.current_project_id: return
        voice_dir = os.path.join(self.main_app.get_proj_dir(self.current_project_id), "Voices")
        if not os.path.exists(voice_dir): return
        
        # Đọc dữ liệu xem voice nào đã được dùng bao nhiêu lần
        p_data = self.main_app.get_project_data(self.current_project_id)
        voice_usage = p_data.get("voice_usage", {})
        
        for f in os.listdir(voice_dir):
            if f.lower().endswith(('.mp3', '.wav', '.m4a')):
                count = voice_usage.get(f, 0) # Lấy số lần dùng, mặc định là 0
                self.tree_voices.insert("", "end", values=(f, f"{count} lần"))

    def play_voice(self):
        selected = self.tree_voices.selection()
        if selected: 
            # Lấy tên file ở Cột số 0
            file_name = self.tree_voices.item(selected[0])['values'][0]
            file_path = os.path.join(self.main_app.get_proj_dir(self.current_project_id), "Voices", file_name)
            if os.path.exists(file_path):
                os.startfile(file_path)

    def delete_voice(self):
        selected = self.tree_voices.selection()
        if selected and messagebox.askyesno("Xóa", "Xóa Voice này?"):
            file_name = self.tree_voices.item(selected[0])['values'][0]
            file_path = os.path.join(self.main_app.get_proj_dir(self.current_project_id), "Voices", file_name)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    
                    # Xóa luôn lịch sử sử dụng trong JSON cho sạch sẽ
                    p_data = self.main_app.get_project_data(self.current_project_id)
                    if "voice_usage" in p_data and file_name in p_data["voice_usage"]:
                        del p_data["voice_usage"][file_name]
                        self.main_app.save_project_data(self.current_project_id, p_data)
                        
                except Exception as e:
                    messagebox.showerror("Lỗi", f"Không thể xóa file: {e}")
            self.load_voices()
    def import_voice(self):
        if not self.current_project_id: return
        files = filedialog.askopenfilenames(title="Chọn Voice", filetypes=[("Audio", "*.mp3 *.wav *.m4a")])
        if files:
            voice_dir = os.path.join(self.main_app.get_proj_dir(self.current_project_id), "Voices")
            os.makedirs(voice_dir, exist_ok=True)
            
            # 1. Gọi cuốn sổ JSON ra (Hàm get này tự có khóa bảo vệ bên main.py rồi)
            p_data = self.main_app.get_project_data(self.current_project_id)
            if "voice_usage" not in p_data: 
                p_data["voice_usage"] = {}
            if "voice_srt_cache" not in p_data:  # [MỚI] Khởi tạo SRT cache
                p_data["voice_srt_cache"] = {}
                
            for f in files: 
                file_name = os.path.basename(f)
                shutil.copy2(f, os.path.join(voice_dir, file_name))
                
                # Khai báo lính mới
                if file_name not in p_data["voice_usage"]:
                    p_data["voice_usage"][file_name] = 0
            
            # 2. Lưu lại (Hàm save này cũng tự có khóa bảo vệ bên main.py rồi, gọi thẳng tay!)
            self.main_app.save_project_data(self.current_project_id, p_data)
            
            # 3. [MỚI] Bắt đầu extract SRT cho từng voice mới (chạy background)
            for f in files:
                file_name = os.path.basename(f)
                file_path = os.path.join(voice_dir, file_name)
                thread = threading.Thread(target=self._extract_voice_srt_async, args=(file_name, file_path), daemon=True)
                thread.start()
                
            self.load_voices()
    
    def _extract_voice_srt_async(self, voice_name, voice_path):
        """[MỚI] Bóc SRT từ voice file và lưu vào cache (chạy background)"""
        try:
            # Gọi get_transcription từ Tab 2
            mode = self.main_app.config.get("boc_bang_mode", "groq")
            srt_text = get_transcription(voice_path, voice_name, mode, self.main_app.config, self._log_extract)
            
            # Lưu vào cache
            p_data = self.main_app.get_project_data(self.current_project_id)
            if "voice_srt_cache" not in p_data:
                p_data["voice_srt_cache"] = {}
            
            p_data["voice_srt_cache"][voice_name] = srt_text
            self.main_app.save_project_data(self.current_project_id, p_data)
            
            self._log_extract(f"✅ Đã bóp SRT xong: {voice_name}")
        except Exception as e:
            self._log_extract(f"❌ Lỗi bóc SRT {voice_name}: {str(e)}")
    
    def _log_extract(self, msg):
        """[MỚI] Ghi log extraction (để in ra log nếu có)"""
        print(f"[Tab 1 Voice] {msg}")
    
    def get_voice_srt(self, voice_name):
        """[MỚI] Lấy SRT của voice (từ cache)"""
        p_data = self.main_app.get_project_data(self.current_project_id)
        
        # Check xem có cache không
        if "voice_srt_cache" in p_data and voice_name in p_data["voice_srt_cache"]:
            return p_data["voice_srt_cache"][voice_name]
        
        return None
    
    def get_voice_srt_or_extract(self, project_id, voice_name, voice_path):
        """[MỚI] Lấy SRT từ cache, nếu chưa có thì extract (blocking)"""
        p_data = self.main_app.get_project_data(project_id)
        
        # 1. Check cache trước
        if "voice_srt_cache" in p_data and voice_name in p_data["voice_srt_cache"]:
            return p_data["voice_srt_cache"][voice_name]
        
        # 2. Nếu chưa cache, extract ngay (blocking call)
        try:
            mode = self.main_app.config.get("boc_bang_mode", "groq")
            srt_text = get_transcription(voice_path, voice_name, mode, self.main_app.config, self._log_extract)
            
            # Lưu vào cache
            if "voice_srt_cache" not in p_data:
                p_data["voice_srt_cache"] = {}
            p_data["voice_srt_cache"][voice_name] = srt_text
            self.main_app.save_project_data(project_id, p_data)
            
            return srt_text
        except Exception as e:
            self._log_extract(f"❌ Lỗi bóc SRT {voice_name}: {str(e)}")
            raise
            
    def add_project_dialog(self):
        proj_name = simpledialog.askstring("Tên Project", "Nhập tên Project:")
        if proj_name:
            pid = datetime.now().strftime("%Y%m%d%H%M%S")
            self.main_app.projects[pid] = {"name": proj_name, "created_at": datetime.now().timestamp()}
            self.main_app.save_projects()
            self.main_app.save_project_data(
                pid,
                {
                    "videos": {},
                    "trash": {},
                    "timeline": [],
                    "product_context": "",
                    "product_name": "",
                    "product_links": ["", "", "", "", "", ""],
                },
            )
            self.refresh_project_list()
            self.tree_proj.selection_set(pid)

    def on_select_project(self, event):
        selected = self.tree_proj.selection()
        if not selected: return
        next_project_id = selected[0]

        if self.current_project_id and self.current_project_id != next_project_id:
            self.save_all_descriptions()
            self.save_project_context()
            self.save_product_info()

        self.current_project_id = next_project_id
        self.lbl_proj_name.config(text=self.main_app.projects[self.current_project_id]['name'])
        self.load_voices()
        self.render_video_list()
        # Đổi trạng thái nút bấm
        status = self.main_app.projects[self.current_project_id].get("status", "active")
        if status == "disabled":
            self.btn_toggle_proj.config(text="▶️ Mở Khóa Project", bg="#27ae60")
        else:
            self.btn_toggle_proj.config(text="⏸️ Đóng Băng Project", bg="#f39c12")
        # Load bối cảnh ra ô Text
        p_data = self.main_app.get_project_data(self.current_project_id)
        self.txt_context.delete("1.0", tk.END)
        self.txt_context.insert("1.0", p_data.get("product_context", ""))
        self._load_product_info(p_data)
        # Load ảnh mẫu ra UI
        ref1 = p_data.get("ref_img_1", "")
        ref2 = p_data.get("ref_img_2", "")
        self.lbl_ref1.config(text=os.path.basename(ref1)[:15]+"..." if ref1 and os.path.exists(ref1) else "Chưa chọn", fg="#27ae60" if ref1 else "gray")
        self.lbl_ref2.config(text=os.path.basename(ref2)[:15]+"..." if ref2 and os.path.exists(ref2) else "Chưa chọn", fg="#27ae60" if ref2 else "gray")

    def delete_project(self):
        if not self.current_project_id: return
        if messagebox.askyesno("Xóa", "Xóa toàn bộ Project và File trong thư mục Tool?"):
            shutil.rmtree(self.main_app.get_proj_dir(self.current_project_id), ignore_errors=True)
            del self.main_app.projects[self.current_project_id]
            self.main_app.save_projects()
            self.refresh_project_list()
            
            self.current_project_id = None
            self.lbl_proj_name.config(text="Chưa chọn Project nào")
            for item in self.tree_voices.get_children(): self.tree_voices.delete(item)
            for widget in self.frame_act.winfo_children(): widget.destroy()
            for widget in self.frame_tr.winfo_children(): widget.destroy()
            self.txt_context.delete("1.0", tk.END)
            self.ent_product_name.delete(0, tk.END)
            for entry in self.product_link_entries:
                entry.delete(0, tk.END)

    def move_to_trash(self, vid_name, refresh=True):
        self.save_all_descriptions() 
        proj_dir = self.main_app.get_proj_dir(self.current_project_id)
        src = os.path.join(proj_dir, "Broll", vid_name)
        dst_dir = os.path.join(proj_dir, "Broll_Trash")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, vid_name)
        
        if os.path.exists(src): shutil.move(src, dst)
        
        p_data = self.main_app.get_project_data(self.current_project_id)
        if "trash" not in p_data: p_data["trash"] = {}
        if vid_name in p_data.get("videos", {}):
            p_data["trash"][vid_name] = p_data["videos"].pop(vid_name)
            self.main_app.save_project_data(self.current_project_id, p_data)
        
        if refresh:
            self.render_video_list()

    def restore_from_trash(self, vid_name):
        proj_dir = self.main_app.get_proj_dir(self.current_project_id)
        src = os.path.join(proj_dir, "Broll_Trash", vid_name)
        dst_dir = os.path.join(proj_dir, "Broll")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, vid_name)
        
        if os.path.exists(src): shutil.move(src, dst)
        
        p_data = self.main_app.get_project_data(self.current_project_id)
        if "videos" not in p_data: p_data["videos"] = {}
        if vid_name in p_data.get("trash", {}):
            p_data["videos"][vid_name] = p_data["trash"].pop(vid_name)
            self.main_app.save_project_data(self.current_project_id, p_data)
        self.render_video_list()

    def open_file_location(self, vid_name):
        if not self.current_project_id: return
        proj_dir = self.main_app.get_proj_dir(self.current_project_id)
        vid_path = os.path.normpath(os.path.join(proj_dir, "Broll", vid_name))
        if os.path.exists(vid_path): subprocess.Popen(f'explorer /select,"{vid_path}"')

    def replace_video(self, old_vid_name):
        if not self.current_project_id: return
        new_file = filedialog.askopenfilename(title="Chọn Video Đã Sửa", filetypes=[("Video", "*.mp4 *.mov")])
        if not new_file: return
        self.save_all_descriptions() 
        
        broll_dir = os.path.join(self.main_app.get_proj_dir(self.current_project_id), "Broll")
        old_vid_path = os.path.join(broll_dir, old_vid_name)
        new_vid_name = os.path.basename(new_file)
        new_vid_path = os.path.join(broll_dir, new_vid_name)
        
        p_data = self.main_app.get_project_data(self.current_project_id)
        old_desc = p_data.get("videos", {}).get(old_vid_name, {}).get("description", "")
        gc.collect()

        if os.path.normpath(new_file) != os.path.normpath(old_vid_path):
            try:
                if os.path.exists(old_vid_path): os.remove(old_vid_path)
            except PermissionError:
                try:
                    os.rename(old_vid_path, old_vid_path + f".locked_{datetime.now().strftime('%H%M%S')}")
                except Exception:
                    messagebox.showerror("⚠️ Kẹt File", "Windows đang khóa file này!")
                    return
            except Exception as e:
                messagebox.showerror("Lỗi", str(e)); return
                
            try: shutil.copy2(new_file, new_vid_path)
            except shutil.SameFileError: pass
            except Exception as e: messagebox.showerror("Lỗi Copy", str(e)); return

        old_thumb = os.path.join(broll_dir, ".thumbnails", f"{old_vid_name}.jpg")
        if os.path.exists(old_thumb): 
            try: os.remove(old_thumb)
            except: pass
            
        if old_vid_name in p_data.get("videos", {}) and old_vid_name != new_vid_name:
            del p_data["videos"][old_vid_name]
        if "videos" not in p_data: p_data["videos"] = {}
        p_data["videos"][new_vid_name] = {"description": old_desc, "duration": 0.0}
        
        self.main_app.save_project_data(self.current_project_id, p_data)
        messagebox.showinfo("Thành công", "Đã đánh tráo file mượt mà!")
        self.render_video_list()

    def render_video_list(self):
        for w in self.frame_act.winfo_children(): w.destroy()
        for w in self.frame_tr.winfo_children(): w.destroy()
        self.photo_refs.clear()
        self.desc_entries.clear()
        self.check_vars_act.clear()
        self.check_vars_tr.clear()
        self.canvas_act.configure(scrollregion=(0, 0, 0, 0))
        self.canvas_tr.configure(scrollregion=(0, 0, 0, 0))
        self.canvas_act.yview_moveto(0)
        self.canvas_tr.yview_moveto(0)

        if not self.current_project_id: return
        proj_dir = self.main_app.get_proj_dir(self.current_project_id)
        broll_dir = os.path.join(proj_dir, "Broll")
        trash_dir = os.path.join(proj_dir, "Broll_Trash")
        os.makedirs(broll_dir, exist_ok=True)
        os.makedirs(trash_dir, exist_ok=True)

        # Lấy từ khóa tìm kiếm (nếu có)
        keyword = self.ent_search.get().strip().lower() if hasattr(self, 'ent_search') else ""

        # Đã thêm điều kiện: keyword in f.lower() để lọc file
        act_files = sorted(
            [f for f in os.listdir(broll_dir) if f.lower().endswith(('.mp4', '.mov')) and keyword in f.lower()],
            key=lambda x: os.path.getmtime(os.path.join(broll_dir, x)),
            reverse=True
        )
        
        tr_files = sorted(
            [f for f in os.listdir(trash_dir) if f.lower().endswith(('.mp4', '.mov')) and keyword in f.lower()],
            key=lambda x: os.path.getmtime(os.path.join(trash_dir, x)),
            reverse=True
        )

        if not act_files and not tr_files: 
            tk.Label(self.frame_act, text="Không tìm thấy cảnh nào phù hợp.", fg="#7f8c8d", font=("Arial", 10, "italic")).pack(pady=20)
            return

        tk.Label(self.frame_act, text="⏳ Đang load ảnh...", fg="#e67e22").pack(pady=10)
        
        threading.Thread(target=self.thumb_handler.generate, args=(broll_dir, trash_dir, act_files, tr_files), daemon=True).start()

    def _build_video_rows(self, broll_dir, trash_dir, act_files, tr_files, p_data):
        for w in self.frame_act.winfo_children(): w.destroy()
        for w in self.frame_tr.winfo_children(): w.destroy()
        
        self.check_vars_act.clear()
        self.check_vars_tr.clear()
        self.thumb_labels.clear()  # [MỚI] Clear thumbnail labels
        
        saved_vids = p_data.get('videos', {})
        if not act_files: 
            pass # Đã xử lý label ở hàm trên
        else:
            header_fr = tk.Frame(self.frame_act, bg="#bdc3c7", pady=5)
            header_fr.pack(fill="x", padx=10, pady=(5, 0))
            
            header_fr.columnconfigure(0, weight=0, minsize=40)
            header_fr.columnconfigure(1, weight=1, minsize=800)
            header_fr.columnconfigure(2, weight=1, minsize=300)  # Tăng minsize từ 250 lên 350
            header_fr.columnconfigure(3, weight=3, minsize=400)
            header_fr.columnconfigure(4, weight=0, minsize=120)
            header_fr.columnconfigure(5, weight=0, minsize=120)
            
            tk.Label(header_fr, text="☑", bg="#bdc3c7", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="ew")
            tk.Label(header_fr, text="Ảnh Cảnh", bg="#bdc3c7", font=("Arial", 10, "bold")).grid(row=0, column=1, sticky="w", padx=5)
            tk.Label(header_fr, text="Info & Công cụ", bg="#bdc3c7", font=("Arial", 10, "bold")).grid(row=0, column=2, sticky="w", padx=5)
            tk.Label(header_fr, text="Mô Tả Cảnh", bg="#bdc3c7", font=("Arial", 10, "bold")).grid(row=0, column=3, sticky="w", padx=5)
            tk.Label(header_fr, text="Âm Thanh", bg="#bdc3c7", font=("Arial", 10, "bold"), fg="#c0392b").grid(row=0, column=4, sticky="w", padx=5)
            tk.Label(header_fr, text="Số Lần", bg="#bdc3c7", font=("Arial", 10, "bold")).grid(row=0, column=5, sticky="e", padx=10)

        for vid_name in act_files:
            row_fr = tk.Frame(self.frame_act, bg="#ffffff", bd=1, relief="ridge", pady=8)
            row_fr.pack(fill="x", padx=10, pady=4)
            
            row_fr.columnconfigure(0, weight=0, minsize=40)
            row_fr.columnconfigure(1, weight=1, minsize=800)
            row_fr.columnconfigure(2, weight=1, minsize=300) # Tăng minsize Info
            row_fr.columnconfigure(3, weight=3, minsize=400)
            row_fr.columnconfigure(4, weight=0, minsize=120)
            row_fr.columnconfigure(5, weight=0, minsize=120)
            
            var = tk.BooleanVar()
            self.check_vars_act[vid_name] = var
            tk.Checkbutton(row_fr, variable=var, bg="#ffffff", activebackground="#ffffff").grid(row=0, column=0, sticky="ns")
            
            thumb_lbl = tk.Label(row_fr, bg="#000000", width=35, height=6)
            thumb_lbl.grid(row=0, column=1, sticky="w", padx=5)
            self.thumb_labels[vid_name] = thumb_lbl  # [MỚI] Lưu thumbnail label
            
            thumb_path = os.path.join(broll_dir, ".thumbnails", f"{vid_name}.jpg")
            if os.path.exists(thumb_path):
                try:
                    img = Image.open(thumb_path)
                    photo = ImageTk.PhotoImage(img)
                    self.photo_refs[vid_name] = photo 
                    thumb_lbl.config(image=photo, width=0, height=0)
                except: pass

            col2 = tk.Frame(row_fr, bg="#ffffff")
            col2.grid(row=0, column=2, sticky="nw", padx=5)
            
            dur = saved_vids.get(vid_name, {}).get('duration', 0)
            # ĐÃ XÓA GỌT TÊN `[:20]...` VÀ THÊM TÍNH NĂNG XUỐNG DÒNG (wraplength)
            tk.Label(col2, text=f"🎥 {vid_name}\n⏳ {dur} giây", font=("Arial", 9, "bold"), bg="#ffffff", justify="left", wraplength=330).pack(anchor="nw", pady=(0, 5))
            
            btn_fr1 = tk.Frame(col2, bg="#ffffff")
            btn_fr1.pack(anchor="nw", pady=2)
            tk.Button(btn_fr1, text="▶ Xem", bg="#3498db", fg="white", font=("Arial", 8, "bold"), width=8, command=lambda p=os.path.join(broll_dir, vid_name): os.startfile(p)).pack(side="left", padx=(0, 5))
            tk.Button(btn_fr1, text="📂 Vị trí", bg="#9b59b6", fg="white", font=("Arial", 8, "bold"), width=8, command=lambda v=vid_name: self.open_file_location(v)).pack(side="left")
            
            btn_fr2 = tk.Frame(col2, bg="#ffffff")
            btn_fr2.pack(anchor="nw", pady=2)

            # [MỚI] Nút Làm mới ảnh
            tk.Button(btn_fr2, text="📸 Làm mới", bg="#3498db", fg="white", font=("Arial", 8, "bold"), width=8, command=lambda v=vid_name: self.refresh_single_thumbnail(v)).pack(side="left", padx=(0, 5))
            
            # [MỚI] Nút AI Soi riêng lẻ
            tk.Button(btn_fr2, text="🤖 AI Soi", bg="#d35400", fg="white", font=("Arial", 8, "bold"), width=8, command=lambda v=vid_name: self.start_single_auto_tag(v)).pack(side="left", padx=(0, 5))
            
            tk.Button(btn_fr2, text="🔄 Thay", bg="#f39c12", fg="white", font=("Arial", 8, "bold"), width=8, command=lambda v=vid_name: self.replace_video(v)).pack(side="left", padx=(0, 5))
            tk.Button(btn_fr2, text="🗑️ Xóa", bg="#e74c3c", fg="white", font=("Arial", 8, "bold"), width=8, command=lambda v=vid_name: self.move_to_trash(v)).pack(side="left")

            description_text = saved_vids.get(vid_name, {}).get("description", "")
            visible_lines = max(6, min(12, len(description_text.splitlines()) + 1))
            txt_desc = tk.Text(row_fr, height=visible_lines, font=("Arial", 10), bg="#f9f9f9", wrap="word")
            txt_desc.grid(row=0, column=3, sticky="nsew", padx=5)
            txt_desc.insert("1.0", description_text)
            txt_desc.bind("<MouseWheel>", self._on_mousewheel)
            self.desc_entries[vid_name] = txt_desc

            # ========================================================
            # [BÙA AUTO-SAVE] TỰ ĐỘNG LƯU SAU KHI SẾP NGỪNG GÕ 1 GIÂY
            # ========================================================
            def on_text_change(event, v_name=vid_name):
                self.update_missing_desc_count() # Kích hoạt đếm số lượng ngay lập tức khi gõ chữ
                
                if hasattr(self, f"timer_{v_name}"):
                    self.parent.after_cancel(getattr(self, f"timer_{v_name}"))
                timer_id = self.parent.after(1000, self.save_all_descriptions)
                setattr(self, f"timer_{v_name}", timer_id)

            # Gắn sự kiện: Cứ nhấc tay khỏi bàn phím là kích hoạt đếm ngược
            txt_desc.bind("<KeyRelease>", on_text_change)
            # ========================================================

            col4 = tk.Frame(row_fr, bg="#ffffff")
            col4.grid(row=0, column=4, sticky="nw", padx=5, pady=10)
            keep_audio_var = tk.BooleanVar(value=saved_vids.get(vid_name, {}).get('keep_audio', False))
            if not hasattr(self, 'audio_vars'): self.audio_vars = {}
            self.audio_vars[vid_name] = keep_audio_var
            tk.Checkbutton(col4, text="🔊 Bật Âm", variable=keep_audio_var, bg="#ffffff", font=("Arial", 9, "bold"), fg="#c0392b", command=self.save_all_descriptions).pack(anchor="nw")
            tk.Label(col4, text="(Giữ tiếng gốc)", bg="#ffffff", font=("Arial", 8, "italic"), fg="#7f8c8d").pack(anchor="nw", padx=20)

            usage = saved_vids.get(vid_name, {}).get('usage_count', 0)
            usage_color = "#27ae60" if usage == 0 else ("#f39c12" if usage < 3 else "#c0392b")
            tk.Label(row_fr, text=f"{usage} lần", font=("Arial", 16, "bold"), fg=usage_color, bg="#ffffff").grid(row=0, column=5, sticky="e", padx=15)

        saved_trash = p_data.get('trash', {})
        if not tr_files: 
            pass # Đã xử lý label ở trên
        else:
            header_tr = tk.Frame(self.frame_tr, bg="#eab5b5", pady=5)
            header_tr.pack(fill="x", padx=10, pady=(5, 0))
            
            header_tr.columnconfigure(0, weight=0, minsize=40)
            header_tr.columnconfigure(1, weight=1, minsize=700)
            header_tr.columnconfigure(2, weight=1, minsize=350)
            header_tr.columnconfigure(3, weight=3, minsize=400)
            
            tk.Label(header_tr, text="☑", bg="#eab5b5", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="ew")
            tk.Label(header_tr, text="Ảnh Cảnh", bg="#eab5b5", font=("Arial", 10, "bold")).grid(row=0, column=1, sticky="w", padx=5)
            tk.Label(header_tr, text="Info & Khôi phục", bg="#eab5b5", font=("Arial", 10, "bold")).grid(row=0, column=2, sticky="w", padx=5)
            tk.Label(header_tr, text="Mô Tả Cũ (Chỉ xem)", bg="#eab5b5", font=("Arial", 10, "bold")).grid(row=0, column=3, sticky="w", padx=5)

        for vid_name in tr_files:
            row_fr = tk.Frame(self.frame_tr, bg="#f9ebed", bd=1, relief="ridge", pady=8)
            row_fr.pack(fill="x", padx=10, pady=4)
            
            row_fr.columnconfigure(0, weight=0, minsize=40)
            row_fr.columnconfigure(1, weight=1, minsize=700)
            row_fr.columnconfigure(2, weight=1, minsize=350)
            row_fr.columnconfigure(3, weight=3, minsize=400)
            
            var = tk.BooleanVar()
            self.check_vars_tr[vid_name] = var
            tk.Checkbutton(row_fr, variable=var, bg="#f9ebed", activebackground="#f9ebed").grid(row=0, column=0, sticky="ns")
            
            thumb_lbl = tk.Label(row_fr, bg="#000000", width=35, height=6)
            thumb_lbl.grid(row=0, column=1, sticky="w", padx=5)
            self.thumb_labels[f"trash_{vid_name}"] = thumb_lbl  # [MỚI] Lưu thumbnail label
            
            thumb_path = os.path.join(trash_dir, ".thumbnails", f"{vid_name}.jpg")
            if os.path.exists(thumb_path):
                try:
                    photo = ImageTk.PhotoImage(Image.open(thumb_path))
                    self.photo_refs[f"trash_{vid_name}"] = photo 
                    thumb_lbl.config(image=photo, width=0, height=0)
                except: pass
            
            col2 = tk.Frame(row_fr, bg="#f9ebed")
            col2.grid(row=0, column=2, sticky="nw", padx=5)
            
            dur = saved_trash.get(vid_name, {}).get('duration', 0)
            tk.Label(col2, text=f"🎥 {vid_name}\n⏳ {dur} giây", font=("Arial", 9, "bold", "overstrike"), fg="#7f8c8d", bg="#f9ebed", justify="left", wraplength=330).pack(anchor="nw", pady=(0, 5))
            
            btn_fr = tk.Frame(col2, bg="#f9ebed")
            btn_fr.pack(anchor="nw", pady=5)
            tk.Button(btn_fr, text="▶ Xem", bg="#3498db", fg="white", font=("Arial", 8, "bold"), width=8, command=lambda p=os.path.join(trash_dir, vid_name): os.startfile(p)).pack(side="left", padx=(0, 5))
            tk.Button(btn_fr, text="♻️ Khôi phục", bg="#27ae60", fg="white", font=("Arial", 8, "bold"), width=10, command=lambda v=vid_name: self.restore_from_trash(v)).pack(side="left")
            
            tk.Label(row_fr, text=saved_trash.get(vid_name, {}).get("description", "(Trống)"), font=("Arial", 10), bg="#fdfefe", anchor="nw", justify="left", wraplength=600, relief="solid", bd=1, padx=5, pady=5).grid(row=0, column=3, sticky="nsew", padx=5)

        self.parent.update_idletasks()
        self.canvas_act.configure(scrollregion=self.canvas_act.bbox("all"))
        self.canvas_tr.configure(scrollregion=self.canvas_tr.bbox("all"))
        self._bind_mousewheel_to_all_children(self.frame_act)
        self._bind_mousewheel_to_all_children(self.frame_tr)
        
        # [THÊM DÒNG NÀY VÀO ĐÂY] Đồ thị vẽ xong thì bắt nó đếm luôn!
        self.update_missing_desc_count()

    def save_all_descriptions(self):
        if not self.current_project_id: return
        
        # 1. Đọc data tươi nhất từ ổ cứng (An toàn vì get_project_data có khóa)
        p_data = self.main_app.get_project_data(self.current_project_id)
        if "videos" not in p_data: p_data["videos"] = {}
        
        for vid_name, txt_widget in list(self.desc_entries.items()):
            if vid_name not in p_data["videos"]: p_data["videos"][vid_name] = {}
            
            try:
                p_data["videos"][vid_name]["description"] = txt_widget.get("1.0", tk.END).strip()
                
                if hasattr(self, 'audio_vars') and vid_name in self.audio_vars:
                    p_data["videos"][vid_name]["keep_audio"] = self.audio_vars[vid_name].get()
            except Exception:
                pass 
                
        # 2. Ghi đè data (An toàn vì save_project_data có khóa)
        self.main_app.save_project_data(self.current_project_id, p_data)
        
        # 3. Báo hiệu UI
        try:
            self.btn_save_tags.config(text="✅ ĐÃ LƯU", bg="#27ae60")
            self.main_app.root.after(2000, lambda: self.btn_save_tags.config(text="💾 LƯU MÔ TẢ", bg="#8e44ad"))
        except: pass

    def _on_context_change(self, event):
        if hasattr(self, "timer_context"):
            self.parent.after_cancel(self.timer_context)
        self.timer_context = self.parent.after(1000, self.save_project_context)

    def save_project_context(self):
        if not self.current_project_id: return
        
        # 1. Đọc data tươi nhất (Hàm get này tự có khóa bảo vệ bên main.py rồi, gọi thoải mái)
        p_data = self.main_app.get_project_data(self.current_project_id)
        
        # 2. Nhồi Bối cảnh vào
        p_data["product_context"] = self.txt_context.get("1.0", tk.END).strip()
        
        # 3. Lưu đè data (Hàm save này cũng tự có khóa bảo vệ bên main.py rồi)
        self.main_app.save_project_data(self.current_project_id, p_data)

    def _load_product_info(self, p_data):
        self.ent_product_name.delete(0, tk.END)
        self.ent_product_name.insert(0, p_data.get("product_name", ""))

        links = p_data.get("product_links", [])
        if len(links) < 6:
            links = list(links) + [""] * (6 - len(links))

        for idx, entry in enumerate(self.product_link_entries):
            entry.delete(0, tk.END)
            entry.insert(0, links[idx] if idx < len(links) else "")

    def _on_product_info_change(self, event):
        if hasattr(self, "timer_product_info"):
            self.parent.after_cancel(self.timer_product_info)
        self.timer_product_info = self.parent.after(800, self.save_product_info)

    def save_product_info(self):
        if not self.current_project_id:
            return

        p_data = self.main_app.get_project_data(self.current_project_id)
        p_data["product_name"] = self.ent_product_name.get().strip()
        p_data["product_links"] = [entry.get().strip() for entry in self.product_link_entries]
        self.main_app.save_project_data(self.current_project_id, p_data)

    def start_auto_tag(self):
        if not self.current_project_id: return messagebox.showwarning("Lỗi", "Phải chọn 1 Project trước!")
        kie_key = self.main_app.config.get("kie_key", "")
        if not kie_key:
            kie_key = simpledialog.askstring("Nhập API Key", "Dán Kie.ai Key vào đây:")
            if not kie_key: return
            self.main_app.config["kie_key"] = kie_key
            self.main_app.save_config()

        context = self.txt_context.get("1.0", tk.END).strip()
        self.btn_auto_tag.config(state="disabled", text="⏳ ĐANG SOI TẤT CẢ...", bg="#7f8c8d")
        
        p_data = self.main_app.get_project_data(self.current_project_id)
        ref1 = p_data.get("ref_img_1", "")
        ref2 = p_data.get("ref_img_2", "")
        threading.Thread(target=self.ai_handler.process_auto_tag, args=(kie_key, context, ref1, ref2), daemon=True).start()

    def start_single_auto_tag(self, vid_name):
        if not self.current_project_id: return
        kie_key = self.main_app.config.get("kie_key", "")
        if not kie_key:
            kie_key = simpledialog.askstring("Nhập API Key", "Dán Kie.ai Key vào đây:")
            if not kie_key: return
            self.main_app.config["kie_key"] = kie_key
            self.main_app.save_config()

        context = self.txt_context.get("1.0", tk.END).strip()
        
        # Báo hiệu UI đang soi 1 file
        if vid_name in self.desc_entries:
            self.desc_entries[vid_name].delete("1.0", tk.END)
            self.desc_entries[vid_name].insert("1.0", "⏳ AI đang soi ảnh, sếp đợi xíu...")
            
        p_data = self.main_app.get_project_data(self.current_project_id)
        ref1 = p_data.get("ref_img_1", "")
        ref2 = p_data.get("ref_img_2", "")
        threading.Thread(target=self.ai_handler.process_single_tag, args=(kie_key, vid_name, context, ref1, ref2), daemon=True).start()


    # =======================================================
    # [TÍNH NĂNG MỚI] ĐÓNG BĂNG VÀ ĐẾM MÔ TẢ
    # =======================================================
    def toggle_project_status(self):
        if not self.current_project_id: return
        proj = self.main_app.projects[self.current_project_id]
        current_status = proj.get("status", "active")
        
        # Đảo ngược trạng thái
        proj["status"] = "disabled" if current_status == "active" else "active"
        self.main_app.save_projects()
        
        # Load lại giao diện
        self.refresh_project_list()
        self.tree_proj.selection_set(self.current_project_id)
        self.main_app.tab2.update_combo_projects() # Cập nhật sang Tab 2

    def update_missing_desc_count(self):
        """ Đếm xem còn bao nhiêu ô chưa gõ chữ """
        empty_count = 0
        for vid_name, txt_widget in self.desc_entries.items():
            text = txt_widget.get("1.0", tk.END).strip()
            if not text:
                empty_count += 1
                
        if empty_count > 0:
            self.lbl_missing_desc.config(text=f"⚠️ Còn {empty_count} cảnh chưa có mô tả", fg="#c0392b")
        else:
            self.lbl_missing_desc.config(text="✅ Đã điền 100% mô tả", fg="#27ae60")

    def refresh_single_thumbnail(self, vid_name):
        """ Ép buộc tạo lại ảnh bìa 5 khung hình cho 1 video cụ thể """
        if not self.current_project_id: return
        
        folder = os.path.join(self.main_app.get_proj_dir(self.current_project_id), "Broll")
        vid_path = os.path.join(folder, vid_name)
        thumb_path = os.path.join(folder, ".thumbnails", f"{vid_name}.jpg")
        
        # Xóa ảnh cũ nếu có
        if os.path.exists(thumb_path):
            try: os.remove(thumb_path)
            except: pass
            
        # Gọi handler tạo lại ảnh (hàm này đã nâng cấp lên 5 khung hình ở file thumbnail_maker)
        def task():
            self.thumb_handler._create_thumb_direct_ffmpeg(vid_path, thumb_path, vid_name)
            # Chỉ cập nhật widget thumbnail của video này, không load lại toàn bộ bảng
            if vid_name in self.thumb_labels:
                try:
                    img = Image.open(thumb_path)
                    photo = ImageTk.PhotoImage(img)
                    self.photo_refs[vid_name] = photo
                    # Update widget trực tiếp từ main thread
                    self.main_app.root.after(0, lambda: self.thumb_labels[vid_name].config(image=photo, width=0, height=0))
                except:
                    pass
            
        threading.Thread(target=task, daemon=True).start()


    def refresh_all_thumbnails(self):
        """ Xóa sạch thư mục .thumbnails để ép tool tạo lại toàn bộ 5 khung hình """
        if not self.current_project_id: return
        if not messagebox.askyesno("Xác nhận", "Sếp có muốn làm mới toàn bộ ảnh bìa (5 khung hình) không?\n(Không mất mô tả, chỉ tạo lại ảnh)"): return
        
        folder = os.path.join(self.main_app.get_proj_dir(self.current_project_id), "Broll")
        thumb_dir = os.path.join(folder, ".thumbnails")
        
        if os.path.exists(thumb_dir):
            import shutil
            try: shutil.rmtree(thumb_dir)
            except: pass
            
        # Load lại list để nó tự kích hoạt luồng tạo ảnh bìa mới
        self.render_video_list()
        messagebox.showinfo("Xong", "Đang khởi tạo lại ảnh bìa ngầm, sếp đợi xíu là nó hiện ra nhé!")


    def select_ref_image(self, num):
        if not self.current_project_id: return
        file_path = filedialog.askopenfilename(title=f"Chọn ảnh Sản Phẩm Mẫu {num}", filetypes=[("Images", "*.jpg *.png *.jpeg")])
        if file_path:
            p_data = self.main_app.get_project_data(self.current_project_id)
            p_data[f"ref_img_{num}"] = file_path
            self.main_app.save_project_data(self.current_project_id, p_data)
            
            lbl = self.lbl_ref1 if num == 1 else self.lbl_ref2
            lbl.config(text=os.path.basename(file_path), fg="#27ae60")

    def clear_ref_images(self):
        if not self.current_project_id: return
        p_data = self.main_app.get_project_data(self.current_project_id)
        if "ref_img_1" in p_data: del p_data["ref_img_1"]
        if "ref_img_2" in p_data: del p_data["ref_img_2"]
        self.main_app.save_project_data(self.current_project_id, p_data)
        
        self.lbl_ref1.config(text="Chưa chọn", fg="gray")
        self.lbl_ref2.config(text="Chưa chọn", fg="gray")