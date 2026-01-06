"""
Ingestion Service
=================

Service for handling document ingestion, registration, and file management.
"""

import asyncio
import hashlib
import io
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.events.dispatcher import EventDispatcher, StateChangeEvent
from src.core.models.document import Document
from src.core.state.machine import DocumentStatus
from src.core.storage.storage_client import MinIOClient
from src.shared.identifiers import generate_document_id

logger = logging.getLogger(__name__)


class IngestionService:
    """
    Handles document registration and initial processing steps.
    """

    def __init__(self, session: AsyncSession, storage_client: MinIOClient):
        self.session = session
        self.storage = storage_client

    async def register_document(
        self,
        tenant_id: str,
        filename: str,
        file_content: bytes,
        content_type: str = "application/octet-stream",
    ) -> Document:
        """
        Register a new document in the system.

        Performs deduplication based on content hash.
        If document exists, returns existing record.
        If new, uploads to storage and creates DB record.

        Args:
            tenant_id: Tenant identifier
            filename: Original filename
            file_content: Raw file bytes
            content_type: MIME type

        Returns:
            Document: The registered document
        """
        # 1. Calculate SHA-256 hash
        content_hash = hashlib.sha256(file_content).hexdigest()

        # 2. Check for existing document
        query = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.content_hash == content_hash,
            # We enforce uniqueness on hash per tenant.
            # If a user uploads the same content with a different filename,
            # we could support that as a new document or deduplicate.
            # Phase 1 requirement says "idempotency", implying we return the existing one.
            # But what if I WANT two copies? Usually in RAG, deduplication saves resources.
            # Let's check if we want to deduplicate by hash ONLY or hash + filename.
            # Implementation plan says: "Upload same file. Second upload should skip extraction."
            # So returning the existing doc is the way.
        )
        result = await self.session.execute(query)
        existing_doc = result.scalars().first()

        if existing_doc:
            logger.info(f"Document deduplicated: {filename} (ID: {existing_doc.id})")
            return existing_doc

        # 3. Upload to MinIO
        doc_id = generate_document_id()
        # Storage path: tenant_id/doc_id/filename
        storage_path = f"{tenant_id}/{doc_id}/{filename}"

        # We need a file-like object for upload_file
        file_io = io.BytesIO(file_content)

        try:
            # Run in threadpool if strictly blocking, but MinIO client is thread-safe.
            # We are in an async function, calling a sync method.
            # Ideally we should use run_in_executor, but for now direct call or specific async wrapper.
            # The MinIOClient wrapper is synchronous. We should acknowledge this block.
            # For high throughput we would offload this.
            await asyncio.to_thread(
                self.storage.upload_file,
                object_name=storage_path,
                data=file_io,
                length=len(file_content),
                content_type=content_type,
            )
        except Exception as e:
            logger.error(f"Failed to upload file to storage: {e}")
            raise

        # 4. Create DB Record
        new_doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            filename=filename,
            content_hash=content_hash,
            storage_path=storage_path,
            status=DocumentStatus.INGESTED,
        )

        self.session.add(new_doc)
        await self.session.commit()
        await self.session.refresh(new_doc)

        # 5. Emit Event
        EventDispatcher.emit_state_change(
            StateChangeEvent(
                document_id=doc_id,
                old_status=DocumentStatus.INGESTED, # Technically None -> Ingested
                new_status=DocumentStatus.INGESTED,
                tenant_id=tenant_id,
                details={"filename": filename}
            )
        )

        logger.info(f"Registered new document: {filename} (ID: {doc_id})")
        return new_doc

    async def process_document(self, document_id: str):
        """
        Process a registered document: Extract content and Chunk.
        """
        # 1. Fetch Document
        query = select(Document).where(Document.id == document_id)
        result = await self.session.execute(query)
        document = result.scalars().first()

        if not document:
            raise ValueError(f"Document {document_id} not found")

        from sqlalchemy import update

        # 2. Check State & Transition (INGESTED -> EXTRACTING)
        # Fix: Atomic update to prevent TOCTOU race conditions
        # We try to update the status only if it is currently INGESTED
        result = await self.session.execute(
            update(Document)
            .where(
                Document.id == document_id,
                Document.status == DocumentStatus.INGESTED
            )
            .values(status=DocumentStatus.EXTRACTING)
        )

        if result.rowcount == 0:
            # Update failed, meaning document was not in INGESTED state
            # It might be already processing, or failed, or deleted
            await self.session.refresh(document)
            logger.warning(
                f"Skipping processing for {document_id}: "
                f"Status is {document.status} (expected INGESTED)"
            )
            return

        # Commit directly to release lock/visible state
        await self.session.commit()

        # Refresh local object to match DB
        await self.session.refresh(document)

        try:
            # 3. Get File from Storage
            # 3. Get File from Storage
            # MinIO get_file returns bytes (handled inside wrapper)
            file_content = self.storage.get_file(document.storage_path)

            # 4. Extract Content (Fallback Chain)
            # Need to import FallbackManager inside method or top level
            # Determine mime type (stored? or guess?)
            # We didn't store mime type on Document model explicitly?
            # We stored `metadata_`. We should probably store it.
            # For now, filename extension based guessing or just generic.
            import mimetypes

            from src.core.extraction.fallback import FallbackManager
            mime_type, _ = mimetypes.guess_type(document.filename)
            if not mime_type:
                mime_type = "application/octet-stream"

            extraction_result = await FallbackManager.extract_with_fallback(
                file_content=file_content,
                mime_type=mime_type,
                filename=document.filename
            )

            # 5. Classify Domain (Stage 1.4)
            # Update Status -> CLASSIFYING
            document.status = DocumentStatus.CLASSIFYING
            await self.session.commit()
            EventDispatcher.emit_state_change(StateChangeEvent(
                document_id=document.id,
                old_status=DocumentStatus.EXTRACTING, # Approximate
                new_status=DocumentStatus.CLASSIFYING,
                tenant_id=document.tenant_id,
                details={"progress": 20}
            ))

            from src.core.intelligence.classifier import DomainClassifier
            from src.core.intelligence.strategies import get_strategy

            # Initialize classifier
            # Ideally this should be dependency injected or managed, but for now we instantiate.
            # Redis connection is handled inside (if configured).
            classifier = DomainClassifier()
            domain = await classifier.classify(extraction_result.content)
            await classifier.close()

            # 6. Select Strategy
            strategy = get_strategy(domain.value)
            logger.info(f"Classified document {document_id} as {domain.value}. Strategy: {strategy.name}")

            # Update Document with domain (and maybe strategy name if we added a column)
            document.domain = domain.value
            document.domain = domain.value
            document.metadata_ = {
                **(extraction_result.metadata or {}),
                "processing_method": "ocr" if extraction_result.extractor_used == "ocr" else "extraction",
                "conversion_pipeline": "amber_v2_standard",
                "file_extension": f".{document.filename.split('.')[-1]}" if '.' in document.filename else "",
                "content_primary_type": "pdf" if document.filename.lower().endswith(".pdf") else "text"
            }

            # 7. Chunk Content using SemanticChunker (Stage 1.5)
            # Update Status -> CHUNKING
            document.status = DocumentStatus.CHUNKING
            await self.session.commit()
            EventDispatcher.emit_state_change(StateChangeEvent(
                document_id=document.id,
                old_status=DocumentStatus.CLASSIFYING,
                new_status=DocumentStatus.CHUNKING,
                tenant_id=document.tenant_id,
                details={"progress": 40}
            ))

            from src.core.chunking.semantic import SemanticChunker
            from src.core.models.chunk import Chunk, EmbeddingStatus
            from src.shared.identifiers import generate_chunk_id

            chunker = SemanticChunker(strategy)
            chunk_data_list = chunker.chunk(extraction_result.content, document_title=document.filename)

            logger.info(f"Document {document_id} split into {len(chunk_data_list)} chunks")

            # Bulk insert chunks
            chunks_to_process = []
            for cd in chunk_data_list:
                chunk = Chunk(
                    id=generate_chunk_id(document.id, cd.index),
                    document_id=document.id,
                    index=cd.index,
                    content=cd.content,
                    tokens=cd.token_count,
                    metadata_={
                        "extractor": extraction_result.extractor_used,
                        "confidence": extraction_result.confidence,
                        "extraction_time": extraction_result.extraction_time_ms,
                        "domain": domain.value,
                        "start_char": cd.start_char,
                        "end_char": cd.end_char,
                        **cd.metadata,
                        **extraction_result.metadata
                    },
                    embedding_status=EmbeddingStatus.PENDING
                )
                self.session.add(chunk)
                chunks_to_process.append(chunk)

            # 8. Generate Embeddings and Store in Milvus
            # Update Status -> EMBEDDING
            document.status = DocumentStatus.EMBEDDING
            await self.session.commit()
            EventDispatcher.emit_state_change(StateChangeEvent(
                document_id=document.id,
                old_status=DocumentStatus.CHUNKING,
                new_status=DocumentStatus.EMBEDDING,
                tenant_id=document.tenant_id,
                details={"progress": 60, "chunk_count": len(chunks_to_process)}
            ))

            # This is the critical step for RAG retrieval!
            vector_store = None
            try:
                from src.api.config import settings
                from src.core.services.embeddings import EmbeddingService
                from src.core.services.sparse_embeddings import SparseEmbeddingService
                from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore

                logger.info(f"Generating embeddings for {len(chunks_to_process)} chunks")

                # Initialize services
                embedding_service = EmbeddingService(
                    openai_api_key=settings.openai_api_key or None,
                )
                sparse_service = SparseEmbeddingService()

                milvus_config = MilvusConfig(
                    host=settings.db.milvus_host,
                    port=settings.db.milvus_port,
                    collection_name=f"amber_{document.tenant_id}",  # Tenant-specific collection
                )
                vector_store = MilvusVectorStore(milvus_config)

                # Extract content for embedding
                chunk_contents = [c.content for c in chunks_to_process]

                # Generate embeddings in batch
                embeddings, embed_stats = await embedding_service.embed_texts(chunk_contents)

                # Generate sparse embeddings
                sparse_embeddings = []
                try:
                    # TODO: Batch sparse generation
                    for text in chunk_contents:
                        sparse_embeddings.append(sparse_service.embed_sparse(text))
                except Exception as e:
                    logger.warning(f"Failed to generate sparse embeddings: {e}")
                    # Fill with None/Empty
                    sparse_embeddings = [None] * len(chunks_to_process)

                # Prepare data for Milvus upsert
                milvus_data = []
                for chunk, emb, sparse_emb in zip(chunks_to_process, embeddings, sparse_embeddings, strict=False):
                    # Base data
                    data = {
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "tenant_id": document.tenant_id,
                        "content": chunk.content[:65530],
                        "embedding": emb,
                    }
                    if sparse_emb:
                        data["sparse_vector"] = sparse_emb

                    # Add metadata from chunk (handling potential None)
                    if chunk.metadata_:
                        data.update(chunk.metadata_)

                    milvus_data.append(data)

                # Upsert to Milvus
                await vector_store.upsert_chunks(milvus_data)

                # Update embedding status for all chunks
                for chunk in chunks_to_process:
                    chunk.embedding_status = EmbeddingStatus.COMPLETED

                logger.info(f"Stored {len(milvus_data)} embeddings in Milvus")

            except Exception as e:
                logger.error(f"Embedding generation/storage failed for document {document_id}: {e}")
                # Mark chunks as failed but don't fail the document entirely
                for chunk in chunks_to_process:
                    chunk.embedding_status = EmbeddingStatus.FAILED
            finally:
                if vector_store is not None:
                    try:
                        await vector_store.disconnect()
                    except Exception as disconnect_error:
                        logger.warning(f"Failed to disconnect Milvus: {disconnect_error}")

            # 9. Build Knowledge Graph (Phase 3)
            # Update Status -> GRAPH_SYNC
            document.status = DocumentStatus.GRAPH_SYNC
            await self.session.commit()
            EventDispatcher.emit_state_change(StateChangeEvent(
                document_id=document.id,
                old_status=DocumentStatus.EMBEDDING,
                new_status=DocumentStatus.GRAPH_SYNC,
                tenant_id=document.tenant_id,
                details={"progress": 80}
            ))

            # We process chunks to extract entities and build graph before marking document as READY.
            try:
                from src.core.graph.processor import graph_processor
                await graph_processor.process_chunks(chunks_to_process, document.tenant_id)
            except Exception as e:
                logger.error(f"Graph processing failed for document {document_id}: {e}")
                # We do NOT fail the document, as we still have chunks for RAG.
                # But we should note this failure.

            # 10. Document Enrichment (Summary, Keywords, Hashtags)
            # This step uses LLM to generate document-level metadata
            try:
                from src.core.intelligence.document_summarizer import get_document_summarizer

                logger.info(f"Generating document enrichment for {document_id}")
                summarizer = get_document_summarizer()

                # Extract first 10 chunks for summary generation
                chunk_contents = [c.content for c in chunks_to_process[:10]]
                enrichment = await summarizer.extract_summary(
                    chunks=chunk_contents,
                    document_title=document.filename
                )

                # Update document with enrichment data
                document.summary = enrichment.get("summary", "")
                document.document_type = enrichment.get("document_type", "other")
                document.hashtags = enrichment.get("hashtags", [])

                # Keywords directly from LLM enrichment
                document.keywords = enrichment.get("keywords", [])

                # Add domain as a keyword if not present
                if domain and domain.value and domain.value not in document.keywords:
                    document.keywords.append(domain.value)

                # Merge AI-generated values into metadata when PDF fields are empty
                if document.metadata_:
                    # Replace empty PDF metadata fields with AI-generated values
                    if not document.metadata_.get("keywords"):
                        document.metadata_["keywords"] = ", ".join(document.keywords) if document.keywords else ""

                logger.info(
                    f"Document enriched: type={document.document_type}, "
                    f"summary_len={len(document.summary)}, hashtags={len(document.hashtags)}"
                )
            except Exception as e:
                logger.error(f"Document enrichment failed for {document_id}: {e}")
                # Non-fatal - document is still usable without enrichment

            # 11. Update Document Status -> READY
            document.status = DocumentStatus.READY
            await self.session.commit()
            EventDispatcher.emit_state_change(StateChangeEvent(
                document_id=document.id,
                old_status=DocumentStatus.GRAPH_SYNC,
                new_status=DocumentStatus.READY,
                tenant_id=document.tenant_id,
                details={"progress": 100}
            ))

            logger.info(f"Processed document {document_id} using {extraction_result.extractor_used}")

        except Exception as e:
            logger.exception(f"Failed to process document {document_id}")
            document.status = DocumentStatus.FAILED
            document.error_message = f"{type(e).__name__}: {str(e)}"
            await self.session.commit()
            raise

