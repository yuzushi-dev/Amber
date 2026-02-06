"""
Export Service
==============

Service for exporting conversation data to downloadable ZIP archives.
"""

import io
import json
import logging
import zipfile
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.generation.domain.memory_models import ConversationSummary
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.ports.storage import StoragePort

logger = logging.getLogger(__name__)


class ExportService:
    """
    Service for generating conversation exports.
    """

    def __init__(self, session: AsyncSession, storage: StoragePort):
        self.session = session
        self.storage = storage

    async def generate_single_conversation_zip(self, conversation_id: str) -> bytes:
        """
        Generate a ZIP file containing a single conversation's export data.

        The ZIP contains:
        - transcript.txt: Human-readable conversation transcript
        - metadata.json: Structured data including chunks and document references
        - documents/: Folder containing referenced source documents

        Args:
            conversation_id: ID of the conversation to export

        Returns:
            bytes: The ZIP file content
        """
        logger.info(f"Generating export for conversation {conversation_id}")

        # Fetch conversation summary
        result = await self.session.execute(
            select(ConversationSummary).where(ConversationSummary.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")

        # Extract conversation data
        metadata = conversation.metadata_ or {}
        history = metadata.get("history", [])

        # Build transcript text
        transcript_lines = [
            "# Conversation Export",
            f"# ID: {conversation_id}",
            f"# Date: {conversation.created_at.isoformat()}",
            f"# Title: {conversation.title}",
            "",
            "=" * 60,
            "",
        ]

        # Collect all referenced document IDs from all turns
        referenced_doc_ids: set[str] = set()
        all_chunks_metadata: list[dict] = []

        if history:
            for idx, turn in enumerate(history, 1):
                # User message
                query = turn.get("query", "")
                if query:
                    transcript_lines.append(f"## User ({idx}):")
                    transcript_lines.append(query)
                    transcript_lines.append("")

                # Assistant message
                answer = turn.get("answer", "")
                if answer:
                    transcript_lines.append(f"## Assistant ({idx}):")
                    transcript_lines.append(answer)
                    transcript_lines.append("")

                # Collect sources/chunks
                sources = turn.get("sources", [])
                if sources:
                    transcript_lines.append(f"### Sources ({idx}):")
                    for src in sources:
                        doc_id = src.get("document_id", "unknown")
                        referenced_doc_ids.add(doc_id)
                        transcript_lines.append(
                            f"  - {src.get('filename', src.get('document_id', 'Unknown'))}"
                        )
                        all_chunks_metadata.append(
                            {
                                "turn": idx,
                                "document_id": doc_id,
                                "chunk_index": src.get("chunk_index", src.get("index")),
                                "content": src.get("content", ""),
                                "score": src.get("score"),
                            }
                        )
                    transcript_lines.append("")
        else:
            # Fallback: single-turn from metadata
            query_text = metadata.get("query", conversation.title)
            answer_text = metadata.get("answer", conversation.summary)

            if query_text:
                transcript_lines.append("## User:")
                transcript_lines.append(query_text)
                transcript_lines.append("")

            if answer_text:
                transcript_lines.append("## Assistant:")
                transcript_lines.append(answer_text)
                transcript_lines.append("")

        transcript_content = "\n".join(transcript_lines)

        # Build metadata JSON
        export_metadata = {
            "conversation_id": conversation_id,
            "tenant_id": conversation.tenant_id,
            "title": conversation.title,
            "created_at": conversation.created_at.isoformat(),
            "exported_at": datetime.now(UTC).isoformat(),
            "chunks": all_chunks_metadata,
            "referenced_documents": list(referenced_doc_ids),
        }

        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add transcript
            zf.writestr("transcript.txt", transcript_content)

            # Add metadata
            zf.writestr("metadata.json", json.dumps(export_metadata, indent=2))

            # Add referenced documents
            if referenced_doc_ids:
                await self._add_documents_to_zip(zf, list(referenced_doc_ids))

        zip_buffer.seek(0)
        return zip_buffer.getvalue()

    async def generate_all_conversations_zip(
        self, tenant_id: str, job_id: str, progress_callback: callable = None
    ) -> tuple[str, int]:
        """
        Generate a ZIP file containing all conversations for a tenant.

        Each conversation is in its own folder with:
        - transcript.txt
        - metadata.json
        - documents/

        Args:
            tenant_id: The tenant ID to export
            job_id: The export job ID for tracking
            progress_callback: Optional callback for progress updates

        Returns:
            tuple[str, int]: (storage_path, file_size_bytes)
        """
        logger.info(f"Generating bulk export for tenant {tenant_id}, job {job_id}")

        # Fetch all conversations for tenant
        result = await self.session.execute(
            select(ConversationSummary)
            .where(ConversationSummary.tenant_id == tenant_id)
            .order_by(ConversationSummary.created_at.desc())
        )
        conversations = result.scalars().all()

        total = len(conversations)
        logger.info(f"Found {total} conversations to export")

        if total == 0:
            # Create empty ZIP
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                zf.writestr("README.txt", "No conversations found for export.")
            zip_buffer.seek(0)
            content = zip_buffer.getvalue()
        else:
            # Create ZIP with all conversations
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, conv in enumerate(conversations):
                    try:
                        await self._add_conversation_to_zip(
                            zf, conv, f"conversation_{idx + 1}_{conv.id[:8]}"
                        )

                        if progress_callback:
                            progress = int((idx + 1) / total * 100)
                            progress_callback(progress)
                    except Exception as e:
                        logger.warning(f"Failed to export conversation {conv.id}: {e}")
                        # Add error note but continue
                        zf.writestr(
                            f"conversation_{idx + 1}_{conv.id[:8]}/ERROR.txt",
                            f"Failed to export: {str(e)}",
                        )

            zip_buffer.seek(0)
            content = zip_buffer.getvalue()

        file_size = len(content)

        # Upload to MinIO
        storage_path = f"exports/{tenant_id}/{job_id}/conversations_export.zip"
        self.storage.upload_file(
            object_name=storage_path,
            data=io.BytesIO(content),
            length=file_size,
            content_type="application/zip",
        )

        logger.info(f"Uploaded export to {storage_path}, size: {file_size} bytes")

        return storage_path, file_size

    async def _add_conversation_to_zip(
        self, zf: zipfile.ZipFile, conversation: ConversationSummary, folder_name: str
    ) -> None:
        """Add a single conversation's data to an open ZIP file."""
        metadata = conversation.metadata_ or {}
        history = metadata.get("history", [])

        # Build transcript
        transcript_lines = [
            f"# {conversation.title}",
            f"# Date: {conversation.created_at.isoformat()}",
            "",
        ]

        referenced_doc_ids: set[str] = set()
        all_chunks: list[dict] = []

        if history:
            for idx, turn in enumerate(history, 1):
                query = turn.get("query", "")
                answer = turn.get("answer", "")
                sources = turn.get("sources", [])

                if query:
                    transcript_lines.append(f"## User ({idx}):")
                    transcript_lines.append(query)
                    transcript_lines.append("")

                if answer:
                    transcript_lines.append(f"## Assistant ({idx}):")
                    transcript_lines.append(answer)
                    transcript_lines.append("")

                for src in sources:
                    doc_id = src.get("document_id", "")
                    if doc_id:
                        referenced_doc_ids.add(doc_id)
                    all_chunks.append(
                        {
                            "turn": idx,
                            "document_id": doc_id,
                            "content": src.get("content", ""),
                            "score": src.get("score"),
                        }
                    )
        else:
            # Fallback
            query_text = metadata.get("query", conversation.title)
            answer_text = metadata.get("answer", conversation.summary)
            if query_text:
                transcript_lines.extend(["## User:", query_text, ""])
            if answer_text:
                transcript_lines.extend(["## Assistant:", answer_text, ""])

        # Write files
        zf.writestr(f"{folder_name}/transcript.txt", "\n".join(transcript_lines))
        zf.writestr(
            f"{folder_name}/metadata.json",
            json.dumps(
                {
                    "conversation_id": conversation.id,
                    "title": conversation.title,
                    "created_at": conversation.created_at.isoformat(),
                    "chunks": all_chunks,
                    "referenced_documents": list(referenced_doc_ids),
                },
                indent=2,
            ),
        )

        # Add referenced documents
        if referenced_doc_ids:
            await self._add_documents_to_zip(
                zf, list(referenced_doc_ids), folder_prefix=f"{folder_name}/documents"
            )

    async def _add_documents_to_zip(
        self, zf: zipfile.ZipFile, document_ids: list[str], folder_prefix: str = "documents"
    ) -> None:
        """Fetch and add source documents to the ZIP."""
        for doc_id in document_ids:
            try:
                # Fetch document metadata
                result = await self.session.execute(select(Document).where(Document.id == doc_id))
                doc = result.scalar_one_or_none()

                if not doc:
                    logger.warning(f"Document {doc_id} not found, skipping")
                    continue

                # Fetch file content from MinIO
                try:
                    file_bytes = self.storage.get_file(doc.storage_path)
                    zf.writestr(f"{folder_prefix}/{doc.filename}", file_bytes)
                except FileNotFoundError:
                    logger.warning(
                        f"File not found in storage for document {doc_id}: {doc.storage_path}"
                    )
                    # Add placeholder
                    zf.writestr(
                        f"{folder_prefix}/{doc.filename}.missing.txt",
                        f"Original file not found in storage: {doc.storage_path}",
                    )
            except Exception as e:
                logger.warning(f"Failed to add document {doc_id} to ZIP: {e}")
