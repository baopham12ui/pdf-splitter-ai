import fitz
import os
import sys
import json
import pandas as pd
import datetime
from collections import defaultdict
import base64
import platform
import tkinter as tk
from tkinter import filedialog, messagebox, Listbox, Scrollbar, ttk, Text, simpledialog
import threading
import subprocess

# ===============================
#  KIỂM TRA & NẠP THƯ VIỆN GOOGLE
# ===============================
try:
    import google.generativeai as genai
    GOOGLE_AI_AVAILABLE = True
except Exception as e:
    print(f"⚠️ Không thể import Google AI ({e})")
    GOOGLE_AI_AVAILABLE = False

# ===============================
#  CẤU HÌNH CHƯƠNG TRÌNH
# ===============================
API_KEY_FILE = "google_api_key.txt"
MODEL_NAME = "gemini-2.0-flash"

AI_PROMPT_BASE = """
Phân tích các file PDF sau đây. Mỗi file chứa nhiều văn bản tố tụng hình sự.
Nhiệm vụ của bạn là tạo ra một danh sách JSON duy nhất cho TẤT CẢ các file.

Các file PDF theo thứ tự: {file_list}

Mỗi đối tượng trong danh sách phải đại diện cho một văn bản và có các khóa:
- "ten_file_goc": (string) Tên file PDF gốc chứa văn bản này (sử dụng tên từ danh sách trên).
- "ten_file_output": (string) Tên file đề xuất, định dạng: [Loại_văn_bản]_[Số_hiệu].pdf.
- "trang_bat_dau": (integer)
- "trang_ket_thuc": (integer)
- "nam_van_ban": (integer)

Hãy đảm bảo phân tích chính xác phạm vi trang và thông tin cho từng văn bản trong mỗi file.
Đảm bảo trang_bat_dau <= trang_ket_thuc và các giá trị là số nguyên dương.
Chỉ trả về khối code JSON duy nhất, không có lời giải thích hay ký tự ```json bao quanh.
"""

# ===============================
#  PHÂN TÍCH PDF VỚI AI (SỬ DỤNG BASE64 INLINE)
# ===============================
def analyze_pdfs_with_ai(api_key, pdf_file_paths, progress_callback):
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        return f"Lỗi cấu hình API: {e}", None, []

    progress_callback("BƯỚC 1: CHUẨN BỊ DỮ LIỆU PDF INLINE")
    pdf_parts = []
    file_list = list(pdf_file_paths.keys())
    error_files = {}
    total_size = 0

    total_files = len(pdf_file_paths)
    for i, (filename, file_path) in enumerate(pdf_file_paths.items()):
        try:
            file_size = os.path.getsize(file_path)
            if file_size > 20 * 1024 * 1024:
                raise ValueError("File vượt quá 20MB, không hỗ trợ inline.")
            total_size += file_size
            if total_size > 50 * 1024 * 1024:
                raise ValueError("Tổng kích thước file vượt quá giới hạn 50MB.")
            
            with open(file_path, 'rb') as f:
                pdf_bytes = f.read()
            encoded_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
            pdf_part = {
                "inline_data": {
                    "mime_type": "application/pdf",
                    "data": encoded_pdf
                }
            }
            pdf_parts.append(pdf_part)
        except Exception as e:
            error_files[filename] = str(e)
        progress_callback(f"Đang xử lý file {i+1}/{total_files}: {filename}")

    if not pdf_parts:
        return f"Không có file nào được xử lý thành công. Lỗi: {error_files}", None, []

    ai_prompt = AI_PROMPT_BASE.format(file_list=', '.join(file_list))

    progress_callback("BƯỚC 2: GỬI YÊU CẦU PHÂN TÍCH")
    model = genai.GenerativeModel(model_name=MODEL_NAME)
    request_content = [{"text": ai_prompt}] + pdf_parts

    try:
        response = model.generate_content(request_content, request_options={'timeout': 1200})
        json_string = response.text.strip().replace("```json", "").replace("```", "").strip()
        analysis_data = json.loads(json_string)
        
        # Validate analysis_data
        if not isinstance(analysis_data, list):
            raise ValueError("Dữ liệu từ AI không phải là list JSON.")
        for item in analysis_data:
            required_keys = ["ten_file_goc", "ten_file_output", "trang_bat_dau", "trang_ket_thuc", "nam_van_ban"]
            if not all(key in item for key in required_keys):
                raise ValueError(f"Item thiếu key: {item}")
            if not (isinstance(item["trang_bat_dau"], int) and isinstance(item["trang_ket_thuc"], int) and item["trang_bat_dau"] <= item["trang_ket_thuc"]):
                raise ValueError(f"Phạm vi trang không hợp lệ: {item}")
        
        return None, analysis_data, []
    except json.JSONDecodeError as e:
        return f"Lỗi parse JSON từ AI: {e}", None, []
    except Exception as e:
        return f"Lỗi khi gọi AI: {e}", None, []

# ===============================
#  TÁCH FILE THEO DỮ LIỆU AI
# ===============================
def run_multi_file_splitter(pdf_file_paths, analysis_data, progress_callback):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_output_dir = f"ket_qua_da_tach_{timestamp}"
    os.makedirs(base_output_dir, exist_ok=True)

    tasks = defaultdict(list)
    for item in analysis_data:
        tasks[item["ten_file_goc"]].append(item)

    progress_callback("BƯỚC 3: TÁCH FILE PDF")
    total_success = 0
    total_tasks = sum(len(rules) for rules in tasks.values())

    current = 0
    for filename, rules in tasks.items():
        if filename not in pdf_file_paths:
            continue

        sub_folder = os.path.join(base_output_dir, os.path.splitext(filename)[0])
        os.makedirs(sub_folder, exist_ok=True)

        try:
            doc = fitz.open(pdf_file_paths[filename])
            page_count = doc.page_count
            for rule in rules:
                current += 1
                progress_callback(f"Đang tách {current}/{total_tasks}: {rule['ten_file_output']}")
                start_page = rule["trang_bat_dau"]
                end_page = rule["trang_ket_thuc"]
                if not (1 <= start_page <= end_page <= page_count):
                    continue
                
                base_name = rule["ten_file_output"].replace(".pdf", "")
                year = rule.get("nam_van_ban")
                output_filename = f"{base_name}_{year}.pdf" if year else f"{base_name}.pdf"

                output_path = os.path.join(sub_folder, output_filename)
                new_doc = fitz.open()
                new_doc.insert_pdf(doc, from_page=start_page - 1, to_page=end_page - 1)
                new_doc.save(output_path)
                new_doc.close()
                total_success += 1
            doc.close()
        except Exception as e:
            pass

    # Export analysis to file
    analysis_file = os.path.join(base_output_dir, "analysis_data.json")
    with open(analysis_file, "w", encoding="utf-8") as f:
        json.dump(analysis_data, f, ensure_ascii=False, indent=4)

    return base_output_dir, total_success

# ===============================
#  GUI APPLICATION
# ===============================
class PDFSplitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Chương Trình Tách File PDF Với AI")
        self.root.geometry("800x600")
        self.root.configure(bg="#f0f0f0")

        self.api_key = self.load_api_key()
        self.pdf_files = None
        self.output_dir = None

        # Khung chọn thư mục
        self.frame_select = tk.Frame(root, bg="#f0f0f0")
        self.frame_select.pack(pady=10)

        self.btn_select_folder = tk.Button(self.frame_select, text="Chọn Thư Mục Chứa PDF", command=self.select_folder, bg="#4CAF50", fg="white", font=("Arial", 12))
        self.btn_select_folder.pack()

        # Listbox hiển thị file PDF
        self.label_files = tk.Label(root, text="Các File PDF Đã Chọn:", bg="#f0f0f0", font=("Arial", 10))
        self.label_files.pack(pady=5)

        self.listbox_files = Listbox(root, height=10, width=70, font=("Arial", 10))
        self.listbox_files.pack(pady=5)

        scrollbar = Scrollbar(root, orient="vertical")
        scrollbar.config(command=self.listbox_files.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox_files.config(yscrollcommand=scrollbar.set)

        # Progress bar
        self.progress = ttk.Progressbar(root, orient="horizontal", length=500, mode="indeterminate")
        self.progress.pack(pady=10)

        # Button bắt đầu xử lý
        self.btn_start = tk.Button(root, text="Bắt Đầu Phân Tích & Tách", command=self.start_processing, state="disabled", bg="#2196F3", fg="white", font=("Arial", 12))
        self.btn_start.pack(pady=10)

        # Button mở thư mục kết quả
        self.btn_open_output = tk.Button(root, text="Mở Thư Mục Kết Quả", command=self.open_output_folder, state="disabled", bg="#FF9800", fg="white", font=("Arial", 12))
        self.btn_open_output.pack(pady=10)

        # Text box for analysis result
        self.label_analysis = tk.Label(root, text="Kết Quả Phân Tích (JSON):", bg="#f0f0f0", font=("Arial", 10))
        self.label_analysis.pack(pady=5)

        self.text_analysis = Text(root, height=10, width=70, font=("Arial", 10))
        self.text_analysis.pack(pady=5)
        self.text_analysis.config(state="disabled")

        # Label trạng thái
        self.status_label = tk.Label(root, text="", fg="blue", bg="#f0f0f0", font=("Arial", 10))
        self.status_label.pack(pady=10)

    def load_api_key(self):
        if os.path.exists(API_KEY_FILE):
            with open(API_KEY_FILE, "r") as f:
                return f.read().strip()
        else:
            api_key = simpledialog.askstring("API Key", "Nhập Google API Key:", parent=self.root)
            if api_key:
                with open(API_KEY_FILE, "w") as f:
                    f.write(api_key)
                return api_key
            else:
                messagebox.showerror("Lỗi", "Không có API Key.")
                sys.exit()

    def select_folder(self):
        folder_path = filedialog.askdirectory(title="Chọn Thư Mục Chứa PDF")
        if folder_path:
            pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
            if not pdf_files:
                messagebox.showwarning("Cảnh Báo", "Thư mục không có file PDF.")
                return

            self.pdf_files = {pdf: os.path.join(folder_path, pdf) for pdf in pdf_files}
            self.listbox_files.delete(0, tk.END)
            for pdf in pdf_files:
                self.listbox_files.insert(tk.END, pdf)
            self.btn_start.config(state="normal")
            self.status_label.config(text=f"Đã chọn {len(pdf_files)} file PDF.", fg="green")

    def start_processing(self):
        if not self.pdf_files:
            messagebox.showerror("Lỗi", "Chưa chọn thư mục PDF.")
            return

        if not messagebox.askyesno("Cảnh Báo", "Dữ liệu PDF sẽ được tải lên Google AI. Đảm bảo không chứa thông tin nhạy cảm?"):
            return

        self.progress.start()
        self.btn_start.config(state="disabled")
        self.status_label.config(text="Đang xử lý...", fg="blue")

        threading.Thread(target=self.process_thread).start()

    def process_thread(self):
        error, analysis_data, file_names = analyze_pdfs_with_ai(self.api_key, self.pdf_files, self.update_status)

        if error:
            self.root.after(0, lambda: messagebox.showerror("Lỗi", error))
            self.root.after(0, self.reset_ui)
            return

        self.root.after(0, lambda: self.display_analysis(analysis_data))

        self.output_dir, total_success = run_multi_file_splitter(self.pdf_files, analysis_data, self.update_status)

        self.root.after(0, lambda: messagebox.showinfo("Hoàn Tất", f"Đã tách thành công {total_success} văn bản."))
        self.root.after(0, self.enable_open_button)

    def display_analysis(self, analysis_data):
        self.text_analysis.config(state="normal")
        self.text_analysis.delete(1.0, tk.END)
        self.text_analysis.insert(tk.END, json.dumps(analysis_data, ensure_ascii=False, indent=4))
        self.text_analysis.config(state="disabled")

    def update_status(self, message):
        self.root.after(0, lambda: self.status_label.config(text=message, fg="blue"))

    def reset_ui(self):
        self.progress.stop()
        self.btn_start.config(state="normal")
        self.status_label.config(text="", fg="blue")

    def enable_open_button(self):
        self.progress.stop()
        self.btn_open_output.config(state="normal")
        self.status_label.config(text="Xử lý hoàn tất.", fg="green")

    def open_output_folder(self):
        if self.output_dir:
            path = os.path.abspath(self.output_dir)
            if platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            elif platform.system() == "Windows":
                subprocess.Popen(f'explorer "{path}"', shell=True)
            else:
                subprocess.Popen(["xdg-open", path])

if __name__ == "__main__":
    if not GOOGLE_AI_AVAILABLE:
        print("❌ Thư viện google-generativeai chưa được cài.")
        sys.exit()

    root = tk.Tk()
    app = PDFSplitterApp(root)
    root.mainloop()