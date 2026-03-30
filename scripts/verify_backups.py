
import asyncio
import io
import os
import sys
import zipfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Add src to path
sys.path.append(os.getcwd())

from src.core.admin_ops.domain.backup_job import BackupJob, BackupStatus
from src.core.ingestion.infrastructure.storage.storage_client import MinIOClient

# Configuration
# Read from env or use defaults matching docker-compose
DB_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://graphrag:graphrag@postgres:5432/graphrag")
MINIO_HOST = os.getenv("MINIO_HOST", "minio")
MINIO_PORT = int(os.getenv("MINIO_PORT", 9000))
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET_NAME", "documents")

async def verify_backups():
    print("Connecting to database...")
    engine = create_async_engine(DB_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        print("Querying latest backups...")
        result = await session.execute(
            select(BackupJob)
            .where(BackupJob.status == BackupStatus.COMPLETED)
            .order_by(BackupJob.created_at.desc())
            .limit(2)
        )
        jobs = result.scalars().all()

        if not jobs:
            print("No completed backups found.")
            return

        # Initialize storage
        storage = MinIOClient(
            host=MINIO_HOST,
            port=MINIO_PORT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False,
            bucket_name=MINIO_BUCKET
        )

        print(f"\nFound {len(jobs)} backups. Verifying contents...\n")

        for job in jobs:
            print(f"=== Backup {job.scope.value} ({job.id}) ===")
            print(f"Size: {job.file_size} bytes")
            print(f"Path: {job.result_path}")

            try:
                print("Downloading file stream...")
                file_bytes = storage.get_file(job.result_path)

                with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                    print("\n--- Content Listing ---")
                    for info in zf.infolist():
                        print(f"{info.filename:<50} {info.file_size:>10} bytes")

                # Check manifest specifically
                with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                    if "manifest.json" in zf.namelist():
                        print("\n--- Manifest ---")
                        print(zf.read("manifest.json").decode())
                    else:
                        print("\nWARNING: No manifest.json found!")

            except Exception as e:
                print(f"ERROR verifying backup: {e}")

            print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(verify_backups())
