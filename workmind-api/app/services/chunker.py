"""
WorkMind — Text Chunker Service
Splits long text into overlapping chunks suitable for vector embedding.
Respects paragraph boundaries before falling back to character-level splitting.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger("workmind.chunker")

_MIN_CHUNK_CHARS = 50


class TextChunker:
    """
    Splits text into chunks with configurable size and overlap.

    Strategy:
      1. Split on blank lines (paragraph boundaries) to get natural segments.
      2. For each paragraph, if it fits within chunk_size, accumulate it.
      3. When the accumulator exceeds chunk_size, flush a chunk and start a new
         one with an overlap window taken from the end of the previous chunk.
      4. Discard any resulting chunk shorter than _MIN_CHUNK_CHARS.
    """

    def chunk(
        self,
        text: str,
        chunk_size: int = 800,
        overlap: int = 100,
    ) -> list[str]:
        """
        Split *text* into chunks of at most *chunk_size* characters with
        *overlap* characters of sliding-window overlap between consecutive chunks.

        Returns a list of non-empty strings, each at least _MIN_CHUNK_CHARS chars.
        """
        if not text or not text.strip():
            return []

        # Step 1: break on paragraph boundaries
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        chunks: list[str] = []
        current: list[str] = []
        current_len: int = 0

        def flush() -> None:
            """Join current buffer into a chunk and append if long enough."""
            raw = "\n\n".join(current).strip()
            if len(raw) >= _MIN_CHUNK_CHARS:
                chunks.append(raw)

        for para in paragraphs:
            para_len = len(para)

            # Paragraph itself is larger than chunk_size → split it by characters
            if para_len > chunk_size:
                # Flush whatever we have accumulated first
                if current:
                    flush()
                    current = []
                    current_len = 0

                # Character-level split with overlap
                start = 0
                while start < para_len:
                    end = start + chunk_size
                    piece = para[start:end].strip()
                    if len(piece) >= _MIN_CHUNK_CHARS:
                        chunks.append(piece)
                    start = end - overlap
                    if start < 0:
                        start = 0
                continue

            # Would the paragraph overflow current buffer?
            separator_len = 2 if current else 0  # "\n\n" separator
            if current_len + separator_len + para_len > chunk_size and current:
                flush()
                # Seed new buffer with overlap from end of the flushed chunk
                overlap_text = "\n\n".join(current)
                if len(overlap_text) > overlap:
                    overlap_text = overlap_text[-overlap:]
                current = [overlap_text] if overlap_text.strip() else []
                current_len = len(overlap_text)

            current.append(para)
            current_len += separator_len + para_len

        # Flush remaining buffer
        if current:
            flush()

        return chunks


# Module-level singleton
text_chunker = TextChunker()
