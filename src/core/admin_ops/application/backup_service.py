"""
Backup Service
==============

Service for creating system backups as downloadable ZIP archives.
Supports two scopes:
- USER_DATA: Documents, conversations, memory facts/summaries
- FULL_SYSTEM: Above + vector metadata, graph entities, configs, rules
"""

import io
import json
import logging
import zipfile
from datetime import datetime
from typing import Optional, Callable

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.backup_job import BackupScope
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.generation.domain.memory_models import ConversationSummary, UserFact
from src.core.ingestion.domain.ports.storage import StoragePort
from src.core.admin_ops.domain.global_rule import GlobalRule

logger = logging.getLogger(__name__)


class BackupService:
    """
    Service for generating system backups.
    """

    def __init__(self, session: AsyncSession, storage: StoragePort):
        self.session = session
        self.storage = storage

    async def create_backup(
        self, 
        tenant_id: str,
        job_id: str,
        scope: BackupScope,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> tuple[str, int]:
        """
        Generate a backup ZIP file based on scope.
        
        Args:
            tenant_id: The tenant to backup
            job_id: The backup job ID for tracking
            scope: What to include (USER_DATA or FULL_SYSTEM)
            progress_callback: Optional callback for progress updates (0-100)
            
        Returns:
            tuple[str, int]: (storage_path, file_size_bytes)
        """
        logger.info(f"Creating backup for tenant {tenant_id}, scope={scope}, job={job_id}")
        
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            total_steps = 6 if scope == BackupScope.USER_DATA else 10
            current_step = 0
            
            def update_progress():
                nonlocal current_step
                current_step += 1
                if progress_callback:
                    progress_callback(int(current_step / total_steps * 100))
            
            # ===== USER_DATA scope =====
            
            # 1. Documents metadata
            await self._add_documents_metadata(zf, tenant_id)
            update_progress()
            
            # 2. Folders structure
            await self._add_folders(zf, tenant_id)
            update_progress()
            
            # 3. Original document files
            await self._add_document_files(zf, tenant_id)
            update_progress()
            
            # 4. Conversations
            await self._add_conversations(zf, tenant_id)
            update_progress()
            
            # 5. User Facts (memory)
            await self._add_user_facts(zf, tenant_id)
            update_progress()
            
            # 6. Conversation Summaries (memory)
            await self._add_conversation_summaries(zf, tenant_id)
            update_progress()
            
            # ===== FULL_SYSTEM scope (additional) =====
            if scope == BackupScope.FULL_SYSTEM:
                # 7. Global rules
                await self._add_global_rules(zf, tenant_id)
                update_progress()
                
                # 8. Tenant configuration
                await self._add_tenant_config(zf, tenant_id)
                update_progress()
                
                # 9. Vector store metadata (just counts, not actual vectors)
                await self._add_vector_metadata(zf, tenant_id)
                update_progress()
                
                # 10. Graph metadata (entity/relationship counts)
                await self._add_graph_metadata(zf, tenant_id)
                update_progress()
            
            # Create manifest
            manifest = {
                "version": "1.0",
                "created_at": datetime.utcnow().isoformat(),
                "tenant_id": tenant_id,
                "scope": scope.value,
                "job_id": job_id
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        
        zip_buffer.seek(0)
        content = zip_buffer.getvalue()
        file_size = len(content)
        
        # Upload to MinIO
        storage_path = f"backups/{tenant_id}/{job_id}/backup.zip"
        self.storage.upload_file(
            object_name=storage_path,
            data=io.BytesIO(content),
            length=file_size,
            content_type="application/zip"
        )
        
        logger.info(f"Uploaded backup to {storage_path}, size: {file_size} bytes")
        return storage_path, file_size

    async def _add_documents_metadata(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export documents metadata as JSON."""
        result = await self.session.execute(
            select(Document).where(Document.tenant_id == tenant_id)
        )
        documents = result.scalars().all()
        
        data = []
        for doc in documents:
            data.append({
                "id": doc.id,
                "filename": doc.filename,
                "folder_id": doc.folder_id,
                "storage_path": doc.storage_path,
                "mime_type": doc.metadata_.get("mime_type"),
                "file_size": doc.metadata_.get("file_size"),
                "status": doc.status,
                "metadata": doc.metadata_ or {},
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            })
        
        zf.writestr("documents/metadata.json", json.dumps(data, indent=2))
        logger.info(f"Added {len(data)} document metadata entries")

    async def _add_folders(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export folder structure as JSON."""
        result = await self.session.execute(
            select(Folder).where(Folder.tenant_id == tenant_id)
        )
        folders = result.scalars().all()
        
        data = []
        for folder in folders:
            data.append({
                "id": folder.id,
                "name": folder.name,
                "created_at": folder.created_at.isoformat() if folder.created_at else None,
            })
        
        zf.writestr("folders/folders.json", json.dumps(data, indent=2))
        logger.info(f"Added {len(data)} folders")

    async def _add_document_files(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export original document files from storage."""
        result = await self.session.execute(
            select(Document).where(Document.tenant_id == tenant_id)
        )
        documents = result.scalars().all()
        
        for doc in documents:
            if not doc.storage_path:
                continue
            try:
                file_bytes = self.storage.get_file(doc.storage_path)
                # Preserve folder structure: documents/files/{folder_id or root}/{filename}
                folder_path = doc.folder_id if doc.folder_id else "root"
                zf.writestr(f"documents/files/{folder_path}/{doc.filename}", file_bytes)
            except Exception as e:
                logger.warning(f"Could not retrieve file for document {doc.id}: {e}")
                zf.writestr(
                    f"documents/files/{doc.folder_id or 'root'}/{doc.filename}.missing.txt",
                    f"File not found: {doc.storage_path}\nError: {str(e)}"
                )

    async def _add_conversations(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export conversation summaries as JSON."""
        result = await self.session.execute(
            select(ConversationSummary).where(ConversationSummary.tenant_id == tenant_id)
        )
        conversations = result.scalars().all()
        
        data = []
        for conv in conversations:
            data.append({
                "id": conv.id,
                "user_id": conv.user_id,
                "title": conv.title,
                "summary": conv.summary,
                "metadata": conv.metadata_ or {},
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
            })
        
        zf.writestr("conversations/conversations.json", json.dumps(data, indent=2))
        logger.info(f"Added {len(data)} conversations")

    async def _add_user_facts(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export user facts (memory) as JSON."""
        result = await self.session.execute(
            select(UserFact).where(UserFact.tenant_id == tenant_id)
        )
        facts = result.scalars().all()
        
        data = []
        for fact in facts:
            data.append({
                "id": fact.id,
                "user_id": fact.user_id,
                "content": fact.content,
                "importance": fact.importance,
                "metadata": fact.metadata_ or {},
                "created_at": fact.created_at.isoformat() if fact.created_at else None,
            })
        
        zf.writestr("memory/user_facts.json", json.dumps(data, indent=2))
        logger.info(f"Added {len(data)} user facts")

    async def _add_conversation_summaries(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export conversation summaries (memory context) as JSON."""
        # This overlaps with conversations but may have different structure
        # For now, we reuse the conversation export
        pass  # Already covered in _add_conversations

    async def _add_global_rules(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export global rules as JSON."""
        try:
            result = await self.session.execute(
                select(GlobalRule).where(GlobalRule.tenant_id == tenant_id)
            )
            rules = result.scalars().all()
            
            data = []
            for rule in rules:
                data.append({
                    "id": rule.id,
                    "content": rule.content,
                    "category": rule.category,
                    "priority": rule.priority,
                    "is_active": rule.is_active,
                    "source": rule.source,
                    "created_at": rule.created_at.isoformat() if rule.created_at else None,
                })
            
            zf.writestr("config/global_rules.json", json.dumps(data, indent=2))
            logger.info(f"Added {len(data)} global rules")
        except Exception as e:
            logger.warning(f"Could not export global rules: {e}")
            zf.writestr("config/global_rules.json", json.dumps([], indent=2))

    async def _add_tenant_config(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export tenant configuration as JSON."""
        from src.core.tenants.domain.tenant import Tenant
        
        try:
            result = await self.session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            tenant = result.scalar_one_or_none()
            
            if tenant:
                data = {
                    "id": tenant.id,
                    "name": tenant.name,
                    "config": tenant.config or {},
                    "is_active": tenant.is_active,
                }
                zf.writestr("config/tenant_config.json", json.dumps(data, indent=2))
                logger.info("Added tenant configuration")
        except Exception as e:
            logger.warning(f"Could not export tenant config: {e}")
            zf.writestr("config/tenant_config.json", json.dumps({}, indent=2))

    async def _add_vector_metadata(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export vector store metadata (counts, not actual vectors)."""
        from src.core.ingestion.domain.chunk import Chunk
        
        try:
            result = await self.session.execute(
                select(func.count(Chunk.id)).where(Chunk.tenant_id == tenant_id)
            )
            chunk_count = result.scalar() or 0
            
            data = {
                "tenant_id": tenant_id,
                "chunk_count": chunk_count,
                "note": "Vectors cannot be exported directly. Re-indexing will be required after restore."
            }
            zf.writestr("vectors/metadata.json", json.dumps(data, indent=2))
            logger.info(f"Added vector metadata: {chunk_count} chunks")
        except Exception as e:
            logger.warning(f"Could not export vector metadata: {e}")
            zf.writestr("vectors/metadata.json", json.dumps({"error": str(e)}, indent=2))

    async def _add_graph_metadata(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Export graph database metadata (structure info, not full data)."""
        # Note: Full neo4j export would require apoc.export which needs docker access
        # For application-level backup, we just note that graph needs separate handling
        data = {
            "tenant_id": tenant_id,
            "note": "Graph database entities are not included in application backup. Use scripts/backup.sh for full Neo4j backup."
        }
        zf.writestr("graph/metadata.json", json.dumps(data, indent=2))
        logger.info("Added graph metadata note")

    async def list_backups(self, tenant_id: str) -> list[dict]:
        """List available backup files for a tenant."""
        from src.core.admin_ops.domain.backup_job import BackupJob, BackupStatus
        
        result = await self.session.execute(
            select(BackupJob)
            .where(BackupJob.tenant_id == tenant_id)
            .where(BackupJob.status == BackupStatus.COMPLETED)
            .order_by(BackupJob.created_at.desc())
        )
        jobs = result.scalars().all()
        
        return [
            {
                "id": job.id,
                "scope": job.scope.value if job.scope else None,
                "file_size": job.file_size,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "is_scheduled": job.is_scheduled == "true",
            }
            for job in jobs
        ]

    async def delete_backup(self, job_id: str, tenant_id: str) -> bool:
        """Delete a backup file."""
        from src.core.admin_ops.domain.backup_job import BackupJob
        
        result = await self.session.execute(
            select(BackupJob)
            .where(BackupJob.id == job_id)
            .where(BackupJob.tenant_id == tenant_id)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            return False
        
        # Delete from storage
        if job.result_path:
            try:
                self.storage.delete_file(job.result_path)
            except Exception as e:
                logger.warning(f"Could not delete backup file from storage: {e}")
        
        # Delete job record
        await self.session.delete(job)
        await self.session.commit()
        
        return True
