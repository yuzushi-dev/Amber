"""
Restore Service
===============

Service for restoring system data from backup ZIP archives.
Supports two modes:
- MERGE: Preserve existing data, add new items (skip duplicates)
- REPLACE: Wipe existing data, restore from backup
"""

import io
import json
import logging
import zipfile
from datetime import datetime
from typing import Optional, Callable
from uuid import uuid4

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.backup_job import RestoreMode, BackupScope
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.generation.domain.memory_models import ConversationSummary, UserFact
from src.core.ingestion.domain.ports.storage import StoragePort

logger = logging.getLogger(__name__)


class BackupManifest:
    """Parsed backup manifest."""
    def __init__(self, data: dict):
        self.version = data.get("version", "1.0")
        self.created_at = data.get("created_at")
        self.tenant_id = data.get("tenant_id")
        self.scope = data.get("scope")
        self.job_id = data.get("job_id")
        self.is_valid = bool(self.version and self.tenant_id)


class RestoreResult:
    """Result of a restore operation."""
    def __init__(self):
        self.folders_restored = 0
        self.documents_restored = 0
        self.conversations_restored = 0
        self.facts_restored = 0
        self.errors: list[str] = []
    
    @property
    def total_items(self) -> int:
        return (
            self.folders_restored + 
            self.documents_restored + 
            self.conversations_restored + 
            self.facts_restored
        )


class RestoreService:
    """
    Service for restoring from backup archives.
    """

    def __init__(self, session: AsyncSession, storage: StoragePort):
        self.session = session
        self.storage = storage

    async def validate_backup(self, backup_path: str) -> BackupManifest:
        """
        Validate a backup ZIP file and return its manifest.
        
        Args:
            backup_path: Path to the backup file in storage
            
        Returns:
            BackupManifest with backup info
            
        Raises:
            ValueError: If backup is invalid
        """
        try:
            file_bytes = self.storage.get_file(backup_path)
            zip_buffer = io.BytesIO(file_bytes)
            
            with zipfile.ZipFile(zip_buffer, "r") as zf:
                # Check for manifest
                if "manifest.json" not in zf.namelist():
                    raise ValueError("Invalid backup: manifest.json not found")
                
                manifest_data = json.loads(zf.read("manifest.json"))
                manifest = BackupManifest(manifest_data)
                
                if not manifest.is_valid:
                    raise ValueError("Invalid backup: manifest is incomplete")
                
                return manifest
                
        except zipfile.BadZipFile:
            raise ValueError("Invalid backup: not a valid ZIP file")
        except FileNotFoundError:
            raise ValueError("Backup file not found")

    async def restore(
        self,
        backup_path: str,
        target_tenant_id: str,
        mode: RestoreMode,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> RestoreResult:
        """
        Restore from a backup file.
        
        Args:
            backup_path: Path to the backup file in storage
            target_tenant_id: Tenant to restore into
            mode: MERGE or REPLACE
            progress_callback: Optional callback for progress updates (0-100)
            
        Returns:
            RestoreResult with counts of restored items
        """
        logger.info(f"Restoring backup from {backup_path} to tenant {target_tenant_id}, mode={mode}")
        
        result = RestoreResult()
        
        try:
            file_bytes = self.storage.get_file(backup_path)
            zip_buffer = io.BytesIO(file_bytes)
            
            with zipfile.ZipFile(zip_buffer, "r") as zf:
                total_steps = 5
                current_step = 0
                
                def update_progress():
                    nonlocal current_step
                    current_step += 1
                    if progress_callback:
                        progress_callback(int(current_step / total_steps * 100))
                
                # If REPLACE mode, clear existing data first
                if mode == RestoreMode.REPLACE:
                    await self._clear_tenant_data(target_tenant_id)
                    logger.info(f"Cleared existing data for tenant {target_tenant_id}")
                
                # 1. Restore folders
                folders_count = await self._restore_folders(zf, target_tenant_id, mode)
                result.folders_restored = folders_count
                update_progress()
                
                # 2. Restore documents metadata
                docs_count = await self._restore_documents(zf, target_tenant_id, mode)
                result.documents_restored = docs_count
                update_progress()
                
                # 3. Restore document files
                await self._restore_document_files(zf, target_tenant_id)
                update_progress()
                
                # 4. Restore conversations
                convs_count = await self._restore_conversations(zf, target_tenant_id, mode)
                result.conversations_restored = convs_count
                update_progress()
                
                # 5. Restore user facts
                facts_count = await self._restore_user_facts(zf, target_tenant_id, mode)
                result.facts_restored = facts_count
                update_progress()
                
                await self.session.commit()
                
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            result.errors.append(str(e))
            await self.session.rollback()
        
        logger.info(f"Restore complete: {result.total_items} items restored")
        return result

    async def _clear_tenant_data(self, tenant_id: str) -> None:
        """Clear all tenant data for REPLACE mode."""
        # Delete in order to respect foreign keys
        await self.session.execute(
            delete(UserFact).where(UserFact.tenant_id == tenant_id)
        )
        await self.session.execute(
            delete(ConversationSummary).where(ConversationSummary.tenant_id == tenant_id)
        )
        await self.session.execute(
            delete(Document).where(Document.tenant_id == tenant_id)
        )
        await self.session.execute(
            delete(Folder).where(Folder.tenant_id == tenant_id)
        )
        await self.session.flush()

    async def _restore_folders(
        self, 
        zf: zipfile.ZipFile, 
        tenant_id: str,
        mode: RestoreMode
    ) -> int:
        """Restore folders from backup."""
        count = 0
        
        try:
            if "folders/folders.json" not in zf.namelist():
                return 0
            
            data = json.loads(zf.read("folders/folders.json"))
            
            for folder_data in data:
                folder_id = folder_data.get("id")
                
                # In MERGE mode, skip if exists
                if mode == RestoreMode.MERGE:
                    existing = await self.session.execute(
                        select(Folder).where(Folder.id == folder_id)
                    )
                    if existing.scalar_one_or_none():
                        continue
                
                folder = Folder(
                    id=folder_id,
                    tenant_id=tenant_id,
                    name=folder_data.get("name"),
                )
                self.session.add(folder)
                count += 1
            
            await self.session.flush()
            
        except Exception as e:
            logger.warning(f"Error restoring folders: {e}")
        
        return count

    async def _restore_documents(
        self, 
        zf: zipfile.ZipFile, 
        tenant_id: str,
        mode: RestoreMode
    ) -> int:
        """Restore document metadata from backup."""
        count = 0
        
        try:
            if "documents/metadata.json" not in zf.namelist():
                return 0
            
            data = json.loads(zf.read("documents/metadata.json"))
            
            for doc_data in data:
                doc_id = doc_data.get("id")
                
                # In MERGE mode, skip if exists
                if mode == RestoreMode.MERGE:
                    existing = await self.session.execute(
                        select(Document).where(Document.id == doc_id)
                    )
                    if existing.scalar_one_or_none():
                        continue
                
                # Prepare metadata with file info
                metadata = doc_data.get("metadata", {})
                metadata["mime_type"] = doc_data.get("mime_type")
                metadata["file_size"] = doc_data.get("file_size")
                
                doc = Document(
                    id=doc_id,
                    tenant_id=tenant_id,
                    filename=doc_data.get("filename"),
                    folder_id=doc_data.get("folder_id"),
                    storage_path=doc_data.get("storage_path"),
                    status=doc_data.get("status", "pending"),
                    metadata_=metadata,
                )
                self.session.add(doc)
                count += 1
            
            await self.session.flush()
            
        except Exception as e:
            logger.warning(f"Error restoring documents: {e}")
        
        return count

    async def _restore_document_files(
        self, 
        zf: zipfile.ZipFile, 
        tenant_id: str
    ) -> None:
        """Restore document files to storage."""
        try:
            # Find all files in documents/files/
            file_entries = [
                name for name in zf.namelist() 
                if name.startswith("documents/files/") and not name.endswith("/")
            ]
            
            for file_path in file_entries:
                try:
                    # Extract folder_id and filename from path
                    parts = file_path.replace("documents/files/", "").split("/", 1)
                    if len(parts) != 2:
                        continue
                    
                    folder_id, filename = parts
                    if folder_id == "root":
                        folder_id = None
                    
                    # Find the document
                    result = await self.session.execute(
                        select(Document)
                        .where(Document.tenant_id == tenant_id)
                        .where(Document.filename == filename)
                        .where(Document.folder_id == folder_id)
                    )
                    doc = result.scalar_one_or_none()
                    
                    if doc and doc.storage_path:
                        # Upload file to storage
                        file_bytes = zf.read(file_path)
                        self.storage.upload_file(
                            object_name=doc.storage_path,
                            data=io.BytesIO(file_bytes),
                            length=len(file_bytes),
                            content_type=doc.metadata_.get("mime_type") or "application/octet-stream"
                        )
                        
                except Exception as e:
                    logger.warning(f"Error restoring file {file_path}: {e}")
                    
        except Exception as e:
            logger.warning(f"Error restoring document files: {e}")

    async def _restore_conversations(
        self, 
        zf: zipfile.ZipFile, 
        tenant_id: str,
        mode: RestoreMode
    ) -> int:
        """Restore conversations from backup."""
        count = 0
        
        try:
            if "conversations/conversations.json" not in zf.namelist():
                return 0
            
            data = json.loads(zf.read("conversations/conversations.json"))
            
            for conv_data in data:
                conv_id = conv_data.get("id")
                
                # In MERGE mode, skip if exists
                if mode == RestoreMode.MERGE:
                    existing = await self.session.execute(
                        select(ConversationSummary).where(ConversationSummary.id == conv_id)
                    )
                    if existing.scalar_one_or_none():
                        continue
                
                conv = ConversationSummary(
                    id=conv_id,
                    tenant_id=tenant_id,
                    user_id=conv_data.get("user_id"),
                    title=conv_data.get("title"),
                    summary=conv_data.get("summary"),
                    metadata_=conv_data.get("metadata", {}),
                )
                self.session.add(conv)
                count += 1
            
            await self.session.flush()
            
        except Exception as e:
            logger.warning(f"Error restoring conversations: {e}")
        
        return count

    async def _restore_user_facts(
        self, 
        zf: zipfile.ZipFile, 
        tenant_id: str,
        mode: RestoreMode
    ) -> int:
        """Restore user facts from backup."""
        count = 0
        
        try:
            if "memory/user_facts.json" not in zf.namelist():
                return 0
            
            data = json.loads(zf.read("memory/user_facts.json"))
            
            for fact_data in data:
                fact_id = fact_data.get("id")
                
                # In MERGE mode, skip if exists
                if mode == RestoreMode.MERGE:
                    existing = await self.session.execute(
                        select(UserFact).where(UserFact.id == fact_id)
                    )
                    if existing.scalar_one_or_none():
                        continue
                
                fact = UserFact(
                    id=fact_id,
                    tenant_id=tenant_id,
                    user_id=fact_data.get("user_id"),
                    content=fact_data.get("content"),
                    importance=fact_data.get("importance", 0.5),
                    metadata_=fact_data.get("metadata", {}),
                )
                self.session.add(fact)
                count += 1
            
            await self.session.flush()
            
        except Exception as e:
            logger.warning(f"Error restoring user facts: {e}")
        
        return count
