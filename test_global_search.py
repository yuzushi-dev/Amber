import asyncio

from src.amber_platform.composition_root import (
    build_retrieval_service,
    build_session_factory,
    configure_settings,
    platform,
)
from src.api.config import settings


async def test():
    print("Initializing platform...")
    configure_settings(settings)

    from src.core.database.session import configure_database
    configure_database(settings.db.database_url)

    await platform.initialize()
    session_maker = build_session_factory()
    async with session_maker() as session:
        retrieval_service = build_retrieval_service(session)

    try:
        print("Executing Global Search directly...")
        from src.shared.kernel.models.query import QueryOptions, SearchMode
        res = await retrieval_service.retrieve(
            query="What are the main topics and entities discussed?",
            tenant_id="default",
            options=QueryOptions(search_mode=SearchMode.GLOBAL)
        )
        print("--- Global Search Result ---")
        print(f"Number of chunks matched: {len(res.chunks)}")

        for idx, c in enumerate(res.chunks, 1):
            doc_id = c.get('document_id', 'unknown')
            chunk_id = c.get('chunk_id', 'unknown')
            score = c.get('score', 0.0)
            content_preview = c.get('content', '')[:100].replace('\n', ' ')
            print(f"[{idx}] Doc: {doc_id} | Chunk: {chunk_id} | Score: {score}")
            print(f"    Preview: {content_preview}...")

    finally:
        await platform.shutdown()
        print("Platform closed.")

if __name__ == "__main__":
    asyncio.run(test())
