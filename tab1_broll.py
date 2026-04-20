import os
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import threading
from datetime import datetime
import subprocess
import gc
import re
import unicodedata
from PIL import Image, ImageTk

# Gọi 2 thằng đệ ra làm việc
from tab1_modules.thumbnail_maker import ThumbnailHandler
from tab1_modules.ai_vision import AIVisionHandler
from tab2_modules.ai_services import get_transcription
from shopee_export import normalize_shopee_product_link

class BRollTab:
    def __init__(self, parent, main_app):
        self.parent = parent
        self.main_app = main_app
        self.current_project_id = None
        self.photo_refs = {} 
        self.desc_entries = {} 
        self.thumb_labels = {}  # [MỚI] Dictionary lưu thumbnail labels
        self.product_link_entries = []
        self.audio_vars = {}
        self.active_page = 1
        self.trash_page = 1
        self.items_per_page = 30
        self.page_size_var = tk.StringVar(master=self.parent, value=str(self.items_per_page))
        self.filtered_act_files = []
        self.filtered_tr_files = []
        self.render_request_id = 0
        self.ai_task_states = {}
        self.ai_task_counter = 0
        self.voice_status_by_project = {}
        
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
        control_panel.columnconfigure(0, weight=1, uniform="tab1-top-panels")
        control_panel.columnconfigure(1, weight=1, uniform="tab1-top-panels")
        control_panel.columnconfigure(2, weight=1, uniform="tab1-top-panels")
        control_panel.rowconfigure(0, weight=1)

        # 1. KHUNG QUẢN LÝ VOICE
        fr_voice = tk.LabelFrame(control_panel, text=" 🎙️ Danh Sách Voice ", font=("Arial", 10, "bold"), bg="#ffffff", padx=10, pady=5)
        fr_voice.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        
        # [NÂNG CẤP] Bảng Treeview rộng rãi, có chia cột rõ ràng
        self.tree_voices = ttk.Treeview(fr_voice, columns=("name", "usage", "status"), show="headings", height=8)
        self.tree_voices.heading("name", text="Tên Voice")
        self.tree_voices.heading("usage", text="Số Lần Dùng")
        self.tree_voices.heading("status", text="Trạng Thái")
        
        # Thu gọn cột để cửa sổ thường vẫn nhìn thấy cụm nút thao tác
        self.tree_voices.column("name", width=150, minwidth=120, anchor="w", stretch=True)
        self.tree_voices.column("usage", width=120, minwidth=70, anchor="center", stretch=False)
        self.tree_voices.column("status", width=190, minwidth=150, anchor="w", stretch=True)
        
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
        fr_tools.grid(row=0, column=1, sticky="nsew", padx=5)

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
        self.lbl_ref1 = tk.Label(fr_ref, text="Chưa chọn", bg="#ffffff", font=("Arial", 8), fg="gray", width=22, anchor="w")
        self.lbl_ref1.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_ref2 = tk.Button(fr_ref, text="🖼️ Ảnh Mẫu 2", bg="#f39c12", fg="white", font=("Arial", 8, "bold"), command=lambda: self.select_ref_image(2))
        self.btn_ref2.pack(side="left", padx=(5, 5))
        self.lbl_ref2 = tk.Label(fr_ref, text="Chưa chọn", bg="#ffffff", font=("Arial", 8), fg="gray", width=22, anchor="w")
        self.lbl_ref2.pack(side="left", fill="x", expand=True, padx=(0, 4))
        
        # Nút xóa ảnh mẫu
        tk.Button(fr_ref, text="❌", bg="#e74c3c", fg="white", font=("Arial", 8), command=self.clear_ref_images).pack(side="right")

        # [MỚI] KHUNG THÔNG TIN SẢN PHẨM / LINK SHOPEE
        fr_product_info = tk.LabelFrame(
            control_panel,
            text=" Thông tin Shopee & Quản lý Job Hàng Loạt ",
            font=("Arial", 10, "bold"),
            bg="#ffffff",
            padx=12,
            pady=8,
        )
        fr_product_info.grid(row=0, column=2, sticky="nsew", padx=(5, 0))

        row_name = tk.Frame(fr_product_info, bg="#ffffff")
        row_name.pack(fill="x", pady=(0, 6))
        tk.Label(
            row_name,
            text="Tên sản phẩm:",
            bg="#ffffff",
            fg="#8e44ad",
            font=("Arial", 10, "bold"),
            width=14,
            anchor="w",
        ).pack(side="left")
        self.ent_product_name = tk.Entry(row_name, font=("Arial", 10))
        self.ent_product_name.pack(side="left", fill="x", expand=True)
        self.ent_product_name.bind("<KeyRelease>", self._on_product_info_change)

        row_stock = tk.Frame(fr_product_info, bg="#ffffff")
        row_stock.pack(fill="x", pady=(0, 6))
        self.var_shopee_out_of_stock = tk.BooleanVar(value=False)
        tk.Checkbutton(
            row_stock,
            text="Hết hàng: không ghi vào file job Shopee",
            variable=self.var_shopee_out_of_stock,
            command=self.save_product_info,
            bg="#ffffff",
            fg="#c0392b",
            font=("Arial", 9, "bold"),
            activebackground="#ffffff",
        ).pack(anchor="w")

        self.product_link_entries = []
        links_column = tk.Frame(fr_product_info, bg="#ffffff")
        links_column.pack(fill="x", expand=True)
        for idx in range(6):
            row_link = tk.Frame(links_column, bg="#ffffff")
            row_link.pack(fill="x", pady=2)
            tk.Label(
                row_link,
                text=f"Link sản phẩm {idx + 1}:",
                bg="#ffffff",
                font=("Arial", 10),
                width=14,
                anchor="w",
            ).pack(side="left")
            ent_link = tk.Entry(row_link, font=("Arial", 10))
            ent_link.pack(side="left", fill="x", expand=True)
            ent_link.bind("<KeyRelease>", self._on_product_info_change)
            ent_link.bind("<FocusOut>", self._on_product_link_focus_out)
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
        self.ent_search.bind("<KeyRelease>", self._on_search_change) # Gõ phím là tự động lọc luôn

        tk.Label(bulk_fr, text="Mỗi trang:", font=("Arial", 9, "bold"), bg="#dfe6e9").pack(side="left", padx=(15, 5))
        self.cmb_page_size = ttk.Combobox(
            bulk_fr,
            width=5,
            state="readonly",
            values=("30", "50", "100"),
            textvariable=self.page_size_var,
        )
        self.cmb_page_size.pack(side="left")
        self.cmb_page_size.bind("<<ComboboxSelected>>", self._on_page_size_change)
        
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

        self.active_pagination_fr = tk.Frame(self.tab_active, bg="#fdfefe", padx=10, pady=6)
        self.active_pagination_fr.pack(fill="x")
        self.lbl_act_page_info = tk.Label(self.active_pagination_fr, text=f"0 cảnh | {self.items_per_page} cảnh/trang", bg="#fdfefe", fg="#34495e", font=("Arial", 9, "bold"))
        self.lbl_act_page_info.pack(side="left")
        self.btn_act_next = tk.Button(self.active_pagination_fr, text="Sau ▶", width=8, font=("Arial", 8, "bold"), command=lambda: self._change_page("active", 1))
        self.btn_act_next.pack(side="right")
        self.lbl_act_page_status = tk.Label(self.active_pagination_fr, text="Không có dữ liệu", bg="#fdfefe", fg="#7f8c8d", font=("Arial", 9))
        self.lbl_act_page_status.pack(side="right", padx=8)
        self.btn_act_prev = tk.Button(self.active_pagination_fr, text="◀ Trước", width=8, font=("Arial", 8, "bold"), command=lambda: self._change_page("active", -1))
        self.btn_act_prev.pack(side="right")

        active_canvas_wrapper = tk.Frame(self.tab_active, bg="#fdfefe")
        active_canvas_wrapper.pack(fill="both", expand=True)

        # Canvas Tab Active
        self.canvas_act = tk.Canvas(active_canvas_wrapper, bg="#fdfefe")
        self.scroll_act = ttk.Scrollbar(active_canvas_wrapper, orient="vertical", command=self.canvas_act.yview)
        self.frame_act = tk.Frame(self.canvas_act, bg="#fdfefe")
        self.frame_act.bind("<Configure>", lambda e: self.canvas_act.configure(scrollregion=self.canvas_act.bbox("all")))
        self.frame_act_window = self.canvas_act.create_window((0, 0), window=self.frame_act, anchor="nw")
        self.canvas_act.configure(yscrollcommand=self.scroll_act.set)
        self.canvas_act.bind("<Configure>", self._sync_canvas_window_widths)
        self.canvas_act.pack(side="left", fill="both", expand=True)
        self.scroll_act.pack(side="right", fill="y")

        self.trash_pagination_fr = tk.Frame(self.tab_trash, bg="#fdfefe", padx=10, pady=6)
        self.trash_pagination_fr.pack(fill="x")
        self.lbl_tr_page_info = tk.Label(self.trash_pagination_fr, text=f"0 cảnh | {self.items_per_page} cảnh/trang", bg="#fdfefe", fg="#34495e", font=("Arial", 9, "bold"))
        self.lbl_tr_page_info.pack(side="left")
        self.btn_tr_next = tk.Button(self.trash_pagination_fr, text="Sau ▶", width=8, font=("Arial", 8, "bold"), command=lambda: self._change_page("trash", 1))
        self.btn_tr_next.pack(side="right")
        self.lbl_tr_page_status = tk.Label(self.trash_pagination_fr, text="Không có dữ liệu", bg="#fdfefe", fg="#7f8c8d", font=("Arial", 9))
        self.lbl_tr_page_status.pack(side="right", padx=8)
        self.btn_tr_prev = tk.Button(self.trash_pagination_fr, text="◀ Trước", width=8, font=("Arial", 8, "bold"), command=lambda: self._change_page("trash", -1))
        self.btn_tr_prev.pack(side="right")

        trash_canvas_wrapper = tk.Frame(self.tab_trash, bg="#fdfefe")
        trash_canvas_wrapper.pack(fill="both", expand=True)

        # Canvas Tab Trash
        self.canvas_tr = tk.Canvas(trash_canvas_wrapper, bg="#fdfefe")
        self.scroll_tr = ttk.Scrollbar(trash_canvas_wrapper, orient="vertical", command=self.canvas_tr.yview)
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
        self._update_pagination_ui("active", 0, 1, 1)
        self._update_pagination_ui("trash", 0, 1, 1)
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

    def _on_search_change(self, event=None):
        self.save_all_descriptions()
        self.render_video_list(reset_pages=True)

    def _on_page_size_change(self, event=None):
        self.save_all_descriptions()
        try:
            self.items_per_page = max(1, int(self.page_size_var.get()))
        except (TypeError, ValueError):
            self.items_per_page = 30
            self.page_size_var.set(str(self.items_per_page))
        self.render_video_list(reset_pages=True)

    def _get_paginated_files(self, files_list, current_page):
        per_page = max(1, self.items_per_page)
        total_items = len(files_list)
        total_pages = max(1, (total_items + per_page - 1) // per_page) if total_items else 1
        current_page = min(max(1, current_page), total_pages)
        start_index = (current_page - 1) * per_page
        end_index = start_index + per_page
        return files_list[start_index:end_index], current_page, total_pages, total_items

    def _update_pagination_ui(self, tab_name, total_items, current_page, total_pages):
        if tab_name == "active":
            count_label = self.lbl_act_page_info
            status_label = self.lbl_act_page_status
            prev_button = self.btn_act_prev
            next_button = self.btn_act_next
        else:
            count_label = self.lbl_tr_page_info
            status_label = self.lbl_tr_page_status
            prev_button = self.btn_tr_prev
            next_button = self.btn_tr_next

        count_label.config(text=f"{total_items} cảnh | {self.items_per_page} cảnh/trang")
        status_label.config(text=f"Trang {current_page}/{total_pages}" if total_items else "Không có dữ liệu")
        prev_button.config(state="normal" if total_items and current_page > 1 else "disabled")
        next_button.config(state="normal" if total_items and current_page < total_pages else "disabled")

    def _change_page(self, tab_name, delta):
        self.save_all_descriptions()
        if tab_name == "active":
            self.active_page = max(1, self.active_page + delta)
        else:
            self.trash_page = max(1, self.trash_page + delta)
        self.render_video_list()

    def _is_render_request_current(self, project_id, render_request_id):
        if render_request_id is None:
            return project_id == self.current_project_id
        return project_id == self.current_project_id and render_request_id == self.render_request_id

    def _get_ai_task_key(self, project_id, vid_name):
        return (project_id, vid_name)

    def _get_ai_task_state(self, project_id, vid_name):
        return self.ai_task_states.get(self._get_ai_task_key(project_id, vid_name))

    def _clear_ai_task_state(self, project_id, vid_name, task_token=None):
        key = self._get_ai_task_key(project_id, vid_name)
        state = self.ai_task_states.get(key)
        if not state:
            return
        if task_token is not None and state.get("token") != task_token:
            return
        self.ai_task_states.pop(key, None)

    def _clear_ai_task_states_for_project(self, project_id):
        keys_to_remove = [key for key in self.ai_task_states if key[0] == project_id]
        for key in keys_to_remove:
            self.ai_task_states.pop(key, None)

    def _set_visible_description_text(self, project_id, vid_name, text):
        if project_id != self.current_project_id:
            return False

        txt_widget = self.desc_entries.get(vid_name)
        if not txt_widget:
            return False

        try:
            txt_widget.delete("1.0", tk.END)
            txt_widget.insert("1.0", text)
            return True
        except tk.TclError:
            return False

    def _is_transient_ai_message(self, text):
        clean_text = (text or "").strip()
        return clean_text.startswith("⏳ AI ") or clean_text.startswith("❌ ")

    def _start_ai_task(self, project_id, vid_name, message):
        self.ai_task_counter += 1
        task_token = self.ai_task_counter
        self.ai_task_states[self._get_ai_task_key(project_id, vid_name)] = {
            "token": task_token,
            "state": "running",
            "message": message,
        }
        self._set_visible_description_text(project_id, vid_name, message)
        return task_token

    def _set_ai_task_error(self, project_id, vid_name, task_token, message):
        state = self._get_ai_task_state(project_id, vid_name)
        if not state or state.get("token") != task_token:
            return

        state["state"] = "error"
        state["message"] = message
        self._set_visible_description_text(project_id, vid_name, message)
        self.update_missing_desc_count()

    def _complete_ai_task(self, project_id, vid_name, task_token, description):
        state = self._get_ai_task_state(project_id, vid_name)
        if not state or state.get("token") != task_token:
            return

        self._clear_ai_task_state(project_id, vid_name, task_token)

        if project_id not in self.main_app.projects:
            return

        clean_description = description.strip()
        p_data = self.main_app.get_project_data(project_id)

        if vid_name in p_data.get("videos", {}):
            target_dict = p_data["videos"]
        elif vid_name in p_data.get("trash", {}):
            target_dict = p_data["trash"]
        else:
            p_data.setdefault("videos", {})
            target_dict = p_data["videos"]

        if vid_name not in target_dict or not isinstance(target_dict[vid_name], dict):
            target_dict[vid_name] = {}

        target_dict[vid_name]["description"] = clean_description
        self.main_app.save_project_data(project_id, p_data)
        self._set_visible_description_text(project_id, vid_name, clean_description)
        self.update_missing_desc_count()


    def refresh_project_list(self):
        for item in self.tree_proj.get_children(): self.tree_proj.delete(item)
        sorted_projects = sorted(self.main_app.projects.items(), key=lambda x: x[1]['created_at'], reverse=True)
        for pid, pdata in sorted_projects:
            name = pdata['name']
            # Hiện icon khóa nếu đang ẩn
            if pdata.get('status') == 'disabled': name = f"⏸️ {name} (Đã Ẩn)"
            self.tree_proj.insert("", "end", iid=pid, values=(name,))

    def _get_voice_status_store(self, project_id):
        return self.voice_status_by_project.setdefault(project_id, {})

    def _get_voice_display_status(self, project_id, voice_name, p_data=None):
        if not project_id:
            return "Chưa bóc SRT"

        status_store = self._get_voice_status_store(project_id)
        if voice_name in status_store:
            return status_store[voice_name]

        if p_data is None:
            p_data = self.main_app.get_project_data(project_id)

        if voice_name in p_data.get("voice_srt_cache", {}):
            return "✅ Đã xong"

        return "⏳ Chờ bóc SRT"

    def _refresh_voice_row(self, voice_name, project_id=None):
        project_id = project_id or self.current_project_id
        if not project_id or project_id != self.current_project_id:
            return

        p_data = self.main_app.get_project_data(project_id)
        usage = p_data.get("voice_usage", {}).get(voice_name, 0)
        status_text = self._get_voice_display_status(project_id, voice_name, p_data)
        voice_path = os.path.join(self.main_app.get_proj_dir(project_id), "Voices", voice_name)

        if not os.path.exists(voice_path):
            if self.tree_voices.exists(voice_name):
                self.tree_voices.delete(voice_name)
            return

        values = (voice_name, f"{usage} lần", status_text)
        if self.tree_voices.exists(voice_name):
            self.tree_voices.item(voice_name, values=values)
        else:
            self.tree_voices.insert("", "end", iid=voice_name, values=values)

    def _set_voice_status(self, project_id, voice_name, status_text):
        if not project_id or not voice_name:
            return

        self._get_voice_status_store(project_id)[voice_name] = status_text

        if project_id == self.current_project_id:
            self.main_app.root.after(0, lambda vn=voice_name, pid=project_id: self._refresh_voice_row(vn, pid))

    def _clear_voice_status(self, project_id, voice_name):
        if not project_id:
            return

        status_store = self._get_voice_status_store(project_id)
        status_store.pop(voice_name, None)

    def _parse_voice_log_status(self, msg):
        clean_msg = str(msg or "").strip()
        if not clean_msg:
            return None, None

        match = re.match(r"^\[([^\]]+)\]\s*(.+)$", clean_msg)
        if match:
            return match.group(1).strip(), match.group(2).strip()

        match = re.match(r"^✅ Đã bóp SRT xong:\s*(.+)$", clean_msg)
        if match:
            return match.group(1).strip(), "✅ Đã xong"

        match = re.match(r"^❌ Lỗi bóc SRT\s+([^:]+):\s*(.+)$", clean_msg)
        if match:
            voice_name, error_text = match.groups()
            return voice_name.strip(), f"❌ {error_text.strip()}"

        match = re.match(r"^✂️ Phát hiện câu test ở đầu\s+([^,]+),\s*cắt\s*([0-9.]+)s", clean_msg)
        if match:
            voice_name, seconds = match.groups()
            return voice_name.strip(), f"✂️ Cắt câu test {seconds}s"

        return None, None

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
            self.render_video_list(reset_pages=True)

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
        voice_files = sorted(
            [f for f in os.listdir(voice_dir) if f.lower().endswith(('.mp3', '.wav', '.m4a'))],
            key=str.lower,
        )
        
        for f in voice_files:
            count = voice_usage.get(f, 0) # Lấy số lần dùng, mặc định là 0
            status_text = self._get_voice_display_status(self.current_project_id, f, p_data)
            self.tree_voices.insert("", "end", iid=f, values=(f, f"{count} lần", status_text))

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
                    self._clear_voice_status(self.current_project_id, file_name)
                        
                except Exception as e:
                    messagebox.showerror("Lỗi", f"Không thể xóa file: {e}")
            self.load_voices()

    def _normalize_voice_marker_text(self, text):
        normalized_text = unicodedata.normalize("NFD", str(text or ""))
        normalized_text = "".join(ch for ch in normalized_text if unicodedata.category(ch) != "Mn")
        normalized_text = normalized_text.lower()
        normalized_text = re.sub(r"[^a-z0-9\s]", " ", normalized_text)
        return re.sub(r"\s+", " ", normalized_text).strip()

    def _looks_like_voice_test_intro(self, text):
        normalized_text = self._normalize_voice_marker_text(text)
        if not normalized_text:
            return False

        trigger_phrases = [
            "day la giong noi thu cua toi",
            "day la giong noi thu cua tui",
            "giong noi thu cua toi",
            "giong noi thu cua tui",
            "day la giong noi thu",
            "giong noi thu",
        ]
        if any(phrase in normalized_text for phrase in trigger_phrases):
            return True

        words = set(normalized_text.split())
        if not {"giong", "noi", "thu"}.issubset(words):
            return False

        extra_hits = sum(word in words for word in ["day", "la", "cua", "toi", "tui"])
        return extra_hits >= 2

    def _parse_voice_timeline_text(self, timeline_text):
        timeline_items = []
        pattern = re.compile(r"\[\s*([0-9]+(?:\.[0-9]+)?)s\s*-\s*([0-9]+(?:\.[0-9]+)?)s\s*\]:\s*(.+)")
        for line in (timeline_text or "").splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue

            start_text, end_text, caption = match.groups()
            timeline_items.append(
                {
                    "start": float(start_text),
                    "end": float(end_text),
                    "text": caption.strip(),
                }
            )
        return timeline_items

    def _detect_voice_test_intro_end(self, timeline_text):
        accumulated_text = ""

        for idx, item in enumerate(self._parse_voice_timeline_text(timeline_text)):
            if idx >= 6 or item["start"] > 15.0:
                break

            caption_text = self._normalize_voice_marker_text(item.get("text", ""))
            if not caption_text:
                continue

            accumulated_text = f"{accumulated_text} {caption_text}".strip()
            if self._looks_like_voice_test_intro(caption_text) or self._looks_like_voice_test_intro(accumulated_text):
                return max(0.0, round(item["end"] + 0.05, 2))

        return 0.0

    def _trim_voice_file(self, voice_path, trim_start_seconds):
        if trim_start_seconds <= 0:
            return False

        base_name, extension = os.path.splitext(voice_path)
        temp_path = f"{base_name}.__trim__{extension}"
        extension = extension.lower()

        codec_args = []
        if extension == ".mp3":
            codec_args = ["-codec:a", "libmp3lame", "-q:a", "2"]
        elif extension == ".wav":
            codec_args = ["-codec:a", "pcm_s16le"]
        elif extension == ".m4a":
            codec_args = ["-codec:a", "aac", "-b:a", "192k"]

        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{trim_start_seconds:.2f}",
            "-i",
            voice_path,
            *codec_args,
            temp_path,
        ]

        creation_flags = 0x08000000 if os.name == 'nt' else 0
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            os.replace(temp_path, voice_path)
            return True
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _transcribe_voice_with_auto_trim(self, project_id, voice_name, voice_path):
        mode = self.main_app.config.get("boc_bang_mode", "groq")
        log_cb = lambda msg, pid=project_id: self._log_extract(msg, project_id=pid)

        srt_text = ""
        for attempt in range(3):
            srt_text = get_transcription(voice_path, voice_name, mode, self.main_app.config, log_cb)
            trim_start_seconds = self._detect_voice_test_intro_end(srt_text)

            if trim_start_seconds <= 0:
                break

            self._log_extract(
                f"✂️ Phát hiện câu test ở đầu {voice_name}, cắt {trim_start_seconds:.2f}s...",
                project_id=project_id,
            )
            if not self._trim_voice_file(voice_path, trim_start_seconds):
                break

        return srt_text

    def import_voice(self):
        if not self.current_project_id: return
        files = filedialog.askopenfilenames(title="Chọn Voice", filetypes=[("Audio", "*.mp3 *.wav *.m4a")])
        if files:
            project_id = self.current_project_id
            voice_dir = os.path.join(self.main_app.get_proj_dir(self.current_project_id), "Voices")
            os.makedirs(voice_dir, exist_ok=True)
            
            # 1. Gọi cuốn sổ JSON ra (Hàm get này tự có khóa bảo vệ bên main.py rồi)
            p_data = self.main_app.get_project_data(project_id)
            if "voice_usage" not in p_data: 
                p_data["voice_usage"] = {}
            if "voice_srt_cache" not in p_data:  # [MỚI] Khởi tạo SRT cache
                p_data["voice_srt_cache"] = {}
                
            for f in files: 
                file_name = os.path.basename(f)
                shutil.copy2(f, os.path.join(voice_dir, file_name))
                self._set_voice_status(project_id, file_name, "⏳ Chờ bóc SRT")
                
                # Khai báo lính mới
                if file_name not in p_data["voice_usage"]:
                    p_data["voice_usage"][file_name] = 0
            
            # 2. Lưu lại (Hàm save này cũng tự có khóa bảo vệ bên main.py rồi, gọi thẳng tay!)
            self.main_app.save_project_data(project_id, p_data)
            
            # 3. [MỚI] Bắt đầu extract SRT cho từng voice mới (chạy background)
            for f in files:
                file_name = os.path.basename(f)
                file_path = os.path.join(voice_dir, file_name)
                thread = threading.Thread(target=self._extract_voice_srt_async, args=(project_id, file_name, file_path), daemon=True)
                thread.start()
                
            self.load_voices()
    
    def _extract_voice_srt_async(self, project_id, voice_name, voice_path):
        """[MỚI] Bóc SRT từ voice file và lưu vào cache (chạy background)"""
        try:
            srt_text = self._transcribe_voice_with_auto_trim(project_id, voice_name, voice_path)

            if project_id not in self.main_app.projects:
                return
            
            # Lưu vào cache
            p_data = self.main_app.get_project_data(project_id)
            if "voice_srt_cache" not in p_data:
                p_data["voice_srt_cache"] = {}
            
            p_data["voice_srt_cache"][voice_name] = srt_text
            self.main_app.save_project_data(project_id, p_data)
            
            self._log_extract(f"✅ Đã bóp SRT xong: {voice_name}", project_id=project_id)
        except Exception as e:
            self._log_extract(f"❌ Lỗi bóc SRT {voice_name}: {str(e)}", project_id=project_id)
    
    def _log_extract(self, msg, project_id=None):
        """[MỚI] Ghi log extraction (để in ra log nếu có)"""
        voice_name, status_text = self._parse_voice_log_status(msg)
        if project_id and voice_name and status_text:
            self._set_voice_status(project_id, voice_name, status_text)

        log_line = f"[Tab 1 Voice] {msg}"
        try:
            print(log_line)
        except UnicodeEncodeError:
            print(log_line.encode("ascii", errors="replace").decode("ascii"))
    
    def get_voice_srt(self, voice_name):
        """[MỚI] Lấy SRT của voice (từ cache)"""
        p_data = self.main_app.get_project_data(self.current_project_id)
        
        # Check xem có cache không
        if "voice_srt_cache" in p_data and voice_name in p_data["voice_srt_cache"]:
            cached_srt = p_data["voice_srt_cache"][voice_name]
            if self._detect_voice_test_intro_end(cached_srt) <= 0:
                return cached_srt
        
        return None
    
    def get_voice_srt_or_extract(self, project_id, voice_name, voice_path):
        """[MỚI] Lấy SRT từ cache, nếu chưa có thì extract (blocking)"""
        p_data = self.main_app.get_project_data(project_id)
        
        # 1. Check cache trước
        if "voice_srt_cache" in p_data and voice_name in p_data["voice_srt_cache"]:
            cached_srt = p_data["voice_srt_cache"][voice_name]
            if self._detect_voice_test_intro_end(cached_srt) <= 0:
                return cached_srt
            self._log_extract(f"⚠️ Phát hiện voice {voice_name} còn câu test trong cache, đang bóc lại...", project_id=project_id)
        
        # 2. Nếu chưa cache hoặc cache còn câu test, extract ngay (blocking call)
        try:
            srt_text = self._transcribe_voice_with_auto_trim(project_id, voice_name, voice_path)
            
            # Lưu vào cache
            if "voice_srt_cache" not in p_data:
                p_data["voice_srt_cache"] = {}
            p_data["voice_srt_cache"][voice_name] = srt_text
            self.main_app.save_project_data(project_id, p_data)
            self._log_extract(f"✅ Đã bóp SRT xong: {voice_name}", project_id=project_id)
            
            return srt_text
        except Exception as e:
            self._log_extract(f"❌ Lỗi bóc SRT {voice_name}: {str(e)}", project_id=project_id)
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
                    "shopee_out_of_stock": False,
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
        self.render_video_list(reset_pages=True)
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
        self.lbl_ref1.config(text=self._format_ref_image_name(ref1), fg="#27ae60" if ref1 else "gray")
        self.lbl_ref2.config(text=self._format_ref_image_name(ref2), fg="#27ae60" if ref2 else "gray")

    def delete_project(self):
        if not self.current_project_id: return
        if messagebox.askyesno("Xóa", "Xóa toàn bộ Project và File trong thư mục Tool?"):
            project_id = self.current_project_id
            shutil.rmtree(self.main_app.get_proj_dir(project_id), ignore_errors=True)
            del self.main_app.projects[project_id]
            self.main_app.save_projects()
            self.refresh_project_list()
            self._clear_ai_task_states_for_project(project_id)
            self.voice_status_by_project.pop(project_id, None)
            
            self.current_project_id = None
            self.active_page = 1
            self.trash_page = 1
            self.filtered_act_files = []
            self.filtered_tr_files = []
            self.render_request_id += 1
            self.lbl_proj_name.config(text="Chưa chọn Project nào")
            for item in self.tree_voices.get_children(): self.tree_voices.delete(item)
            for widget in self.frame_act.winfo_children(): widget.destroy()
            for widget in self.frame_tr.winfo_children(): widget.destroy()
            self.txt_context.delete("1.0", tk.END)
            self.ent_product_name.delete(0, tk.END)
            self.var_shopee_out_of_stock.set(False)
            self._update_pagination_ui("active", 0, 1, 1)
            self._update_pagination_ui("trash", 0, 1, 1)
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

    def render_video_list(self, reset_pages=False):
        if reset_pages:
            self.active_page = 1
            self.trash_page = 1

        self.render_request_id += 1
        current_request_id = self.render_request_id

        for w in self.frame_act.winfo_children(): w.destroy()
        for w in self.frame_tr.winfo_children(): w.destroy()
        self.photo_refs.clear()
        self.desc_entries.clear()
        self.thumb_labels.clear()
        self.audio_vars.clear()
        self.check_vars_act.clear()
        self.check_vars_tr.clear()
        self.canvas_act.configure(scrollregion=(0, 0, 0, 0))
        self.canvas_tr.configure(scrollregion=(0, 0, 0, 0))
        self.canvas_act.yview_moveto(0)
        self.canvas_tr.yview_moveto(0)
        self.filtered_act_files = []
        self.filtered_tr_files = []
        self._update_pagination_ui("active", 0, 1, 1)
        self._update_pagination_ui("trash", 0, 1, 1)

        if not self.current_project_id:
            self.update_missing_desc_count()
            return

        project_id = self.current_project_id
        proj_dir = self.main_app.get_proj_dir(self.current_project_id)
        broll_dir = os.path.join(proj_dir, "Broll")
        trash_dir = os.path.join(proj_dir, "Broll_Trash")
        os.makedirs(broll_dir, exist_ok=True)
        os.makedirs(trash_dir, exist_ok=True)

        # Lấy từ khóa tìm kiếm (nếu có)
        keyword = self.ent_search.get().strip().lower() if hasattr(self, 'ent_search') else ""

        # Đã thêm điều kiện: keyword in f.lower() để lọc file
        all_act_files = sorted(
            [f for f in os.listdir(broll_dir) if f.lower().endswith(('.mp4', '.mov')) and keyword in f.lower()],
            key=lambda x: os.path.getmtime(os.path.join(broll_dir, x)),
            reverse=True
        )
        
        all_tr_files = sorted(
            [f for f in os.listdir(trash_dir) if f.lower().endswith(('.mp4', '.mov')) and keyword in f.lower()],
            key=lambda x: os.path.getmtime(os.path.join(trash_dir, x)),
            reverse=True
        )

        self.filtered_act_files = all_act_files
        self.filtered_tr_files = all_tr_files

        act_files, self.active_page, act_total_pages, act_total = self._get_paginated_files(all_act_files, self.active_page)
        tr_files, self.trash_page, tr_total_pages, tr_total = self._get_paginated_files(all_tr_files, self.trash_page)

        self._update_pagination_ui("active", act_total, self.active_page, act_total_pages)
        self._update_pagination_ui("trash", tr_total, self.trash_page, tr_total_pages)

        if act_total == 0:
            empty_active_text = "Không tìm thấy cảnh nào phù hợp." if keyword else "Chưa có cảnh nào trong danh sách đang dùng."
            tk.Label(self.frame_act, text=empty_active_text, fg="#7f8c8d", font=("Arial", 10, "italic")).pack(pady=20)

        if tr_total == 0:
            empty_trash_text = "Không có cảnh nào trong thùng rác khớp từ khóa." if keyword else "Thùng rác đang trống."
            tk.Label(self.frame_tr, text=empty_trash_text, fg="#7f8c8d", font=("Arial", 10, "italic")).pack(pady=20)

        self.update_missing_desc_count()

        if not act_files and not tr_files:
            return

        if act_files:
            tk.Label(self.frame_act, text="⏳ Đang load ảnh...", fg="#e67e22").pack(pady=10)
        if tr_files:
            tk.Label(self.frame_tr, text="⏳ Đang load ảnh...", fg="#e67e22").pack(pady=10)
        
        threading.Thread(
            target=self.thumb_handler.generate,
            args=(project_id, broll_dir, trash_dir, act_files, tr_files, current_request_id),
            daemon=True,
        ).start()

        remaining_act_files = [f for f in all_act_files if f not in act_files]
        remaining_tr_files = [f for f in all_tr_files if f not in tr_files]
        if remaining_act_files or remaining_tr_files:
            threading.Thread(
                target=self.thumb_handler.generate,
                args=(project_id, broll_dir, trash_dir, remaining_act_files, remaining_tr_files, None, False),
                daemon=True,
            ).start()

    def _build_video_rows(self, project_id, broll_dir, trash_dir, act_files, tr_files, p_data, render_request_id=None):
        if not self._is_render_request_current(project_id, render_request_id):
            return

        for w in self.frame_act.winfo_children(): w.destroy()
        for w in self.frame_tr.winfo_children(): w.destroy()
        
        self.check_vars_act.clear()
        self.check_vars_tr.clear()
        self.thumb_labels.clear()  # [MỚI] Clear thumbnail labels
        self.audio_vars.clear()
        
        saved_vids = p_data.get('videos', {})
        if not act_files:
            active_empty_text = "Không tìm thấy cảnh nào phù hợp." if self.ent_search.get().strip() else "Chưa có cảnh nào trong danh sách đang dùng."
            tk.Label(self.frame_act, text=active_empty_text, fg="#7f8c8d", font=("Arial", 10, "italic")).pack(pady=20)
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
            ai_state = self._get_ai_task_state(project_id, vid_name)
            if ai_state:
                description_text = ai_state.get("message", description_text)
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
                self._clear_ai_task_state(project_id, v_name)
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
            self.audio_vars[vid_name] = keep_audio_var
            tk.Checkbutton(col4, text="🔊 Bật Âm", variable=keep_audio_var, bg="#ffffff", font=("Arial", 9, "bold"), fg="#c0392b", command=self.save_all_descriptions).pack(anchor="nw")
            tk.Label(col4, text="(Giữ tiếng gốc)", bg="#ffffff", font=("Arial", 8, "italic"), fg="#7f8c8d").pack(anchor="nw", padx=20)

            usage = saved_vids.get(vid_name, {}).get('usage_count', 0)
            usage_color = "#27ae60" if usage == 0 else ("#f39c12" if usage < 3 else "#c0392b")
            tk.Label(row_fr, text=f"{usage} lần", font=("Arial", 16, "bold"), fg=usage_color, bg="#ffffff").grid(row=0, column=5, sticky="e", padx=15)

        saved_trash = p_data.get('trash', {})
        if not tr_files:
            trash_empty_text = "Không có cảnh nào trong thùng rác khớp từ khóa." if self.ent_search.get().strip() else "Thùng rác đang trống."
            tk.Label(self.frame_tr, text=trash_empty_text, fg="#7f8c8d", font=("Arial", 10, "italic")).pack(pady=20)
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
        self._sync_canvas_window_widths()
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
            if self._get_ai_task_state(self.current_project_id, vid_name):
                continue

            if vid_name not in p_data["videos"]: p_data["videos"][vid_name] = {}
            
            try:
                widget_text = txt_widget.get("1.0", tk.END).strip()
                if self._is_transient_ai_message(widget_text):
                    continue

                p_data["videos"][vid_name]["description"] = widget_text
                
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
        self.var_shopee_out_of_stock.set(bool(p_data.get("shopee_out_of_stock", False)))

        links = p_data.get("product_links", [])
        if len(links) < 6:
            links = list(links) + [""] * (6 - len(links))

        for idx, entry in enumerate(self.product_link_entries):
            entry.delete(0, tk.END)
            entry.insert(0, normalize_shopee_product_link(links[idx] if idx < len(links) else ""))

    def _normalize_product_link_entry(self, entry):
        raw_value = entry.get()
        cleaned_value = normalize_shopee_product_link(raw_value)
        if cleaned_value != raw_value.strip():
            entry.delete(0, tk.END)
            entry.insert(0, cleaned_value)
        return cleaned_value

    def _on_product_link_focus_out(self, event):
        if event.widget in self.product_link_entries:
            self._normalize_product_link_entry(event.widget)
            self.save_product_info()

    def _on_product_info_change(self, event):
        if hasattr(self, "timer_product_info"):
            self.parent.after_cancel(self.timer_product_info)
        self.timer_product_info = self.parent.after(800, self.save_product_info)

    def save_product_info(self):
        if not self.current_project_id:
            return

        cleaned_links = [self._normalize_product_link_entry(entry) for entry in self.product_link_entries]

        p_data = self.main_app.get_project_data(self.current_project_id)
        p_data["product_name"] = self.ent_product_name.get().strip()
        p_data["shopee_out_of_stock"] = bool(self.var_shopee_out_of_stock.get())
        p_data["product_links"] = cleaned_links
        self.main_app.save_project_data(self.current_project_id, p_data)

    def start_auto_tag(self):
        if not self.current_project_id: return messagebox.showwarning("Lỗi", "Phải chọn 1 Project trước!")
        kie_key = self.main_app.config.get("kie_key", "")
        if not kie_key:
            kie_key = simpledialog.askstring("Nhập API Key", "Dán Kie.ai Key vào đây:")
            if not kie_key: return
            self.main_app.config["kie_key"] = kie_key
            self.main_app.save_config()

        project_id = self.current_project_id
        self.save_all_descriptions()
        context = self.txt_context.get("1.0", tk.END).strip()
        self.btn_auto_tag.config(state="disabled", text="⏳ ĐANG SOI TẤT CẢ...", bg="#7f8c8d")

        p_data = self.main_app.get_project_data(project_id)
        saved_videos = p_data.get("videos", {})
        target_video_names = self.filtered_act_files if self.filtered_act_files else list(saved_videos.keys())

        videos_to_tag = []
        for vid_name in target_video_names:
            if vid_name not in saved_videos:
                continue

            if self._get_ai_task_state(project_id, vid_name):
                continue

            current_text = saved_videos.get(vid_name, {}).get("description", "").strip()
            if current_text:
                continue

            task_token = self._start_ai_task(project_id, vid_name, "⏳ AI đang soi ảnh (kèm mẫu)...")
            videos_to_tag.append((vid_name, task_token))

        if not videos_to_tag:
            self.btn_auto_tag.config(state="normal", text="🧠 AI TỰ NHÌN & ĐIỀN", bg="#d35400")
            return

        ref1 = p_data.get("ref_img_1", "")
        ref2 = p_data.get("ref_img_2", "")
        threading.Thread(target=self.ai_handler.process_auto_tag, args=(project_id, videos_to_tag, kie_key, context, ref1, ref2), daemon=True).start()

    def start_single_auto_tag(self, vid_name):
        if not self.current_project_id: return
        kie_key = self.main_app.config.get("kie_key", "")
        if not kie_key:
            kie_key = simpledialog.askstring("Nhập API Key", "Dán Kie.ai Key vào đây:")
            if not kie_key: return
            self.main_app.config["kie_key"] = kie_key
            self.main_app.save_config()

        project_id = self.current_project_id
        context = self.txt_context.get("1.0", tk.END).strip()

        hint_text = ""
        if vid_name in self.desc_entries:
            try:
                current_text = self.desc_entries[vid_name].get("1.0", tk.END).strip()
                if current_text and not self._is_transient_ai_message(current_text):
                    hint_text = current_text
            except tk.TclError:
                pass

        task_token = self._start_ai_task(project_id, vid_name, "⏳ AI đang soi ảnh, sếp đợi xíu...")
            
        p_data = self.main_app.get_project_data(project_id)
        ref1 = p_data.get("ref_img_1", "")
        ref2 = p_data.get("ref_img_2", "")
        threading.Thread(target=self.ai_handler.process_single_tag, args=(project_id, task_token, kie_key, vid_name, context, ref1, ref2, hint_text), daemon=True).start()


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
        if not self.current_project_id:
            self.lbl_missing_desc.config(text="Chưa có cảnh để điền mô tả", fg="#7f8c8d")
            return

        p_data = self.main_app.get_project_data(self.current_project_id)
        saved_videos = p_data.get("videos", {})
        target_names = self.filtered_act_files if self.filtered_act_files is not None else list(saved_videos.keys())

        empty_count = 0
        total_count = len(target_names)

        for vid_name in target_names:
            saved_text = saved_videos.get(vid_name, {}).get("description", "").strip()
            ai_state = self._get_ai_task_state(self.current_project_id, vid_name)

            if ai_state:
                text = saved_text
            elif vid_name in self.desc_entries:
                try:
                    widget_text = self.desc_entries[vid_name].get("1.0", tk.END).strip()
                except tk.TclError:
                    widget_text = None

                if widget_text is None:
                    text = saved_text
                elif self._is_transient_ai_message(widget_text):
                    text = saved_text
                else:
                    text = widget_text
            else:
                text = saved_text
            if not text:
                empty_count += 1

        if total_count == 0:
            self.lbl_missing_desc.config(text="Chưa có cảnh để điền mô tả", fg="#7f8c8d")
        elif empty_count > 0:
            self.lbl_missing_desc.config(text=f"⚠️ Thiếu mô tả {empty_count}/{total_count} cảnh", fg="#c0392b")
        else:
            self.lbl_missing_desc.config(text=f"✅ Đã điền 100% mô tả ({total_count} cảnh)", fg="#27ae60")

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


    def _format_ref_image_name(self, file_path, max_len=20):
        if not file_path or not os.path.exists(file_path):
            return "Chưa chọn"

        file_name = os.path.basename(file_path)
        if len(file_name) <= max_len:
            return file_name

        name, ext = os.path.splitext(file_name)
        keep_len = max(8, max_len - len(ext) - 3)
        return f"{name[:keep_len]}...{ext}"

    def select_ref_image(self, num):
        if not self.current_project_id: return
        file_path = filedialog.askopenfilename(
            title=f"Chọn ảnh Sản Phẩm Mẫu {num}",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp"), ("All files", "*.*")]
        )
        if file_path:
            p_data = self.main_app.get_project_data(self.current_project_id)
            p_data[f"ref_img_{num}"] = file_path
            self.main_app.save_project_data(self.current_project_id, p_data)
            
            lbl = self.lbl_ref1 if num == 1 else self.lbl_ref2
            lbl.config(text=self._format_ref_image_name(file_path), fg="#27ae60")

    def clear_ref_images(self):
        if not self.current_project_id: return
        p_data = self.main_app.get_project_data(self.current_project_id)
        if "ref_img_1" in p_data: del p_data["ref_img_1"]
        if "ref_img_2" in p_data: del p_data["ref_img_2"]
        self.main_app.save_project_data(self.current_project_id, p_data)
        
        self.lbl_ref1.config(text="Chưa chọn", fg="gray")
        self.lbl_ref2.config(text="Chưa chọn", fg="gray")
