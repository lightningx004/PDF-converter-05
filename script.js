document.addEventListener('DOMContentLoaded', async () => {
    const codeInput = document.getElementById('code-input');
    const convertBtn = document.getElementById('convert-btn');
    const resetBtn = document.getElementById('reset-btn');
    const filenameInput = document.getElementById('filename-input');
    const fontSizeInput = document.getElementById('fontsize-input');
    const lineNumbers = document.getElementById('line-numbers');
    const statLines = document.getElementById('stat-lines');
    const statChars = document.getElementById('stat-chars');
    const statWords = document.getElementById('stat-words');

    // Modal Elements
    const errorModal = document.getElementById('error-modal');
    const errorMessagePre = document.getElementById('error-message');
    const errorSuggestion = document.getElementById('error-suggestion');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const dismissBtn = document.getElementById('dismiss-btn');

    let pyodide = null;
    let pyodideReady = false;

    // Initial Stats
    updateStats();

    // Load Pyodide
    async function initPyodide() {
        showToast('Initializing Pyodide...', 'info');
        try {
            if (typeof loadPyodide === 'undefined') {
                throw new Error('Pyodide script not loaded. Check your internet connection.');
            }

            pyodide = await loadPyodide();

            showToast('Loading Micropip...', 'info');
            await pyodide.loadPackage("micropip");
            const micropip = pyodide.pyimport("micropip");

            showToast('Installing fpdf2 library...', 'info');
            await micropip.install("fpdf2");
            await micropip.install("reportlab");
            await micropip.install("requests");

            showToast('Configuring environment...', 'info');
            // Define clean_code function in Python environment
            await pyodide.runPythonAsync(`
import re

def clean_code(code, font_size=None):
    # Remove markdown code fences
    code = re.sub(r'\`\`\`python|\`\`\`', '', code)
    
    # Remove citation markers
    code = re.sub(r'\\[cite_start\\]', '', code)
    code = re.sub(r'\\[cite: \\d+\\]', '', code)
    code = re.sub(r'\\[cite_end\\]', '', code)
    
    # Inject Font Size if provided
    if font_size:
        # FPDF: set_font_size(12) -> set_font_size(16)
        code = re.sub(r'(\\.set_font_size\\s*\\()\\s*\\d+', f'\\\\g<1>{font_size}', code)
        
        # FPDF: set_font(..., size=12) -> set_font(..., size=16) (Keyword arg)
        code = re.sub(r'(\\.set_font\\s*\\([^)]*?size\\s*=\\s*)\\d+', f'\\\\g<1>{font_size}', code)
        
        # FPDF: set_font("Arial", 12) (Positional)
        code = re.sub(r'(\\.set_font\\s*\\((?:[^()=]+,)\\s*)\\d+(\\s*\\))', f'\\\\g<1>{font_size}\\\\g<2>', code)
        
        # ReportLab: setFont("Name", 12) -> setFont("Name", 16)
        code = re.sub(r'(\\.setFont\\s*\\([^,]+,\\s*)\\d+', f'\\\\g<1>{font_size}', code)
    
    return code.strip()
            `);

            pyodideReady = true;
            showToast('Python ready!', 'success');
        } catch (err) {
            console.error(err);
            showToast('Failed to load Python environment', 'error');
        }
    }

    initPyodide();

    // Editor Interactions
    codeInput.addEventListener('input', () => {
        updateStats();
        updateLineNumbers();
    });

    codeInput.addEventListener('scroll', () => {
        lineNumbers.scrollTop = codeInput.scrollTop;
    });

    codeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
            e.preventDefault();
            const start = codeInput.selectionStart;
            const end = codeInput.selectionEnd;
            codeInput.value = codeInput.value.substring(0, start) + '    ' + codeInput.value.substring(end);
            codeInput.selectionStart = codeInput.selectionEnd = start + 4;
            updateStats();
        }
    });

    // Reset Button
    resetBtn.addEventListener('click', () => {
        codeInput.value = '';
        updateStats();
        updateLineNumbers();
        showToast('Editor cleared', 'info');
    });

    // Convert Button
    convertBtn.addEventListener('click', async () => {
        if (!pyodideReady) {
            showToast('Python is still loading...', 'info');
            return;
        }

        const code = codeInput.value;
        const fontSize = fontSizeInput.value;
        if (!code.trim()) {
            showToast('Please enter some Python code', 'error');
            return;
        }

        startLoading();

        try {
            // cleanup previous pdfs
            await pyodide.runPythonAsync(`
import os
import glob
for f in glob.glob("*.pdf"):
    try:
        os.remove(f)
    except:
        pass
            `);

            // Set variables for Python
            pyodide.globals.set("user_code", code);
            pyodide.globals.set("font_size", fontSize);

            // Execute Conversion
            await pyodide.runPythonAsync(`
import glob
import sys
from fpdf import FPDF
import fpdf

# --- MONKEY PATCH START ---
# Save original method
if not hasattr(FPDF, '_original_multi_cell'):
    FPDF._original_multi_cell = FPDF.multi_cell

def patched_multi_cell(self, *args, **kwargs):
    try:
        # Handle width (first arg or 'w' in kwargs)
        w = kwargs.get('w')
        if w is None and len(args) > 0:
            w = args[0]
        
        # Logic for w=0 fix
        if w == 0:
            available_width = self.w - self.r_margin - self.x
            if available_width < 5:
                self.ln()
                available_width = self.w - self.r_margin - self.x
            
            # Inject collected available_width back
            if kwargs.get('w') is not None:
                kwargs['w'] = available_width
            elif len(args) > 0:
                args = (available_width,) + args[1:]
    except:
        pass
    
    try:
        return self._original_multi_cell(*args, **kwargs)
    except Exception as e:
        # Check if it looks like an encoding/font error (UnicodeEncodeError or FPDFUnicodeEncodingException)
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
                    # Normalize
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
        # Fallback for characters not supported by the font (e.g. Emoji)
        return text.encode('latin-1', 'replace').decode('latin-1')

FPDF.normalize_text = patched_normalize_text
# --- UNICODE PATCH END ---

# --- MONKEY PATCH END ---

cleaned = clean_code(user_code, font_size)

# Attempt to execute valid Python code
exec(cleaned, globals())

# Check if a PDF was actually generated
import glob
pdfs = glob.glob("*.pdf")
if not pdfs:
    raise Exception("No PDF generated. Ensure your code saves a PDF (e.g. pdf.output('name.pdf'))")
            `);

            // Check for PDF
            const pdfFiles = await pyodide.runPythonAsync(`
import glob
glob.glob("*.pdf")
            `);

            const filesList = pdfFiles.toJs();

            if (filesList.length === 0) {
                // This usually catches the case where no error was raised but no file was made
                throw new Error("No PDF file generated. Ensure your code saves a PDF (e.g. pdf.output('name.pdf'))");
            }

            const pdfFilename = filesList[0];

            // Read file bytes
            const pdfBytes = pyodide.FS.readFile(pdfFilename);

            // Create Blob and Download
            const blob = new Blob([pdfBytes], { type: 'application/pdf' });
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = filenameInput.value ? (filenameInput.value.endsWith('.pdf') ? filenameInput.value : filenameInput.value + '.pdf') : pdfFilename;
            document.body.appendChild(a);
            a.click();
            a.remove();

            showToast('PDF Generated Successfully!', 'success');

        } catch (error) {
            console.error('Error:', error);
            showErrorModal(error);
        } finally {
            stopLoading();
        }
    });

    // Modal Functions
    function showErrorModal(error) {
        let msg = error.message || String(error);

        // Clean up Pyodide error message prefix if present
        if (msg.includes("PythonClientError") || msg.includes("PythonError")) {
            // Keep the traceback which is usually helpful
            msg = msg.replace(/^PythonError: /, '');
        }

        errorMessagePre.textContent = msg;

        // Simple heuristics for suggestions
        if (msg.includes("SyntaxError")) {
            errorSuggestion.textContent = "Check for missing parentheses, matching quotes, or correct colons at the end of statements.";
        } else if (msg.includes("IndentationError")) {
            errorSuggestion.textContent = "Check your code indentation. Python relies on consistent spacing (tabs vs spaces).";
        } else if (msg.includes("NameError")) {
            errorSuggestion.textContent = "You are trying to use a variable or function that hasn't been defined or imported yet.";
        } else if (msg.includes("ImportError") || msg.includes("ModuleNotFoundError")) {
            errorSuggestion.textContent = "The library you are trying to import might not be available in this environment.";
        } else if (msg.includes("No PDF generated")) {
            errorSuggestion.textContent = "Your code ran without errors but didn't save a PDF. Make sure you call `pdf.output('filename.pdf')` at the end.";
        } else {
            errorSuggestion.textContent = "Review the error details above to identify the issue.";
        }

        errorModal.classList.remove('hidden');
    }

    function closeErrorModal() {
        errorModal.classList.add('hidden');
    }

    // Modal Event Listeners
    closeModalBtn.addEventListener('click', closeErrorModal);
    dismissBtn.addEventListener('click', closeErrorModal);
    errorModal.addEventListener('click', (e) => {
        if (e.target === errorModal) closeErrorModal();
    });

    // Helper Functions
    function updateStats() {
        const text = codeInput.value;
        const lines = text ? text.split('\n').length : 0;
        const chars = text.length;
        const words = text.trim() ? text.trim().split(/\s+/).length : 0;

        statLines.textContent = lines;
        statChars.textContent = chars;
        statWords.textContent = words;
    }

    function updateLineNumbers() {
        const lines = codeInput.value.split('\n').length;
        lineNumbers.innerHTML = Array(lines).fill(1).map((_, i) => `<div>${i + 1}</div>`).join('');
    }

    function startLoading() {
        convertBtn.classList.add('loading');
        convertBtn.disabled = true;
    }

    function stopLoading() {
        convertBtn.classList.remove('loading');
        convertBtn.disabled = false;
    }

    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        let icon = 'fa-info-circle';
        if (type === 'success') icon = 'fa-check-circle';
        if (type === 'error') icon = 'fa-exclamation-circle';

        toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;

        const container = document.getElementById('toast-container');
        container.appendChild(toast);

        // Remove after animation
        setTimeout(() => {
            toast.style.animation = 'fadeOut 0.3s forwards';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
});
