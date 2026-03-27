from __future__ import annotations

from io import BytesIO


def extract_text_from_upload(filename: str, data: bytes) -> str:
    """Best-effort text extraction for TXT / PDF / DOCX.

    Returns extracted text (may be empty). Raises ValueError for unsupported types.
    """

    name = (filename or "").lower().strip()

    if name.endswith('.txt') or name.endswith('.md'):
        return data.decode('utf-8', errors='replace')

    if name.endswith('.pdf'):
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n\n".join([p.strip() for p in parts if p and p.strip()]).strip()

    if name.endswith('.docx'):
        import docx  # python-docx

        doc = docx.Document(BytesIO(data))
        parts = [p.text for p in doc.paragraphs if (p.text or "").strip()]
        return "\n".join(parts).strip()

    raise ValueError('unsupported file type (supported: .txt, .md, .pdf, .docx)')
