# 📄 PDF Splitter với AI

Ứng dụng web tự động phân tích và tách file PDF chứa nhiều văn bản tố tụng hình sự sử dụng Google Gemini AI.

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/pdf-splitter?referralCode=baopham12ui)

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Tính năng

- 🤖 Sử dụng **Google Gemini 2.5 Flash** AI
- 📑 Tự động nhận diện các loại văn bản: Quyết định, Lệnh, Cáo trạng, Bản án...
- 📄 Hỗ trợ PDF scan (có hình ảnh)
- 📦 Tải về kết quả dạng ZIP
- 🎨 Giao diện web đẹp, dễ sử dụng

## 🚀 Deploy Online (1-Click)

### Railway (Khuyến nghị)
[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/baopham12ui/pdf-splitter-ai)

### Render
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/baopham12ui/pdf-splitter-ai)

### 1. Clone repository

```bash
git clone https://github.com/YOUR_USERNAME/pdf-splitter-ai.git
cd pdf-splitter-ai
```

### 2. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 3. (Tùy chọn) Cài OCR cho PDF scan

```bash
# macOS
brew install tesseract tesseract-lang
pip install pytesseract pillow

# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-vie
pip install pytesseract pillow
```

### 4. Chạy ứng dụng

```bash
python webapp.py
```

Truy cập: http://127.0.0.1:8080

## 🔑 Lấy API Key

### Google Gemini (Khuyến nghị)
1. Truy cập https://aistudio.google.com/app/apikey
2. Tạo API Key mới
3. Copy và paste vào ứng dụng

### DeepSeek
1. Truy cập https://platform.deepseek.com/api_keys
2. Tạo API Key mới
3. Copy và paste vào ứng dụng

## 📖 Hướng dẫn sử dụng

1. Chọn AI Provider (Google Gemini hoặc DeepSeek)
2. Nhập API Key
3. Kéo thả hoặc chọn file PDF
4. Nhấn "Bắt Đầu Phân Tích & Tách"
5. Tải kết quả về

## 🛠️ Công nghệ

- **Backend**: Flask, PyMuPDF
- **AI**: Google Gemini 2.5, DeepSeek
- **Frontend**: Bootstrap 5, JavaScript
- **OCR**: Tesseract (tùy chọn)

## 📝 Lưu ý

- Mỗi file PDF tối đa 20MB
- Tổng dung lượng tối đa 50MB
- Không lưu trữ dữ liệu người dùng

## 📄 License

MIT License - Xem file [LICENSE](LICENSE) để biết thêm chi tiết.

## 👨‍💻 Tác giả

- **Phạm Bảo** - [GitHub](https://github.com/YOUR_USERNAME)

---

⭐ Nếu thấy hữu ích, hãy star repo này!
