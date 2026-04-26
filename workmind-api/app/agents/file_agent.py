"""
WorkMind — File Agent
Indexes files and directories into the Knowledge Base.
Handles deduplication via MD5 content hash.
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.db.models import Document, DocumentChunk, DocumentStatus
from app.services.chunker import text_chunker
from app.services.embedder import embedder
from app.services.file_parser import file_parser

log = structlog.get_logger("workmind.file_agent")

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".dxf", ".eml", ".msg", ".txt", ".md", ".csv"}


def _md5_file(path: str) -> str:
    """Compute MD5 hex digest of file contents (blocking — run in thread pool)."""
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class FileAgent(BaseAgent):
    name = "file_agent"

    async def index_file(
        self,
        org_id: uuid.UUID,
        path: str,
        session: AsyncSession,
    ) -> int:
        """
        Index a single file into the Knowledge Base.

        Steps:
        1. Compute MD5 of the file.
        2. Check if a Document with the same source_path + content_hash already exists → skip.
        3. Create/update Document record with status=processing.
        4. Parse text, chunk, embed, store DocumentChunks.
        5. Update Document.status=indexed, total_chunks=n.

        Returns the number of chunks created (0 if skipped).
        """
        file_path = Path(path)
        filename = file_path.name

        # Step 1: compute hash
        try:
            content_hash = await asyncio.to_thread(_md5_file, path)
        except OSError as exc:
            log.error("file_agent_read_error", path=path, error=str(exc))
            raise

        # Step 2: check for duplicates
        stmt = select(Document).where(
            Document.org_id == org_id,
            Document.source_path == path,
            Document.content_hash == content_hash,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None and existing.status == DocumentStatus.indexed:
            log.info("file_agent_skip_duplicate", path=path, doc_id=str(existing.id))
            return 0

        # Step 3: upsert Document
        if existing is None:
            doc = Document(
                org_id=org_id,
                filename=filename,
                content_hash=content_hash,
                source_path=path,
                status=DocumentStatus.processing,
                total_chunks=0,
                metadata_json={"indexed_by": "file_agent"},
            )
            session.add(doc)
            await session.flush()  # get doc.id
        else:
            existing.status = DocumentStatus.processing
            existing.content_hash = content_hash
            doc = existing
            await session.flush()

        doc_id = doc.id

        # Delete stale chunks if re-indexing
        if existing is not None:
            stale_stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
            stale_res = await session.execute(stale_stmt)
            for stale_chunk in stale_res.scalars().all():
                await session.delete(stale_chunk)
            await session.flush()

        try:
            # Step 4: parse → chunk → embed
            text = await file_parser.parse(path)
            chunks = text_chunker.chunk(text)

            if not chunks:
                log.warning("file_agent_no_chunks", path=path, doc_id=str(doc_id))
                doc.status = DocumentStatus.failed
                doc.metadata_json = {**doc.metadata_json, "error": "no_chunks_produced"}
                await session.flush()
                return 0

            embeddings = await embedder.embed_batch(chunks)

            # Step 5: persist chunks
            for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
                chunk = DocumentChunk(
                    document_id=doc_id,
                    org_id=org_id,
                    chunk_index=i,
                    content=chunk_text,
                    embedding=embedding,
                    meta_json={"source_path": path, "chunk_index": i},
                )
                session.add(chunk)

            doc.status = DocumentStatus.indexed
            doc.total_chunks = len(chunks)
            await session.flush()

            log.info(
                "file_agent_indexed",
                path=path,
                doc_id=str(doc_id),
                chunks=len(chunks),
            )
            return len(chunks)

        except Exception as exc:
            log.error("file_agent_index_error", path=path, error=str(exc))
            doc.status = DocumentStatus.failed
            doc.metadata_json = {**doc.metadata_json, "error": str(exc)[:500]}
            await session.flush()
            raise

    async def scan_directory(
        self,
        org_id: uuid.UUID,
        dir_path: str,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """
        Recursively scan *dir_path* and index all supported files.
        Returns a summary dict with counts.
        """
        root = Path(dir_path)
        if not root.is_dir():
            raise ValueError(f"Not a directory: {dir_path}")

        total = 0
        skipped = 0
        failed = 0
        indexed = 0
        errors: list[str] = []

        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                skipped += 1
                continue
            total += 1
            try:
                chunks_created = await self.index_file(org_id, str(file_path), session)
                if chunks_created == 0:
                    skipped += 1
                else:
                    indexed += 1
                # Commit after each file to avoid holding a mega-transaction
                await session.commit()
            except Exception as exc:
                failed += 1
                errors.append(f"{file_path.name}: {str(exc)[:200]}")
                await session.rollback()
                log.error(
                    "scan_directory_file_failed",
                    file=str(file_path),
                    error=str(exc),
                )

        log.info(
            "scan_directory_complete",
            dir=dir_path,
            total=total,
            indexed=indexed,
            skipped=skipped,
            failed=failed,
        )
        return {
            "dir": dir_path,
            "total_files_found": total,
            "indexed": indexed,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
        }

    async def run(self, query: str, context: dict) -> dict:
        """FileAgent does not answer queries directly."""
        return {"error": "FileAgent does not handle chat queries. Use ContextAgent instead."}
