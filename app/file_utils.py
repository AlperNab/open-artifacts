from __future__ import annotations
from pathlib import Path
from pypdf import PdfReader
from docx import Document
import pandas as pd

UPLOAD_DIR = Path('./data/uploads')
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_TEXT_CHARS = 180_000

def safe_name(name: str) -> str:
    keep = ''.join(c if c.isalnum() or c in '._- ' else '_' for c in name).strip()
    return keep[:150] or 'uploaded_file'

def extract_text(path: Path, mime_type: str | None = None) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in {'.txt','.md','.py','.js','.ts','.tsx','.jsx','.json','.csv','.html','.css','.xml','.yml','.yaml','.log','.sql'}:
            return path.read_text(encoding='utf-8', errors='ignore')[:MAX_TEXT_CHARS]
        if suffix == '.pdf':
            reader = PdfReader(str(path))
            pages = []
            for i, page in enumerate(reader.pages[:80]):
                pages.append(f'--- Page {i+1} ---\n{page.extract_text() or ""}')
            return '\n\n'.join(pages)[:MAX_TEXT_CHARS]
        if suffix == '.docx':
            doc = Document(str(path))
            return '\n'.join(p.text for p in doc.paragraphs)[:MAX_TEXT_CHARS]
        if suffix in {'.xlsx','.xls'}:
            sheets = pd.read_excel(path, sheet_name=None, nrows=200)
            parts = []
            for sheet, df in sheets.items():
                parts.append(f'--- Sheet: {sheet} ---\n' + df.to_csv(index=False))
            return '\n'.join(parts)[:MAX_TEXT_CHARS]
    except Exception as e:
        return f'[Text extraction failed for {path.name}: {type(e).__name__}: {e}]'
    return f'[Uploaded binary file: {path.name}. No text extractor available for {suffix or mime_type}.]'
