# Hướng dẫn đóng gói PDF Splitter AI

## 📦 Đã có sẵn (macOS)

Thư mục `dist/` chứa:
- `PDF_Splitter_AI.app` - Ứng dụng macOS, double-click để chạy
- `PDF_Splitter_AI` - File thực thi cho Terminal

## 🪟 Tạo file .exe cho Windows

### Bước 1: Trên máy Windows, cài Python

Tải từ: https://www.python.org/downloads/

### Bước 2: Cài thư viện

```cmd
pip install pyinstaller google-genai PyMuPDF
```

### Bước 3: Copy file `pdf_splitter.py` sang Windows

### Bước 4: Chạy lệnh đóng gói

```cmd
pyinstaller --onefile --windowed --name "PDF_Splitter_AI" pdf_splitter.py
```

### Bước 5: Lấy file .exe

File `PDF_Splitter_AI.exe` sẽ nằm trong thư mục `dist/`

## 🌐 Chia sẻ qua GitHub

1. Tạo repository mới trên GitHub
2. Upload các file: `pdf_splitter.py`, `requirements.txt`, `README.md`
3. Tạo Release và đính kèm file .exe hoặc .app

## 📝 Lưu ý

- File .exe/app khá lớn (~100MB) vì chứa cả Python runtime
- Người dùng Windows cần có Visual C++ Redistributable
- macOS có thể yêu cầu cho phép chạy app không rõ nguồn gốc
