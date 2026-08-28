"""Resume text extraction — Phase 8 (docs/product-plan.md). Turns an
uploaded PDF/DOCX/TXT file into plain text, which then goes through the
exact same candidate_analysis flow a pasted-text "add candidate" already
uses. Extraction only, no field parsing here — that's still
candidate_analysis.py's job via the model, entirely unchanged by this."""

import io

from docx import Document
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt")


def extract_text(filename: str, content: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if lower.endswith(".docx"):
        doc = Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    if lower.endswith(".txt"):
        return content.decode("utf-8", errors="replace")
    raise ValueError(
        f"unsupported file type: '{filename}' — upload a {', '.join(SUPPORTED_EXTENSIONS)} file"
    )
