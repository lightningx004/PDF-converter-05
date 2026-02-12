import os
import subprocess
import tempfile
import glob
from flask import Flask, request, send_file, jsonify, render_template

import re

app = Flask(__name__)

def clean_code(code, font_size=None):
    # Remove markdown code fences
    code = re.sub(r'```python|```', '', code)
    
    # Remove citation markers like [cite_start], [cite: 1], etc.
    code = re.sub(r'\[cite_start\]', '', code)
    code = re.sub(r'\[cite: \d+\]', '', code)
    code = re.sub(r'\[cite_end\]', '', code)
    
    # Inject Font Size if provided
    if font_size:
        # FPDF: set_font_size(12) -> set_font_size(16)
        # Use \g<1> to prevent \1 + digits from being interpreted as octal or wrong group
        code = re.sub(r'(\.set_font_size\s*\()\s*\d+', f'\\g<1>{font_size}', code)
        
        # FPDF: set_font(..., size=12) -> set_font(..., size=16) (Keyword arg)
        code = re.sub(r'(\.set_font\s*\([^)]*?size\s*=\s*)\d+', f'\\g<1>{font_size}', code)
        
        # FPDF: set_font("Arial", 12) or set_font("Arial", "B", 12) (Positional)
        # Safer approach for positional: Look for patterns ending in a number inside set_font
        # Matches: .set_font("Arial", 12)
        code = re.sub(r'(\.set_font\s*\((?:[^()=]+,)\s*)\d+(\s*\))', f'\\g<1>{font_size}\\g<2>', code)
        
        # ReportLab: setFont("Name", 12) -> setFont("Name", 16)
        code = re.sub(r'(\.setFont\s*\([^,]+,\s*)\d+', f'\\g<1>{font_size}', code)
    
    return code.strip()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/convert', methods=['POST'])
def convert():
    data = request.json
    raw_code = data.get('code')
    font_size = data.get('font_size')
    
    if not raw_code:
        return jsonify({'error': 'No code provided'}), 400

    code = clean_code(raw_code, font_size)
    
    # Create a temporary directory for execution
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, 'script.py')
        
        # Write the user code to a file
        with open(script_path, 'w', encoding='utf-8') as f:
            # Inject Monkey Patch
            patch_code = """
import fpdf
from fpdf import FPDF
# --- MONKEY PATCH START ---
if not hasattr(FPDF, '_original_multi_cell'):
    FPDF._original_multi_cell = FPDF.multi_cell

def patched_multi_cell(self, *args, **kwargs):
    try:
        w = kwargs.get('w')
        if w is None and len(args) > 0:
            w = args[0]
        
        if w == 0:
            available_width = self.w - self.r_margin - self.x
            if available_width < 5:
                self.ln()
                available_width = self.w - self.r_margin - self.x
            
            if kwargs.get('w') is not None:
                kwargs['w'] = available_width
            elif len(args) > 0:
                args = (available_width,) + args[1:]
    except:
        pass
    
    try:
        return self._original_multi_cell(*args, **kwargs)
    except Exception as e:
        err_msg = str(e).lower()
        if "outside the range" in err_msg or "codec can't encode" in err_msg or "character map" in err_msg:
             try:
                text = kwargs.get('text') or kwargs.get('txt')
                text_arg_index = -1
                
                if text is None:
                    if len(args) >= 3:
                        text = args[2]
                        text_arg_index = 2
                
                if text:
                    normalized = text.encode('latin-1', 'replace').decode('latin-1')
                    if kwargs.get('text') is not None:
                        kwargs['text'] = normalized
                    elif kwargs.get('txt') is not None:
                        kwargs['txt'] = normalized
                    elif text_arg_index != -1:
                        args_list = list(args)
                        args_list[text_arg_index] = normalized
                        args = tuple(args_list)
                    return self._original_multi_cell(*args, **kwargs)
             except:
                pass
        raise e

FPDF.multi_cell = patched_multi_cell

# --- UNICODE PATCH START ---
if not hasattr(FPDF, '_original_normalize_text'):
    FPDF._original_normalize_text = FPDF.normalize_text

def patched_normalize_text(self, text):
    try:
        return self._original_normalize_text(text)
    except:
        return text.encode('latin-1', 'replace').decode('latin-1')

FPDF.normalize_text = patched_normalize_text
# --- UNICODE PATCH END ---

# --- MONKEY PATCH END ---
"""
            f.write(patch_code + "\n" + code)
            
        try:
            # Execute the script in the temporary directory
            # Capture output for debugging
            result = subprocess.run(
                ['python', 'script.py'], 
                cwd=temp_dir, 
                capture_output=True, 
                text=True, 
                timeout=30 # Prevent infinite loops
            )
            
            if result.returncode != 0:
                return jsonify({'error': f"Execution failed:\n{result.stderr}"}), 400
                
            # Find the generated PDF file
            pdf_files = glob.glob(os.path.join(temp_dir, '*.pdf'))
            
            if not pdf_files:
                return jsonify({'error': 'No PDF file was generated by the script. Ensure your code saves a PDF (e.g., output("file.pdf")).'}), 400
                
            # Return the first PDF found
            # We must read it into memory or stream it before the temp dir is cleaned up
             # However, send_file with a file path inside a closing verify might fail if not handled carefully
            # A safer way is to read the content and send it as bytes, or keep the temp file open?
            # Actually, flask's send_file can take a file object.
            
            pdf_path = pdf_files[0]
            # Use a BytesIO object to hold the file in memory
            from io import BytesIO
            with open(pdf_path, 'rb') as f:
                pdf_data = BytesIO(f.read())
            
            pdf_filename = os.path.basename(pdf_path)
            return send_file(
                pdf_data, 
                mimetype='application/pdf', 
                as_attachment=True, 
                download_name=pdf_filename
            )

        except subprocess.TimeoutExpired:
            return jsonify({'error': 'Execution timed out.'}), 408
        except Exception as e:
            return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
