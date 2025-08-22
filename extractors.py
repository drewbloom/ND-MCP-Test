import io, zipfile
from typing import Tuple
from settings import settings

def _is_pdf(data: bytes) -> bool:
    return data.startswith(b"%PDF")

def _is_docx(data: bytes) -> bool:
    # DOCX is a zip; this quick check tries to open as zip and look for document.xml
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return any(n.endswith("word/document.xml") for n in z.namelist())
    except Exception:
        return False

def _try_decode_text(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    # fallback replace
    return data.decode("utf-8", errors="replace")

def _extract_pdf_text(data: bytes) -> str:
    """
    Extract text from a PDF using PyPDF.
    Assumes text layer exists (as ND OCR writes it back).
    Returns empty string if no text layer is present.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        # Some PDFs require non-strict parsing; retry with strict disabled if needed
        reader = PdfReader(io.BytesIO(data), strict=False)

    # Handle encrypted PDFs (occasionally appear if ND didn't flatten permissions)
    if getattr(reader, "is_encrypted", False):
        try:
            # Attempt empty-password decrypt (common for owner-password-only)
            reader.decrypt("")
        except Exception:
            # If still encrypted, give up gracefully
            return ""

    chunks = []
    for page in getattr(reader, "pages", []) or []:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        chunks.append(text)

    return "\n".join(chunks).strip()

def extract_text_from_bytes(filename: str, data: bytes) -> Tuple[str, str]:
    """Return (text, mimetype_guess) from document bytes."""
    name = (filename or "").lower()

    # Plain-text quick path
    if any(name.endswith(ext) for ext in (".txt", ".md", ".csv", ".json", ".log")):
        return _try_decode_text(data), "text/plain"

    # PDF → PyPDF
    if name.endswith(".pdf") or _is_pdf(data):
        pdf_text = _extract_pdf_text(data)
        return pdf_text, "application/pdf"

    # DOCX
    if settings.ENABLE_DOCX and (name.endswith(".docx") or _is_docx(data)):
        try:
            import docx  # python-docx
            doc = docx.Document(io.BytesIO(data))
            paragraphs = [p.text for p in doc.paragraphs]
            return "\n".join(paragraphs), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except Exception:
            return "", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # Unknown → best-effort text
    return _try_decode_text(data), "application/octet-stream"
