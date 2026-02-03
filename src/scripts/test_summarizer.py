import asyncio
import sys
import os

# Add src to path
sys.path.append(os.getcwd())

from src.api.config import settings
from src.core.database.session import configure_database, get_session_maker
from src.core.ingestion.domain.document import Document
from src.core.ingestion.domain.chunk import Chunk
from src.core.ingestion.domain.folder import Folder
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.core.generation.application.intelligence.document_summarizer import get_document_summarizer

async def main():
    print("Configuring DB...")
    configure_database(settings.db.database_url)
    
    # Configure runtime settings for services that use get_settings()
    from src.shared.kernel.runtime import configure_settings
    configure_settings(settings)
    
    # Initialize providers
    from src.core.generation.infrastructure.providers.factory import init_providers
    init_providers(
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key,
        default_llm_provider=settings.default_llm_provider,
        default_llm_model=settings.default_llm_model,
        default_embedding_provider=settings.default_embedding_provider,
        default_embedding_model=settings.default_embedding_model,
    )
    
    session_maker = get_session_maker()
    filename = "Backup not Running after upgrade to Carbonio 25.6.0   Howto fix   Zextras Group.pdf"

    async with session_maker() as session:
        stmt = select(Document).options(selectinload(Document.chunks)).where(Document.filename == filename)
        result = await session.execute(stmt)
        doc = result.scalars().first()
        
        if not doc:
            print("Document not found")
            return

        print(f"Document found: {doc.id}")
        chunk_texts = [c.content for c in doc.chunks]
        print(f"Chunks: {len(chunk_texts)}")
        
        print("Initializing Summarizer...")
        summarizer = get_document_summarizer()
        
        print("Attempting to summarize...")
        try:
            # We need to simulate the environment settings if they aren't picked up automatically
            # The summarizer uses settings.openai_api_key etc.
            
            result = await summarizer.extract_summary(
                chunks=chunk_texts,
                document_title=doc.filename
            )
            print("Result:", result)
        except Exception as e:
            print("Summarization Failed with error:")
            print(e)
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
