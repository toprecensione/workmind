"""
WorkMind — File Parser Service
Extracts plain text from various file formats for KB indexing.
Supported: PDF, DOCX, XLSX/XLS, DXF (AutoCAD), EML, MSG, TXT, MD, CSV.
"""
from __future__ import annotations

from pathlib import Path

import structlog

log = structlog.get_logger("workmind.file_parser")


class UnsupportedFileTypeError(ValueError):
    """Raised when a file extension is not supported by the parser."""


class FileParser:
    """
    Async-compatible file text extractor.
    All heavy IO is wrapped in asyncio.to_thread for non-blocking operation.
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".dxf", ".eml", ".msg", ".txt", ".md", ".csv"}

    async def parse(self, path: str) -> str:
        """
        Extract text content from the file at *path*.
        Returns a UTF-8 string. Binary parsing errors are replaced with '?'.
        Raises UnsupportedFileTypeError for unknown extensions.
        """
        import asyncio

        file_path = Path(path)
        ext = file_path.suffix.lower()

        if ext not in self.SUPPORTED_EXTENSIONS:
            raise UnsupportedFileTypeError(
                f"File type '{ext}' is not supported. "
                f"Supported: {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}"
            )

        # Run blocking IO in a thread pool
        return await asyncio.to_thread(self._parse_sync, path, ext)

    # ── Synchronous parsers (called from thread pool) ─────────────────────────

    def _parse_sync(self, path: str, ext: str) -> str:
        if ext == ".pdf":
            return self._parse_pdf(path)
        elif ext == ".docx":
            return self._parse_docx(path)
        elif ext in (".xlsx", ".xls"):
            return self._parse_excel(path)
        elif ext == ".dxf":
            return self._parse_dxf(path)
        elif ext == ".eml":
            return self._parse_eml(path)
        elif ext == ".msg":
            return self._parse_msg(path)
        else:  # .txt, .md, .csv
            return self._parse_text(path)

    def _parse_pdf(self, path: str) -> str:
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError("pdfplumber is required to parse PDF files: pip install pdfplumber") from exc

        pages: list[str] = []
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    pages.append(text)
        except Exception as exc:
            log.error("pdf_parse_error", path=path, error=str(exc))
            raise
        return "\n---\n".join(pages)

    def _parse_docx(self, path: str) -> str:
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("python-docx is required to parse DOCX files: pip install python-docx") from exc

        try:
            doc = Document(path)
            paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
            return "\n\n".join(paragraphs)
        except Exception as exc:
            log.error("docx_parse_error", path=path, error=str(exc))
            raise

    def _parse_excel(self, path: str) -> str:
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError("openpyxl is required to parse Excel files: pip install openpyxl") from exc

        parts: list[str] = []
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                parts.append(f"=== Sheet: {sheet_name} ===")
                for row in ws.iter_rows(values_only=True):
                    row_text = "\t".join(
                        str(cell) if cell is not None else "" for cell in row
                    )
                    if row_text.strip():
                        parts.append(row_text)
            wb.close()
        except Exception as exc:
            log.error("excel_parse_error", path=path, error=str(exc))
            raise
        return "\n".join(parts)

    def _parse_dxf(self, path: str) -> str:
        try:
            import ezdxf
        except ImportError as exc:
            raise RuntimeError("ezdxf is required to parse DXF files: pip install ezdxf") from exc

        parts: list[str] = []
        try:
            doc = ezdxf.readfile(path)

            # Metadata
            try:
                parts.append(f"DXF Version: {doc.dxfversion}")
            except Exception:
                pass

            # Layer names
            layers = [layer.dxf.name for layer in doc.layers]
            if layers:
                parts.append("Layers: " + ", ".join(layers))

            # Text entities from all layouts
            for layout in doc.layouts:
                for entity in layout:
                    try:
                        dxftype = entity.dxftype()
                        if dxftype in ("TEXT", "MTEXT"):
                            text_val = ""
                            if dxftype == "TEXT":
                                text_val = entity.dxf.get("text", "")
                            else:
                                text_val = entity.text  # MTEXT has a .text property
                            if text_val and text_val.strip():
                                parts.append(text_val.strip())
                    except Exception:
                        continue
        except Exception as exc:
            log.error("dxf_parse_error", path=path, error=str(exc))
            raise
        return "\n".join(parts)

    def _parse_eml(self, path: str) -> str:
        """Parse RFC-2822 .eml files using Python stdlib email module."""
        import email
        from email import policy as email_policy

        try:
            with open(path, "rb") as fh:
                msg = email.message_from_binary_file(fh, policy=email_policy.default)
        except Exception as exc:
            log.error("eml_parse_error", path=path, error=str(exc))
            raise

        parts: list[str] = []

        # Headers
        for header in ("From", "To", "Cc", "Subject", "Date"):
            val = msg.get(header, "")
            if val:
                parts.append(f"{header}: {val}")
        parts.append("")

        # Body — prefer plain text, fall back to html stripped
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                disp = str(part.get_content_disposition() or "")
                if "attachment" in disp:
                    parts.append(f"[allegato: {part.get_filename() or 'file'}]")
                    continue
                if ct == "text/plain":
                    try:
                        parts.append(part.get_content())
                    except Exception:
                        pass
                elif ct == "text/html":
                    try:
                        html = part.get_content()
                        # Strip tags with stdlib only
                        import html as html_mod
                        import re
                        text = re.sub(r"<[^>]+>", " ", html)
                        text = html_mod.unescape(text)
                        text = re.sub(r"\s+", " ", text).strip()
                        if text:
                            parts.append(text)
                    except Exception:
                        pass
        else:
            try:
                parts.append(msg.get_content())
            except Exception:
                parts.append(msg.get_payload(decode=True).decode("utf-8", errors="replace"))

        return "\n".join(parts)

    def _parse_msg(self, path: str) -> str:
        """Parse Outlook .msg files using extract-msg library."""
        try:
            import extract_msg
        except ImportError as exc:
            raise RuntimeError(
                "extract-msg is required to parse MSG files: pip install extract-msg"
            ) from exc

        try:
            with extract_msg.openMsg(path) as msg:
                parts: list[str] = []

                if msg.sender:
                    parts.append(f"From: {msg.sender}")
                if msg.to:
                    parts.append(f"To: {msg.to}")
                if msg.cc:
                    parts.append(f"Cc: {msg.cc}")
                if msg.subject:
                    parts.append(f"Subject: {msg.subject}")
                if msg.date:
                    parts.append(f"Date: {msg.date}")
                parts.append("")

                body = msg.body or ""
                if body.strip():
                    parts.append(body)
                elif msg.htmlBody:
                    import html as html_mod
                    import re
                    text = re.sub(r"<[^>]+>", " ", msg.htmlBody.decode("utf-8", errors="replace"))
                    text = html_mod.unescape(text)
                    text = re.sub(r"\s+", " ", text).strip()
                    parts.append(text)

                # List attachments
                for att in msg.attachments:
                    fname = getattr(att, "longFilename", None) or getattr(att, "shortFilename", "file")
                    parts.append(f"[allegato: {fname}]")

                return "\n".join(parts)
        except Exception as exc:
            log.error("msg_parse_error", path=path, error=str(exc))
            raise

    def _parse_text(self, path: str) -> str:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except Exception as exc:
            log.error("text_parse_error", path=path, error=str(exc))
            raise


# Module-level singleton
file_parser = FileParser()
