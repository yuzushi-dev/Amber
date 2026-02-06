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
import os
import subprocess
import zipfile
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_ops.domain.backup_job import BackupSchedule, BackupScope, RestoreMode
from src.core.admin_ops.domain.global_rule import GlobalRule
from src.core.generation.domain.memory_models import ConversationSummary, UserFact
from src.core.graph.domain.ports.graph_client import GraphClientPort
from src.core.ingestion.domain.chunk import Chunk, EmbeddingStatus
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.folder import Folder
from src.core.ingestion.domain.ports.storage import StoragePort
from src.core.ingestion.domain.ports.vector_store import VectorStoreFactory
from src.core.tenants.domain.tenant import Tenant

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
            self.folders_restored
            + self.documents_restored
            + self.conversations_restored
            + self.facts_restored
        )


class RestoreService:
    """
    Service for restoring from backup archives.
    """

    def __init__(
        self,
        session: AsyncSession,
        storage: StoragePort,
        graph_client: GraphClientPort,
        vector_store_factory: VectorStoreFactory,
    ):
        self.session = session
        self.storage = storage
        self.graph_client = graph_client
        self.vector_store_factory = vector_store_factory

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

        except zipfile.BadZipFile as e:
            raise ValueError("Invalid backup: not a valid ZIP file") from e
        except FileNotFoundError as e:
            raise ValueError("Backup file not found") from e

    async def restore(
        self,
        backup_path: str,
        target_tenant_id: str,
        mode: RestoreMode,
        progress_callback: Callable[[int], None] | None = None,
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
        logger.info(
            f"Restoring backup from {backup_path} to tenant {target_tenant_id}, mode={mode}"
        )

        result = RestoreResult()

        try:
            file_bytes = self.storage.get_file(backup_path)
            zip_buffer = io.BytesIO(file_bytes)

            with zipfile.ZipFile(zip_buffer, "r") as zf:
                # Determine restore strategy
                has_dump = (
                    "database/postgres_dump.sql" in zf.namelist() and mode == RestoreMode.REPLACE
                )

                # Estimated total steps
                # If Dump: Dump(1) + Files(1) + Vectors(1) + Graph(1) = 4
                # If No Dump: Folders+Docs+Convs+Facts+Configs+Chunks = 6, + Files+Vectors+Graph = 9
                total_steps = 4 if has_dump else 9
                current_step = 0

                def update_progress():
                    nonlocal current_step
                    current_step += 1
                    if progress_callback:
                        progress_callback(int(current_step / total_steps * 100))

                # 1. Postgres Dump (Priority)
                if has_dump:
                    await self._restore_postgres_dump(zf)
                    update_progress()
                else:
                    # Standard Granular SQL Restore
                    if mode == RestoreMode.REPLACE:
                        await self._clear_tenant_data(target_tenant_id)
                        logger.info(f"Cleared existing data for tenant {target_tenant_id}")

                    # 1. Folders
                    result.folders_restored = await self._restore_folders(
                        zf, target_tenant_id, mode
                    )
                    update_progress()

                    # 2. Documents
                    result.documents_restored = await self._restore_documents(
                        zf, target_tenant_id, mode
                    )
                    update_progress()

                    # 3. Conversations
                    result.conversations_restored = await self._restore_conversations(
                        zf, target_tenant_id, mode
                    )
                    update_progress()

                    # 4. User Facts
                    result.facts_restored = await self._restore_user_facts(
                        zf, target_tenant_id, mode
                    )
                    update_progress()

                    # 5. Configs & Schedules
                    if "config/global_rules.json" in zf.namelist():
                        if mode == RestoreMode.REPLACE:
                            await self.session.execute(
                                delete(GlobalRule).where(GlobalRule.tenant_id == target_tenant_id)
                            )
                        await self._restore_global_rules(zf, target_tenant_id, mode)

                    if "config/backup_schedules.json" in zf.namelist():
                        if mode == RestoreMode.REPLACE:
                            await self.session.execute(
                                delete(BackupSchedule).where(
                                    BackupSchedule.tenant_id == target_tenant_id
                                )
                            )
                        await self._restore_backup_schedules(zf, target_tenant_id, mode)

                    if "config/tenant_config.json" in zf.namelist():
                        await self._restore_tenant_config(zf, target_tenant_id)
                    update_progress()

                    # 6. Chunks
                    await self._restore_chunks(zf, target_tenant_id, mode)
                    update_progress()

                # Shared Steps (External Systems & Files)

                # Restore Files (MinIO)
                await self._restore_document_files(zf, target_tenant_id)
                update_progress()

                # Restore Vectors (Milvus)
                await self._restore_vectors(zf, target_tenant_id, mode)
                update_progress()

                # Restore Graph (Neo4j)
                await self._restore_graph(zf, target_tenant_id, mode)
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
        await self.session.execute(delete(UserFact).where(UserFact.tenant_id == tenant_id))
        await self.session.execute(
            delete(ConversationSummary).where(ConversationSummary.tenant_id == tenant_id)
        )
        await self.session.execute(delete(Document).where(Document.tenant_id == tenant_id))
        await self.session.execute(delete(Folder).where(Folder.tenant_id == tenant_id))
        await self.session.flush()

    async def _restore_folders(self, zf: zipfile.ZipFile, tenant_id: str, mode: RestoreMode) -> int:
        """Restore folders from backup."""
        count = 0

        if "folders/folders.json" not in zf.namelist():
            return 0

        data = json.loads(zf.read("folders/folders.json"))

        for folder_data in data:
            folder_id = folder_data.get("id")

            # In MERGE mode, skip if exists
            if mode == RestoreMode.MERGE:
                existing = await self.session.execute(select(Folder).where(Folder.id == folder_id))
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

        return count

    async def _restore_documents(
        self, zf: zipfile.ZipFile, tenant_id: str, mode: RestoreMode
    ) -> int:
        """Restore document metadata from backup."""
        count = 0

        if "documents/metadata.json" not in zf.namelist():
            return 0

        data = json.loads(zf.read("documents/metadata.json"))

        for doc_data in data:
            doc_id = doc_data.get("id")

            # In MERGE mode, skip if exists
            if mode == RestoreMode.MERGE:
                existing = await self.session.execute(select(Document).where(Document.id == doc_id))
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

        return count

    async def _restore_document_files(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Restore document files to storage."""
        try:
            # Find all files in documents/files/
            file_entries = [
                name
                for name in zf.namelist()
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
                            content_type=doc.metadata_.get("mime_type")
                            or "application/octet-stream",
                        )

                except Exception as e:
                    logger.warning(f"Error restoring file {file_path}: {e}")

        except Exception as e:
            logger.warning(f"Error restoring document files: {e}")

    async def _restore_conversations(
        self, zf: zipfile.ZipFile, tenant_id: str, mode: RestoreMode
    ) -> int:
        """Restore conversations from backup."""
        count = 0

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

        return count

    async def _restore_user_facts(
        self, zf: zipfile.ZipFile, tenant_id: str, mode: RestoreMode
    ) -> int:
        """Restore user facts from backup."""
        count = 0

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

        return count

    async def _restore_global_rules(
        self, zf: zipfile.ZipFile, tenant_id: str, mode: RestoreMode
    ) -> int:
        """Restore global rules."""
        count = 0
        data = json.loads(zf.read("config/global_rules.json"))
        for rule_data in data:
            rule_id = rule_data.get("id")

            if mode == RestoreMode.MERGE:
                existing = await self.session.execute(
                    select(GlobalRule).where(GlobalRule.id == rule_id)
                )
                if existing.scalar_one_or_none():
                    continue

            rule = GlobalRule(
                id=rule_id,
                tenant_id=tenant_id,
                content=rule_data.get("content"),
                category=rule_data.get("category"),
                priority=rule_data.get("priority", 0),
                is_active=rule_data.get("is_active", True),
                source=rule_data.get("source"),
            )
            self.session.add(rule)
            count += 1
        await self.session.flush()
        return count

    async def _restore_backup_schedules(
        self, zf: zipfile.ZipFile, tenant_id: str, mode: RestoreMode
    ) -> int:
        """Restore backup schedules."""
        count = 0
        data = json.loads(zf.read("config/backup_schedules.json"))
        for schedule_data in data:
            schedule_id = schedule_data.get("id")

            if mode == RestoreMode.MERGE:
                existing = await self.session.execute(
                    select(BackupSchedule).where(BackupSchedule.id == schedule_id)
                )
                if existing.scalar_one_or_none():
                    continue

            schedule = BackupSchedule(
                id=schedule_id,
                tenant_id=tenant_id,
                frequency=schedule_data.get("frequency", "daily"),
                time_utc=schedule_data.get("time_utc", "02:00"),
                day_of_week=schedule_data.get("day_of_week"),
                retention_count=schedule_data.get("retention_count", 7),
                scope=BackupScope(schedule_data.get("scope"))
                if schedule_data.get("scope")
                else None,
                enabled=schedule_data.get("enabled", "false"),
            )
            self.session.add(schedule)
            count += 1
        await self.session.flush()
        return count

    async def _restore_tenant_config(self, zf: zipfile.ZipFile, tenant_id: str) -> None:
        """Restore tenant configuration."""
        data = json.loads(zf.read("config/tenant_config.json"))
        config = data.get("config", {})

        # Update existing tenant
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()

        if tenant:
            tenant.config = config
            # We could also restore name/is_active if desired
            if "name" in data:
                tenant.name = data["name"]
            if "is_active" in data:
                tenant.is_active = data["is_active"]

            self.session.add(tenant)
            await self.session.flush()
            logger.info(f"Restored configuration for tenant {tenant_id}")

    async def _restore_chunks(self, zf: zipfile.ZipFile, tenant_id: str, mode: RestoreMode) -> None:
        """Restore chunks table."""
        if "ingestion/chunks.json" not in zf.namelist():
            return

        data = json.loads(zf.read("ingestion/chunks.json"))

        for chunk_data in data:
            chunk_id = chunk_data.get("id")

            if mode == RestoreMode.MERGE:
                result = await self.session.execute(select(Chunk).where(Chunk.id == chunk_id))
                if result.scalar_one_or_none():
                    continue

            chunk = Chunk(
                id=chunk_id,
                tenant_id=tenant_id,
                document_id=chunk_data.get("document_id"),
                index=chunk_data.get("index", 0),
                tokens=chunk_data.get("tokens", 0),
                content=chunk_data.get("content"),
                metadata_=chunk_data.get("metadata", {}),
                embedding_status=EmbeddingStatus(chunk_data.get("embedding_status", "pending")),
            )
            self.session.add(chunk)

        await self.session.flush()
        logger.info(f"Restored {len(data)} chunks")

    async def _restore_vectors(
        self, zf: zipfile.ZipFile, tenant_id: str, mode: RestoreMode
    ) -> None:
        """Restore vectors to Milvus."""
        from src.core.tenants.application.active_vector_collection import (
            resolve_active_vector_collection,
        )
        from src.core.tenants.domain.tenant import Tenant

        if "vectors/vectors.jsonl" not in zf.namelist():
            return

        # Resolve collection
        res = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant_obj = res.scalar_one_or_none()
        t_config = tenant_obj.config if tenant_obj else {}
        collection_name = resolve_active_vector_collection(tenant_id, t_config)

        # Build ephemeral store
        factory = self.vector_store_factory
        dims = int(t_config.get("embedding_dimensions") or 1536)

        vector_store = factory(dims, collection_name=collection_name)
        logger.info(f"Restoring vectors for tenant {tenant_id} to collection {collection_name}")

        try:
            with zf.open("vectors/vectors.jsonl") as f:

                def vector_gen():
                    for line in f:
                        if line.strip():
                            yield json.loads(line)

                count = await vector_store.import_vectors(vector_gen())
                logger.info(f"Restored {count} vectors")
        finally:
            await vector_store.close()

    async def _restore_graph(self, zf: zipfile.ZipFile, tenant_id: str, mode: RestoreMode) -> None:
        """Restore graph to Neo4j."""

        if "graph/graph.jsonl" not in zf.namelist():
            return

        with zf.open("graph/graph.jsonl") as f:

            def graph_gen():
                for line in f:
                    if line.strip():
                        yield json.loads(line)

            stats = await self.graph_client.import_graph(graph_gen(), mode=mode.value.lower())
            logger.info(f"Restored graph: {stats}")

    async def _restore_postgres_dump(self, zf: zipfile.ZipFile) -> None:
        """Restore full postgres dump using pg_restore/psql."""
        from sqlalchemy.engine.url import make_url

        from src.shared.kernel.runtime import get_settings

        settings = get_settings()
        try:
            tmp_path = f"/tmp/restore_dump_{datetime.now().timestamp()}.sql"
            with open(tmp_path, "wb") as f:
                f.write(zf.read("database/postgres_dump.sql"))

            url = make_url(settings.db.database_url)
            env = os.environ.copy()
            if url.password:
                env["PGPASSWORD"] = url.password

            cmd = [
                "psql",
                "-h",
                url.host or "localhost",
                "-p",
                str(url.port or 5432),
                "-U",
                url.username or "postgres",
                "-d",
                url.database,
                "-f",
                tmp_path,
            ]

            logger.info("Running psql restore")
            process = subprocess.run(cmd, env=env, capture_output=True, text=True)

            if os.path.exists(tmp_path):
                os.remove(tmp_path)

            if process.returncode != 0:
                raise RuntimeError(f"psql restore failed: {process.stderr}")

            logger.info("Full Postgres dump restored successfully")

        except Exception as e:
            logger.error(f"Failed to restore postgres dump: {e}")
            raise
