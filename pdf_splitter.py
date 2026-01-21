"""
PDF Splitter với Google Gemini AI
Phiên bản Desktop - Chỉ cần chạy file này
"""

import fitz
import os
import sys
import json
import datetime
import base64
import platform
import tkinter as tk
from tkinter import filedialog, messagebox, Listbox, Scrollbar, ttk, Text, simpledialog
import threading
import subprocess
import webbrowser

# Google GenAI
try:
    from google import genai
    GOOGLE_AI_AVAILABLE = True
except ImportError:
    GOOGLE_AI_AVAILABLE = False

# ===============================
#  CẤU HÌNH
# ===============================
API_KEY_FILE = "google_api_key.txt"
GEMINI_MODEL = "gemini-2.5-flash"

AI_PROMPT = """
Phân tích KỸ LƯỠNG file PDF này. File chứa nhiều văn bản tố tụng hình sự.

QUAN TRỌNG: 
- Đọc KỸ nội dung từng trang để xác định CHÍNH XÁC ranh giới giữa các văn bản
- Mỗi văn bản thường bắt đầu với tiêu đề như: "QUYẾT ĐỊNH", "LỆNH", "BẢN KẾT LUẬN", "CÁO TRẠNG", "BẢN ÁN"...
- Tìm số hiệu văn bản (ví dụ: 16/QĐ-ĐTTH, 79/LTG-VKS...)
- Xác định năm từ ngày tháng trong văn bản
- KHÔNG ĐƯỢC BỊA hoặc ĐỂ SÓT văn bản nào

Tên file: {filename}

Trả về JSON array với mỗi object có:
- "ten_file_goc": "{filename}"
- "ten_file_output": "[Loai_van_ban]_[So_hieu].pdf"
- "trang_bat_dau": (integer)
- "trang_ket_thuc": (integer)  
- "nam_van_ban": (integer)

Chỉ trả về JSON array, không giải thích.
"""


def analyze_pdf_with_gemini(api_key, filename, file_path, progress_callback):
    """Phân tích PDF với Google Gemini"""
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        return f"Lỗi cấu hình API: {e}", None

    progress_callback("Đang đọc file PDF...")
    
    try:
        with open(file_path, 'rb') as f:
            pdf_bytes = f.read()
        
        file_size = len(pdf_bytes)
        if file_size > 20 * 1024 * 1024:
            return "File vượt quá 20MB", None
            
        pdf_part = genai.types.Part.from_bytes(
            data=pdf_bytes,
            mime_type="application/pdf"
        )
    except Exception as e:
        return f"Lỗi đọc file: {e}", None

    progress_callback("Đang gửi yêu cầu phân tích đến AI...")
    
    prompt = AI_PROMPT.format(filename=filename)
    contents = [prompt, pdf_part]

    max_retries = 3
    for attempt in range(max_retries):
        try:
            progress_callback(f"Đang phân tích... (lần {attempt + 1})")
            
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents
            )
            
            json_string = response.text.strip()
            if "```json" in json_string:
                json_string = json_string.split("```json")[1].split("```")[0]
            elif "```" in json_string:
                json_string = json_string.split("```")[1].split("```")[0]
            json_string = json_string.strip()
            
            analysis_data = json.loads(json_string)

            if not isinstance(analysis_data, list):
                return "AI trả về dữ liệu không hợp lệ", None

            if len(analysis_data) == 0:
                return "AI không tìm thấy văn bản nào. Vui lòng thử lại.", None

            for item in analysis_data:
                required_keys = ["ten_file_goc", "ten_file_output", "trang_bat_dau", "trang_ket_thuc", "nam_van_ban"]
                if not all(key in item for key in required_keys):
                    return f"Dữ liệu thiếu trường: {item}", None

            return None, analysis_data

        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                continue
            return f"Lỗi parse JSON: {e}", None
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower() or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    progress_callback(f"Quota tạm hết, đợi 30 giây...")
                    import time
                    time.sleep(30)
                    continue
                return "Quota API đã hết. Vui lòng đợi 1 phút hoặc tạo API key mới.", None
            return f"Lỗi: {e}", None
    
    return "Không thể phân tích sau nhiều lần thử", None


def split_pdf(file_path, analysis_data, progress_callback):
    """Tách file PDF theo dữ liệu phân tích"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_dir = os.path.join(os.path.dirname(file_path), f"ket_qua_{base_name}_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)

    total_success = 0
    results = []

    try:
        doc = fitz.open(file_path)
        page_count = doc.page_count

        for i, rule in enumerate(analysis_data):
            progress_callback(f"Đang tách văn bản {i+1}/{len(analysis_data)}...")
            
            start_page = rule["trang_bat_dau"]
            end_page = rule["trang_ket_thuc"]

            if not (1 <= start_page <= end_page <= page_count):
                results.append(f"❌ {rule['ten_file_output']}: Trang không hợp lệ ({start_page}-{end_page})")
                continue

            base_name = rule["ten_file_output"].replace(".pdf", "")
            year = rule.get("nam_van_ban")
            output_filename = f"{base_name}_{year}.pdf" if year else f"{base_name}.pdf"
            
            # Làm sạch tên file
            output_filename = "".join(c for c in output_filename if c.isalnum() or c in "._- ")

            output_path = os.path.join(output_dir, output_filename)
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=start_page - 1, to_page=end_page - 1)
            new_doc.save(output_path)
            new_doc.close()

            total_success += 1
            results.append(f"✅ {output_filename} (Trang {start_page}-{end_page})")

        doc.close()
        
        # Lưu analysis data
        analysis_file = os.path.join(output_dir, "phan_tich.json")
        with open(analysis_file, "w", encoding="utf-8") as f:
            json.dump(analysis_data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        results.append(f"❌ Lỗi: {e}")

    return output_dir, total_success, results


class PDFSplitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📄 Tách File PDF Với AI")
        self.root.geometry("700x650")
        self.root.configure(bg="#f5f5f5")
        
        # Căn giữa cửa sổ
        self.center_window()
        
        self.api_key = None
        self.pdf_file = None
        self.output_dir = None

        self.create_widgets()
        self.load_api_key()

    def center_window(self):
        self.root.update_idletasks()
        w = 700
        h = 650
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f'{w}x{h}+{x}+{y}')

    def create_widgets(self):
        # Header
        header = tk.Frame(self.root, bg="#4f46e5", height=80)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        title = tk.Label(header, text="📄 Tách File PDF Với AI", 
                        font=("Arial", 18, "bold"), fg="white", bg="#4f46e5")
        title.pack(pady=25)

        # Main content
        main = tk.Frame(self.root, bg="#f5f5f5", padx=20, pady=15)
        main.pack(fill="both", expand=True)

        # API Key section
        api_frame = tk.LabelFrame(main, text="🔑 Google API Key", font=("Arial", 10, "bold"), 
                                  bg="#f5f5f5", padx=10, pady=10)
        api_frame.pack(fill="x", pady=(0, 10))

        self.api_entry = tk.Entry(api_frame, font=("Arial", 11), show="*", width=50)
        self.api_entry.pack(side="left", fill="x", expand=True)

        btn_get_key = tk.Button(api_frame, text="Lấy Key", command=self.open_get_key,
                               bg="#10b981", fg="white", font=("Arial", 9))
        btn_get_key.pack(side="right", padx=(10, 0))

        # File selection
        file_frame = tk.LabelFrame(main, text="📁 Chọn File PDF", font=("Arial", 10, "bold"),
                                   bg="#f5f5f5", padx=10, pady=10)
        file_frame.pack(fill="x", pady=(0, 10))

        self.file_label = tk.Label(file_frame, text="Chưa chọn file", font=("Arial", 10),
                                   bg="#f5f5f5", fg="#666")
        self.file_label.pack(side="left", fill="x", expand=True)

        btn_select = tk.Button(file_frame, text="Chọn File", command=self.select_file,
                              bg="#3b82f6", fg="white", font=("Arial", 10))
        btn_select.pack(side="right")

        # Progress
        self.progress = ttk.Progressbar(main, mode="indeterminate", length=400)
        self.progress.pack(pady=10)

        self.status_label = tk.Label(main, text="", font=("Arial", 10), bg="#f5f5f5", fg="#4f46e5")
        self.status_label.pack()

        # Start button
        self.btn_start = tk.Button(main, text="🚀 Bắt Đầu Phân Tích & Tách", 
                                   command=self.start_processing,
                                   bg="#4f46e5", fg="white", font=("Arial", 12, "bold"),
                                   state="disabled", width=30, height=2)
        self.btn_start.pack(pady=15)

        # Results
        result_frame = tk.LabelFrame(main, text="📋 Kết Quả", font=("Arial", 10, "bold"),
                                     bg="#f5f5f5", padx=10, pady=10)
        result_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.result_text = Text(result_frame, font=("Arial", 9), height=12, wrap="word")
        self.result_text.pack(fill="both", expand=True)
        
        scrollbar = Scrollbar(result_frame, command=self.result_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.result_text.config(yscrollcommand=scrollbar.set)

        # Open folder button
        self.btn_open = tk.Button(main, text="📂 Mở Thư Mục Kết Quả",
                                  command=self.open_output_folder,
                                  bg="#f59e0b", fg="white", font=("Arial", 10),
                                  state="disabled")
        self.btn_open.pack(pady=5)

    def load_api_key(self):
        if os.path.exists(API_KEY_FILE):
            with open(API_KEY_FILE, "r") as f:
                key = f.read().strip()
                self.api_entry.insert(0, key)
                self.api_key = key

    def save_api_key(self):
        key = self.api_entry.get().strip()
        if key:
            with open(API_KEY_FILE, "w") as f:
                f.write(key)
            self.api_key = key

    def open_get_key(self):
        webbrowser.open("https://aistudio.google.com/app/apikey")

    def select_file(self):
        file_path = filedialog.askopenfilename(
            title="Chọn File PDF",
            filetypes=[("PDF files", "*.pdf")]
        )
        if file_path:
            self.pdf_file = file_path
            filename = os.path.basename(file_path)
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            self.file_label.config(text=f"{filename} ({size_mb:.1f} MB)", fg="#333")
            self.update_start_button()

    def update_start_button(self):
        api_key = self.api_entry.get().strip()
        if api_key and self.pdf_file:
            self.btn_start.config(state="normal")
        else:
            self.btn_start.config(state="disabled")

    def start_processing(self):
        self.save_api_key()
        
        if not self.api_key:
            messagebox.showerror("Lỗi", "Vui lòng nhập API Key")
            return

        if not self.pdf_file:
            messagebox.showerror("Lỗi", "Vui lòng chọn file PDF")
            return

        self.progress.start()
        self.btn_start.config(state="disabled")
        self.result_text.delete(1.0, tk.END)

        threading.Thread(target=self.process_thread, daemon=True).start()

    def process_thread(self):
        filename = os.path.basename(self.pdf_file)
        
        # Phân tích với AI
        error, analysis_data = analyze_pdf_with_gemini(
            self.api_key, filename, self.pdf_file, self.update_status
        )

        if error:
            self.root.after(0, lambda: self.show_error(error))
            return

        # Hiển thị kết quả phân tích
        self.root.after(0, lambda: self.show_analysis(analysis_data))

        # Tách file
        self.update_status("Đang tách file PDF...")
        self.output_dir, total_success, results = split_pdf(
            self.pdf_file, analysis_data, self.update_status
        )

        # Hiển thị kết quả
        self.root.after(0, lambda: self.show_results(total_success, results))

    def update_status(self, message):
        self.root.after(0, lambda: self.status_label.config(text=message))

    def show_error(self, error):
        self.progress.stop()
        self.btn_start.config(state="normal")
        self.status_label.config(text="")
        messagebox.showerror("Lỗi", error)

    def show_analysis(self, data):
        self.result_text.insert(tk.END, f"📊 Phân tích: Tìm thấy {len(data)} văn bản\n\n")

    def show_results(self, total_success, results):
        self.progress.stop()
        self.btn_start.config(state="normal")
        self.btn_open.config(state="normal")
        self.status_label.config(text=f"✅ Hoàn tất! Đã tách {total_success} văn bản")
        
        for result in results:
            self.result_text.insert(tk.END, result + "\n")
        
        messagebox.showinfo("Hoàn Tất", f"Đã tách thành công {total_success} văn bản!")

    def open_output_folder(self):
        if self.output_dir and os.path.exists(self.output_dir):
            if platform.system() == "Darwin":
                subprocess.Popen(["open", self.output_dir])
            elif platform.system() == "Windows":
                os.startfile(self.output_dir)
            else:
                subprocess.Popen(["xdg-open", self.output_dir])


def main():
    if not GOOGLE_AI_AVAILABLE:
        try:
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", "google-genai", "PyMuPDF"])
            from google import genai
        except:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Lỗi", "Cần cài đặt thư viện:\npip install google-genai PyMuPDF")
            sys.exit(1)

    root = tk.Tk()
    app = PDFSplitterApp(root)
    
    # Bind API key change
    app.api_entry.bind("<KeyRelease>", lambda e: app.update_start_button())
    
    root.mainloop()


if __name__ == "__main__":
    main()
