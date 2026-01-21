"""
Web App Tách File PDF Với AI
Flask + Google Generative AI
"""

import os
import sys
import json
import datetime
import base64
import zipfile
import tempfile
import shutil
import requests
import time
from collections import defaultdict
from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename

try:
    import fitz
except ImportError:
    print("❌ Cần cài PyMuPDF: pip install PyMuPDF")
    fitz = None

# OCR support
try:
    import pytesseract
    from PIL import Image
    import io as io_module
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# Google GenAI (new API)
try:
    from google import genai
    GOOGLE_AI_AVAILABLE = True
except ImportError:
    print("⚠️ Google AI không khả dụng. Cài: pip install google-genai")
    GOOGLE_AI_AVAILABLE = False

# ===============================
#  CẤU HÌNH
# ===============================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'pdf-splitter-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

UPLOAD_FOLDER = tempfile.mkdtemp()
OUTPUT_FOLDER = tempfile.mkdtemp()
ALLOWED_EXTENSIONS = {'pdf'}

MODEL_NAME = "gemini-2.0-flash"
GEMINI_PREVIEW_MODEL = "gemini-2.5-flash"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

AI_PROMPT_BASE = """
Phân tích KỸ LƯỠNG các file PDF sau đây. Mỗi file chứa nhiều văn bản tố tụng hình sự.

QUAN TRỌNG: 
- Đọc KỸ nội dung từng trang để xác định CHÍNH XÁC ranh giới giữa các văn bản
- Mỗi văn bản thường bắt đầu với tiêu đề như: "QUYẾT ĐỊNH", "LỆNH", "BẢN KẾT LUẬN", "CÁO TRẠNG", "BẢN ÁN"...
- Tìm số hiệu văn bản (ví dụ: 16/QĐ-ĐTTH, 79/LTG-VKS...)
- Xác định năm từ ngày tháng trong văn bản
- KHÔNG ĐƯỢC BỊA hoặc ĐỂ SÓT văn bản nào

Các file PDF theo thứ tự: {file_list}

Mỗi đối tượng trong danh sách JSON phải có:
- "ten_file_goc": (string) Tên file PDF gốc
- "ten_file_output": (string) Định dạng: [Loai_van_ban]_[So_hieu].pdf (ví dụ: Quyet_dinh_khoi_to_vu_an_16_QD.pdf)
- "trang_bat_dau": (integer) Trang đầu tiên của văn bản
- "trang_ket_thuc": (integer) Trang cuối cùng của văn bản  
- "nam_van_ban": (integer) Năm ban hành văn bản

Lưu ý:
- Một văn bản có thể kéo dài nhiều trang
- Đảm bảo trang_bat_dau <= trang_ket_thuc
- Kiểm tra kỹ để không bỏ sót văn bản nào
- Chỉ trả về JSON array, không giải thích
"""


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(file_path):
    """Trích xuất text từ PDF, hỗ trợ OCR cho PDF scan"""
    try:
        doc = fitz.open(file_path)
        text_content = []
        has_text = False
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            text = page.get_text().strip()
            
            # Nếu không có text và OCR khả dụng, thử OCR
            if not text and OCR_AVAILABLE:
                # Render page thành hình ảnh
                mat = fitz.Matrix(2, 2)  # zoom 2x cho chất lượng tốt hơn
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                # OCR với tiếng Việt
                try:
                    text = pytesseract.image_to_string(img, lang='vie')
                except:
                    text = pytesseract.image_to_string(img)
            
            if text:
                has_text = True
            text_content.append(f"\n{'='*60}\n[TRANG {page_num + 1}]\n{'='*60}\n{text}")
        
        doc.close()
        return "\n".join(text_content), doc.page_count, has_text
    except Exception as e:
        return f"Lỗi đọc PDF: {e}", 0, False


def analyze_pdfs_with_deepseek(api_key, pdf_file_paths):
    """Phân tích PDF với DeepSeek API"""
    file_list = list(pdf_file_paths.keys())
    
    # Trích xuất text từ tất cả PDF
    all_text = []
    total_pages = {}
    any_has_text = False
    
    for filename, file_path in pdf_file_paths.items():
        text, page_count, has_text = extract_text_from_pdf(file_path)
        total_pages[filename] = page_count
        if has_text:
            any_has_text = True
        all_text.append(f"\n{'#'*60}\nFILE: {filename} (Tổng: {page_count} trang)\n{'#'*60}\n{text}")
        print(f"[DEBUG] Extracted {page_count} pages from {filename}, text length: {len(text)}, has_text: {has_text}")
    
    # Kiểm tra nếu không có text nào
    if not any_has_text:
        if not OCR_AVAILABLE:
            return "PDF là file scan (hình ảnh). Cần cài OCR: pip install pytesseract pillow. Hoặc dùng Google Gemini.", None
        else:
            return "Không thể trích xuất text từ PDF. File có thể bị mã hóa hoặc hỏng.", None
    
    combined_text = "\n".join(all_text)
    print(f"[DEBUG] Total combined text length: {len(combined_text)}")
    
    # Giới hạn text để tránh vượt context
    if len(combined_text) > 120000:
        combined_text = combined_text[:120000] + "\n...[ĐÃ CẮT BỚT]..."
    
    ai_prompt = AI_PROMPT_BASE.format(file_list=', '.join(file_list))
    
    # Thêm thông tin tổng số trang
    pages_info = ", ".join([f"{f}: {p} trang" for f, p in total_pages.items()])
    full_prompt = f"{ai_prompt}\n\nTHÔNG TIN FILE:\n{pages_info}\n\nNỘI DUNG CHI TIẾT TỪNG TRANG:\n{combined_text}"
    
    print(f"[DEBUG] Full prompt length: {len(full_prompt)}")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": """Bạn là chuyên gia phân tích văn bản pháp luật Việt Nam. 
Nhiệm vụ: Phân tích PDF chứa nhiều văn bản tố tụng hình sự và xác định CHÍNH XÁC:
- Ranh giới từng văn bản (trang bắt đầu, trang kết thúc)
- Loại văn bản (Quyết định, Lệnh, Bản kết luận, Cáo trạng, Bản án...)
- Số hiệu văn bản
- Năm ban hành

LUÔN trả về JSON array hợp lệ. KHÔNG bịa thông tin."""},
            {"role": "user", "content": full_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 8000
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=300)
            
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    time.sleep(30)
                    continue
                return "Quota DeepSeek đã hết. Vui lòng đợi hoặc kiểm tra tài khoản.", None
            
            if response.status_code != 200:
                return f"Lỗi DeepSeek API: {response.status_code} - {response.text}", None
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Debug: in ra response
            print(f"[DEBUG] DeepSeek response: {content[:500]}...")
            
            json_string = content.strip()
            # Loại bỏ markdown code blocks
            if "```json" in json_string:
                json_string = json_string.split("```json")[1].split("```")[0]
            elif "```" in json_string:
                json_string = json_string.split("```")[1].split("```")[0]
            json_string = json_string.strip()
            
            analysis_data = json.loads(json_string)
            
            if not isinstance(analysis_data, list):
                return "Dữ liệu từ AI không phải là list JSON", None
            
            # Kiểm tra nếu kết quả rỗng
            if len(analysis_data) == 0:
                return "AI trả về kết quả rỗng. Vui lòng thử lại hoặc đổi sang Google Gemini.", None
            
            for item in analysis_data:
                required_keys = ["ten_file_goc", "ten_file_output", "trang_bat_dau", "trang_ket_thuc", "nam_van_ban"]
                if not all(key in item for key in required_keys):
                    return f"Dữ liệu thiếu trường bắt buộc: {item}", None
            
            return None, analysis_data
            
        except json.JSONDecodeError as e:
            return f"Lỗi parse JSON từ DeepSeek: {e}", None
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                continue
            return "DeepSeek API timeout. Vui lòng thử lại.", None
        except Exception as e:
            return f"Lỗi khi gọi DeepSeek: {e}", None
    
    return "Không thể kết nối DeepSeek sau nhiều lần thử", None


def analyze_pdfs_with_google(api_key, pdf_file_paths):
    """Phân tích PDF với Google AI (New API)"""
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        return f"Lỗi cấu hình API: {e}", None

    file_list = list(pdf_file_paths.keys())
    total_size = 0
    
    # Chuẩn bị nội dung gửi đến API
    contents = []
    
    # Thêm prompt
    ai_prompt = AI_PROMPT_BASE.format(file_list=', '.join(file_list))
    contents.append(ai_prompt)
    
    # Thêm các file PDF
    for filename, file_path in pdf_file_paths.items():
        try:
            file_size = os.path.getsize(file_path)
            if file_size > 20 * 1024 * 1024:
                return f"File {filename} vượt quá 20MB", None
            total_size += file_size
            if total_size > 50 * 1024 * 1024:
                return "Tổng kích thước file vượt quá 50MB", None

            # Upload file using new API
            with open(file_path, 'rb') as f:
                pdf_bytes = f.read()
            
            # Tạo Part với inline data
            pdf_part = genai.types.Part.from_bytes(
                data=pdf_bytes,
                mime_type="application/pdf"
            )
            contents.append(pdf_part)
            
        except Exception as e:
            return f"Lỗi đọc file {filename}: {e}", None

    if len(contents) <= 1:
        return "Không có file nào được xử lý", None

    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_PREVIEW_MODEL,
                contents=contents
            )
            
            json_string = response.text.strip()
            # Loại bỏ markdown code blocks
            if "```json" in json_string:
                json_string = json_string.split("```json")[1].split("```")[0]
            elif "```" in json_string:
                json_string = json_string.split("```")[1].split("```")[0]
            json_string = json_string.strip()
            
            print(f"[DEBUG] Google response: {json_string[:500]}...")
            
            analysis_data = json.loads(json_string)

            if not isinstance(analysis_data, list):
                return "Dữ liệu từ AI không phải là list JSON", None

            if len(analysis_data) == 0:
                return "AI trả về kết quả rỗng. Vui lòng thử lại.", None

            for item in analysis_data:
                required_keys = ["ten_file_goc", "ten_file_output", "trang_bat_dau", "trang_ket_thuc", "nam_van_ban"]
                if not all(key in item for key in required_keys):
                    return f"Dữ liệu thiếu trường bắt buộc: {item}", None

            return None, analysis_data

        except json.JSONDecodeError as e:
            return f"Lỗi parse JSON từ AI: {e}", None
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower() or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    time.sleep(45)
                    continue
                return "Quota API đã hết. Vui lòng đợi 1 phút hoặc tạo API key mới tại https://aistudio.google.com/app/apikey", None
            return f"Lỗi khi gọi AI: {e}", None
    
    return "Không thể kết nối API sau nhiều lần thử", None


def split_pdfs(pdf_file_paths, analysis_data, output_base_dir):
    """Tách file PDF theo dữ liệu phân tích"""
    tasks = defaultdict(list)
    for item in analysis_data:
        tasks[item["ten_file_goc"]].append(item)

    total_success = 0
    split_results = []

    for filename, rules in tasks.items():
        if filename not in pdf_file_paths:
            continue

        sub_folder = os.path.join(output_base_dir, os.path.splitext(filename)[0])
        os.makedirs(sub_folder, exist_ok=True)

        try:
            doc = fitz.open(pdf_file_paths[filename])
            page_count = doc.page_count

            for rule in rules:
                start_page = rule["trang_bat_dau"]
                end_page = rule["trang_ket_thuc"]

                if not (1 <= start_page <= end_page <= page_count):
                    split_results.append({
                        "file": rule["ten_file_output"],
                        "status": "error",
                        "message": f"Phạm vi trang không hợp lệ ({start_page}-{end_page})"
                    })
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
                split_results.append({
                    "file": output_filename,
                    "status": "success",
                    "pages": f"{start_page}-{end_page}"
                })

            doc.close()
        except Exception as e:
            split_results.append({
                "file": filename,
                "status": "error",
                "message": str(e)
            })

    return total_success, split_results


def create_zip(output_dir, zip_path):
    """Tạo file ZIP từ thư mục output"""
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(output_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, output_dir)
                zipf.write(file_path, arcname)


# ===============================
#  ROUTES
# ===============================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'google_ai': GOOGLE_AI_AVAILABLE})


@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        if 'files[]' not in request.files:
            return jsonify({'error': 'Không có file nào được chọn'}), 400

        api_key = request.form.get('api_key', '').strip()
        if not api_key:
            return jsonify({'error': 'Vui lòng nhập API Key'}), 400

    ai_provider = request.form.get('ai_provider', 'google').strip()

    files = request.files.getlist('files[]')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'Không có file nào được chọn'}), 400

    # Tạo session folder
    session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_upload = os.path.join(UPLOAD_FOLDER, session_id)
    session_output = os.path.join(OUTPUT_FOLDER, session_id)
    os.makedirs(session_upload, exist_ok=True)
    os.makedirs(session_output, exist_ok=True)

    pdf_file_paths = {}
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(session_upload, filename)
            file.save(file_path)
            pdf_file_paths[filename] = file_path

    if not pdf_file_paths:
        return jsonify({'error': 'Không có file PDF hợp lệ'}), 400

    # Phân tích với AI theo provider
    if ai_provider == 'deepseek':
        error, analysis_data = analyze_pdfs_with_deepseek(api_key, pdf_file_paths)
    else:
        if not GOOGLE_AI_AVAILABLE:
            return jsonify({'error': 'Google AI không khả dụng. Vui lòng cài: pip install google-generativeai'}), 400
        error, analysis_data = analyze_pdfs_with_google(api_key, pdf_file_paths)
    
    if error:
        shutil.rmtree(session_upload, ignore_errors=True)
        return jsonify({'error': error}), 400

    # Tách file
    total_success, split_results = split_pdfs(pdf_file_paths, analysis_data, session_output)

    # Lưu analysis data
    analysis_file = os.path.join(session_output, "analysis_data.json")
    with open(analysis_file, "w", encoding="utf-8") as f:
        json.dump(analysis_data, f, ensure_ascii=False, indent=4)

    # Tạo ZIP
    zip_filename = f"ket_qua_{session_id}.zip"
    zip_path = os.path.join(OUTPUT_FOLDER, zip_filename)
    create_zip(session_output, zip_path)

    # Cleanup upload folder
    shutil.rmtree(session_upload, ignore_errors=True)

    return jsonify({
        'success': True,
        'total_files': len(pdf_file_paths),
        'total_split': total_success,
        'analysis': analysis_data,
        'results': split_results,
        'download_id': session_id
    })
    
    except Exception as e:
        return jsonify({'error': f'Lỗi server: {str(e)}'}), 500


@app.route('/download/<session_id>')
def download_result(session_id):
    zip_filename = f"ket_qua_{session_id}.zip"
    zip_path = os.path.join(OUTPUT_FOLDER, zip_filename)

    if not os.path.exists(zip_path):
        return jsonify({'error': 'File không tồn tại'}), 404

    return send_file(zip_path, as_attachment=True, download_name=zip_filename)


# ===============================
#  MAIN
# ===============================
if __name__ == '__main__':
    # Tạo thư mục templates nếu chưa có
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    os.makedirs(templates_dir, exist_ok=True)

    port = int(os.environ.get('PORT', 8080))
    print(f"🚀 Server đang chạy tại http://127.0.0.1:{port}")
    app.run(debug=False, host='0.0.0.0', port=port)
