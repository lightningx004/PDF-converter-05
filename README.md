# Python to PDF Converter (Static)

A web-based tool to convert AI-generated Python code into PDF files. This project is built with HTML, CSS, JavaScript, and [Pyodide](https://pyodide.org/), running entirely in your browser.

## Features
- **Client-Side Execution**: Python code runs directly in your browser using WebAssembly.
- **PDF Generation**: Uses `fpdf2` to create PDF documents.
- **Clean Interface**: Convert code snippets instantly.

## How to Deploy on GitHub Pages
1. Upload the following files to your GitHub repository:
   - `index.html`
   - `script.js`
   - `style.css`
   - `README.md`
2. Go to **Settings** -> **Pages**.
3. Select the `main` branch as Source.
4. Your site will be live!

## Local Development
Since this uses Pyodide (WebAssembly), you need a local server to run it:
```bash
python -m http.server
```
Then open [http://localhost:8000](http://localhost:8000).
