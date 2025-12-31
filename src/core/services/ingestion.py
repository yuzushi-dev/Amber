"""
Ingestion Service
=================

Service for handling document ingestion, registration, and file management.
"""

import hashlib
import io
import logging
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.events.dispatcher import EventDispatcher, StateChangeEvent
from src.core.models.document import Document
from src.core.state.machine import DocumentStatus
from src.core.storage.minio_client import MinIOClient
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
            self.storage.upload_file(
                object_name=storage_path,
                data=file_io,
                length=len(file_content),
                content_type=content_type
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
            
        # 2. Check State & Transition (INGESTED -> EXTRACTING)
        # In a real app we might use transition manager explicitly or implicit here
        if document.status != DocumentStatus.INGESTED:
            # Maybe it's already processed or failed?
            pass

        # Update status to EXTRACTING
        document.status = DocumentStatus.EXTRACTING
        await self.session.commit()
        
        try:
            # 3. Get File from Storage
            # 3. Get File from Storage
            # MinIO get_file returns bytes (handled inside wrapper)
            file_content = self.storage.get_file(document.storage_path)
                
            # 4. Extract Content (Fallback Chain)
            # Need to import FallbackManager inside method or top level
            from src.core.extraction.fallback import FallbackManager
            
            # Determine mime type (stored? or guess?)
            # We didn't store mime type on Document model explicitly? 
            # We stored `metadata_`. We should probably store it.
            # For now, filename extension based guessing or just generic.
            import mimetypes
            mime_type, _ = mimetypes.guess_type(document.filename)
            if not mime_type:
                mime_type = "application/octet-stream"
                
            extraction_result = await FallbackManager.extract_with_fallback(
                file_content=file_content,
                mime_type=mime_type,
                filename=document.filename
            )
            
            # 5. Classify Domain (Stage 1.4)
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
            
            # 7. Chunk Content using SemanticChunker (Stage 1.5)
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
            
            # 9. Build Knowledge Graph (Phase 3)
            # We process chunks to extract entities and build graph before marking document as READY.
            try:
                from src.core.graph.processor import graph_processor
                await graph_processor.process_chunks(chunks_to_process, document.tenant_id)
            except Exception as e:
                logger.error(f"Graph processing failed for document {document_id}: {e}")
                # We do NOT fail the document, as we still have chunks for RAG.
                # But we should note this failure.
            
            # 8. Update Document Status -> READY
            document.status = DocumentStatus.READY 
            await self.session.commit()
            
            logger.info(f"Processed document {document_id} using {extraction_result.extractor_used}")
            
        except Exception as e:
            logger.error(f"Failed to process document {document_id}: {e}")
            document.status = DocumentStatus.FAILED
            # document.error_message = str(e) # If we had that field
            await self.session.commit()
            raise
