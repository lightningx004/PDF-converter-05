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
# --- END MONKEY PATCH ---
"""

            auto_runner_code = """
# --- AUTO-RUNNER LOGIC START ---
import glob
import inspect
import sys
import os

pdf_files = glob.glob("*.pdf")
if not pdf_files:
    # Check if we printed anything (stdout is captured by runner, but we can check if sys.stdout has been written to?)
    # Actually, we can just try to run functions if no PDF exists.
    # Printing side-effects are fine.
    
    current_globals = dict(globals())
    candidates = []
    
    for name, obj in current_globals.items():
        if callable(obj) and name not in ['clean_code', 'patched_multi_cell', 'patched_normalize_text', 'FPDF', 'fpdf', 'glob', 'inspect', 'sys', 'os', 're', 'subprocess', 'tempfile']:
             # Check if it was defined in the script (__main__)
             if getattr(obj, '__module__', None) in (None, '__main__'):
                 candidates.append(name)
    
    for name in candidates:
        try:
            func = current_globals[name]
            sig = inspect.signature(func)
            params = len(sig.parameters)
            
            if params == 0:
                print(f"Auto-running {name}()...")
                func()
            elif params == 1:
                print(f"Auto-running {name}('output.pdf')...")
                func("output.pdf")
            
            if glob.glob("*.pdf"):
                break
        except:
            pass
# --- AUTO-RUNNER LOGIC END ---
"""
            
            # Write key parts in order:
            # 1. Monkey Patch (setup FPDF)
            # 2. User Code (defines functions, maybe runs them)
            # 3. Auto-Runner (if user code didn't produce PDF)
            
            full_script = patch_code + "\n" + code + "\n" + auto_runner_code
            f.write(full_script)
            
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
            
            # Find the generated PDF file
            pdf_files = glob.glob(os.path.join(temp_dir, '*.pdf'))
            
            if not pdf_files:
                # No PDF file found. Check stdout.
                stdout_content = result.stdout
                if stdout_content and stdout_content.strip():
                     # Generate PDF from stdout
                     try:
                        from fpdf import FPDF # FPDF is already imported in the patch_code, but this is fine.
                        pdf = FPDF()
                        pdf.add_page()
                        pdf.set_font("Courier", size=12)
                        pdf.multi_cell(0, 5, txt=stdout_content)
                        stdout_pdf_path = os.path.join(temp_dir, "output_from_stdout.pdf")
                        pdf.output(stdout_pdf_path)
                        pdf_files = [stdout_pdf_path]
                     except Exception as e:
                        # If PDF generation from stdout fails, raise an error
                        return jsonify({'error': f"Script executed, but no PDF was generated and failed to create PDF from stdout: {e}"}), 400
                else:
                    # HEURISTIC: Auto-Run if no output
                    # This is tricky because globals() content isn't easily accessible from subprocess result
                    # Unless we modify the script wrapper to do the auto-run logic INSIDE the script execution.
                    
                    # We can't do it easily here because `result` is just strings.
                    # Retrying: We need to inject the auto-run logic INTO the patch_code!
                    pass

                    if result.returncode != 0:
                        return jsonify({'error': f"Execution failed:\n{result.stderr}"}), 400
                    return jsonify({'error': 'No PDF file was generated. Ensure your code saves a PDF or prints output.'}), 400
            
            # If we reach here, pdf_files should contain at least one PDF path
            pdf_path = pdf_files[0]
            
            # Read the PDF into memory before the temporary directory is cleaned up
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
