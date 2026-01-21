"""
PDF Splitter - Web App
Simple version for deployment
"""

import os
import sys
import json
import datetime
import zipfile
import tempfile
import shutil
from collections import defaultdict
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

# ===============================
#  IMPORTS
# ===============================
try:
    import fitz
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False
    print("Warning: PyMuPDF not available")

try:
    from google import genai
    GOOGLE_AI_AVAILABLE = True
except ImportError:
    GOOGLE_AI_AVAILABLE = False
    print("Warning: google-genai not available")

# ===============================
#  APP CONFIG
# ===============================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'pdf-splitter-2024')
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25MB

UPLOAD_FOLDER = tempfile.gettempdir()
ALLOWED_EXTENSIONS = {'pdf'}
GEMINI_MODEL = "gemini-2.5-flash"

AI_PROMPT = """
Phân tích file PDF này chứa nhiều văn bản tố tụng hình sự.

Xác định CHÍNH XÁC:
- Ranh giới từng văn bản (trang bắt đầu, trang kết thúc)
- Loại văn bản (Quyết định, Lệnh, Cáo trạng, Bản án...)
- Số hiệu và năm văn bản

Tên file: {filename}

Trả về JSON array:
[
  {{"ten_file_goc": "{filename}", "ten_file_output": "Loai_So.pdf", "trang_bat_dau": 1, "trang_ket_thuc": 2, "nam_van_ban": 2024}}
]

CHỈ TRẢ VỀ JSON, KHÔNG GIẢI THÍCH.
"""

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def analyze_pdf(api_key, filename, file_path):
    """Analyze PDF with Google Gemini"""
    if not GOOGLE_AI_AVAILABLE:
        return "Google AI chưa được cài đặt", None
    
    try:
        client = genai.Client(api_key=api_key)
        
        with open(file_path, 'rb') as f:
            pdf_bytes = f.read()
        
        pdf_part = genai.types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        prompt = AI_PROMPT.format(filename=filename)
        
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, pdf_part]
        )
        
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        
        data = json.loads(text.strip())
        
        if not isinstance(data, list) or len(data) == 0:
            return "AI không tìm thấy văn bản nào", None
            
        return None, data
        
    except json.JSONDecodeError as e:
        return f"Lỗi phân tích JSON: {e}", None
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "quota" in error_msg.lower():
            return "Quota API đã hết. Đợi 1 phút hoặc tạo key mới.", None
        return f"Lỗi: {error_msg}", None


def split_pdf(file_path, analysis_data, output_dir):
    """Split PDF based on analysis"""
    if not FITZ_AVAILABLE:
        return 0, ["PyMuPDF chưa được cài đặt"]
    
    results = []
    success = 0
    
    try:
        doc = fitz.open(file_path)
        page_count = doc.page_count
        
        for item in analysis_data:
            start = item.get("trang_bat_dau", 0)
            end = item.get("trang_ket_thuc", 0)
            
            if not (1 <= start <= end <= page_count):
                results.append(f"❌ Trang không hợp lệ: {start}-{end}")
                continue
            
            name = item.get("ten_file_output", "output.pdf").replace(".pdf", "")
            year = item.get("nam_van_ban", "")
            output_name = f"{name}_{year}.pdf" if year else f"{name}.pdf"
            output_name = "".join(c for c in output_name if c.isalnum() or c in "._- ")
            
            output_path = os.path.join(output_dir, output_name)
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=start-1, to_page=end-1)
            new_doc.save(output_path)
            new_doc.close()
            
            success += 1
            results.append(f"✅ {output_name} (Trang {start}-{end})")
        
        doc.close()
    except Exception as e:
        results.append(f"❌ Lỗi: {e}")
    
    return success, results


# ===============================
#  ROUTES
# ===============================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'fitz': FITZ_AVAILABLE,
        'google_ai': GOOGLE_AI_AVAILABLE
    })


@app.route('/upload', methods=['POST'])
def upload():
    try:
        if 'files[]' not in request.files:
            return jsonify({'error': 'Không có file'}), 400
        
        api_key = request.form.get('api_key', '').strip()
        if not api_key:
            return jsonify({'error': 'Cần API Key'}), 400
        
        file = request.files.getlist('files[]')[0]
        if not file or not allowed_file(file.filename):
            return jsonify({'error': 'File không hợp lệ'}), 400
        
        # Create temp directories
        session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        upload_dir = os.path.join(UPLOAD_FOLDER, f"upload_{session_id}")
        output_dir = os.path.join(UPLOAD_FOLDER, f"output_{session_id}")
        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        
        # Save file
        filename = secure_filename(file.filename)
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        
        # Analyze with AI
        error, analysis = analyze_pdf(api_key, filename, file_path)
        if error:
            shutil.rmtree(upload_dir, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)
            return jsonify({'error': error}), 400
        
        # Split PDF
        success, results = split_pdf(file_path, analysis, output_dir)
        
        # Save analysis
        with open(os.path.join(output_dir, "analysis.json"), "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        
        # Create ZIP
        zip_path = os.path.join(UPLOAD_FOLDER, f"result_{session_id}.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for root, dirs, files in os.walk(output_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    zf.write(fpath, fname)
        
        # Cleanup
        shutil.rmtree(upload_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        
        return jsonify({
            'success': True,
            'total_files': 1,
            'total_split': success,
            'analysis': analysis,
            'results': results,
            'download_id': session_id
        })
        
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.route('/download/<session_id>')
def download(session_id):
    zip_path = os.path.join(UPLOAD_FOLDER, f"result_{session_id}.zip")
    if not os.path.exists(zip_path):
        return jsonify({'error': 'File không tồn tại'}), 404
    return send_file(zip_path, as_attachment=True, download_name=f"ket_qua_{session_id}.zip")


# ===============================
#  MAIN
# ===============================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
