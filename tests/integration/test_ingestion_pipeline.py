"""
Integration Test for Complete Ingestion Pipeline
=================================================

Tests the full document ingestion pipeline including:
- Upload and storage
- Text extraction
- Classification
- Semantic chunking
- Embedding generation
- Knowledge graph extraction
- Neo4j sync
- Milvus vector storage

Run with: pytest tests/integration/test_ingestion_pipeline.py -v
"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.config import settings
from src.api.main import app
from src.core.graph.neo4j_client import neo4j_client
from src.core.vector_store.milvus import MilvusConfig, MilvusVectorStore

# Test PDF content as bytes
TEST_PDF_CONTENT = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
/Resources <<
/Font <<
/F1 5 0 R
>>
>>
>>
endobj
4 0 obj
<<
/Length 480
>>
stream
BT
/F1 18 Tf
50 720 Td
(Integration Test Document) Tj
0 -35 Td
/F1 14 Tf
(Company Information) Tj
0 -30 Td
/F1 11 Tf
(Anthropic is an AI safety company founded by Dario Amodei) Tj
0 -18 Td
(and Daniela Amodei in 2021. The company developed Claude,) Tj
0 -18 Td
(a large language model assistant.) Tj
0 -35 Td
/F1 14 Tf
(Technology Stack) Tj
0 -30 Td
/F1 11 Tf
(The system uses Neo4j for graph storage, Milvus for) Tj
0 -18 Td
(vector embeddings, and PostgreSQL for metadata.) Tj
0 -18 Td
(OpenAI provides embedding generation capabilities.) Tj
0 -35 Td
/F1 14 Tf
(Leadership) Tj
0 -30 Td
/F1 11 Tf
(Dario Amodei serves as CEO while Daniela Amodei is President.) Tj
ET
endstream
endobj
5 0 obj
<<
/Type /Font
/Subtype /Type1
/BaseFont /Helvetica
>>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000270 00000 n
0000000802 00000 n
trailer
<<
/Size 6
/Root 1 0 R
>>
startxref
882
%%EOF
"""


@pytest.fixture
def api_key() -> str:
    """Get test API key."""
    return "amber-dev-key-2024"


@pytest.fixture
async def test_client() -> AsyncClient:
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def test_pdf_file() -> tuple[str, bytes, str]:
    """Create test PDF file."""
    return ("test_integration.pdf", TEST_PDF_CONTENT, "application/pdf")


class TestIngestionPipeline:
    """Integration tests for the complete ingestion pipeline."""

    @pytest.mark.asyncio
    async def test_complete_pipeline(
        self,
        test_client: AsyncClient,
        api_key: str,
        test_pdf_file: tuple[str, bytes, str]
    ):
        """
        Test the complete ingestion pipeline from upload to graph sync.

        This test verifies:
        1. Document upload succeeds
        2. Document processes through all stages
        3. Chunks are created and embedded
        4. Entities are extracted
        5. Relationships are created
        6. Data exists in Neo4j
        7. Embeddings exist in Milvus
        """
        filename, content, content_type = test_pdf_file

        # Step 1: Upload document
        print("\n1. Uploading document...")
        files = {"file": (filename, content, content_type)}
        response = await test_client.post(
            "/v1/documents",
            headers={"X-API-Key": api_key},
            files=files
        )

        assert response.status_code == 202, f"Upload failed: {response.text}"
        upload_data = response.json()
        document_id = upload_data["document_id"]

        assert document_id is not None
        assert upload_data["status"] == "ingested"
        print(f"   ✓ Document uploaded: {document_id}")

        # Step 2: Wait for processing to complete
        print("2. Waiting for processing...")
        max_wait = 60  # 60 seconds max
        status = None

        for i in range(max_wait):
            await asyncio.sleep(1)
            response = await test_client.get(
                f"/v1/documents/{document_id}",
                headers={"X-API-Key": api_key}
            )
            assert response.status_code == 200

            doc_data = response.json()
            status = doc_data["status"]

            if status in ["ready", "failed"]:
                break

            if i % 5 == 0:
                print(f"   Status: {status} ({i}s)")

        assert status == "ready", f"Document failed or timed out. Status: {status}"
        print(f"   ✓ Processing complete: {status}")

        # Step 3: Verify chunks
        print("3. Verifying chunks...")
        response = await test_client.get(
            f"/v1/documents/{document_id}/chunks",
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200
        chunks = response.json()

        assert len(chunks) > 0, "No chunks created"
        embedded_count = sum(1 for c in chunks if c["embedding_status"] == "completed")
        assert embedded_count == len(chunks), "Not all chunks have embeddings"
        print(f"   ✓ {len(chunks)} chunks created with embeddings")

        # Step 4: Verify entities
        print("4. Verifying entities...")
        response = await test_client.get(
            f"/v1/documents/{document_id}/entities",
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200
        entities = response.json()

        assert len(entities) > 0, "No entities extracted"
        entity_names = {e["name"] for e in entities}
        print(f"   ✓ {len(entities)} entities extracted")
        print(f"     Sample: {list(entity_names)[:5]}")

        # Step 5: Verify relationships
        print("5. Verifying relationships...")
        response = await test_client.get(
            f"/v1/documents/{document_id}/relationships",
            headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200
        relationships = response.json()

        assert len(relationships) > 0, "No relationships created"
        print(f"   ✓ {len(relationships)} relationships created")

        # Step 6: Verify Neo4j graph structure
        print("6. Verifying Neo4j graph...")
        await neo4j_client.connect()

        try:
            # Check document node
            doc_query = """
            MATCH (d:Document {id: $doc_id})
            RETURN count(d) as count
            """
            result = await neo4j_client.execute_read(doc_query, {"doc_id": document_id})
            assert result[0]["count"] == 1, "Document not in Neo4j"

            # Check chunks
            chunk_query = """
            MATCH (d:Document {id: $doc_id})-[:HAS_CHUNK]->(c:Chunk)
            RETURN count(c) as count
            """
            result = await neo4j_client.execute_read(chunk_query, {"doc_id": document_id})
            neo4j_chunks = result[0]["count"]
            assert neo4j_chunks == len(chunks), f"Chunk mismatch: {neo4j_chunks} vs {len(chunks)}"

            # Check entities
            entity_query = """
            MATCH (c:Chunk {document_id: $doc_id})-[:MENTIONS]->(e:Entity)
            RETURN count(DISTINCT e) as count
            """
            result = await neo4j_client.execute_read(entity_query, {"doc_id": document_id})
            neo4j_entities = result[0]["count"]
            assert neo4j_entities == len(entities), f"Entity mismatch: {neo4j_entities} vs {len(entities)}"

            print(f"   ✓ Neo4j verified: 1 doc, {neo4j_chunks} chunks, {neo4j_entities} entities")

        finally:
            await neo4j_client.close()

        # Step 7: Verify Milvus embeddings
        print("7. Verifying Milvus embeddings...")
        config = MilvusConfig(
            host=settings.db.milvus_host,
            port=settings.db.milvus_port,
            collection_name=f"amber_{doc_data['tenant_id']}"
        )

        vector_store = MilvusVectorStore(config)
        await vector_store.connect()

        try:
            milvus_results = vector_store._collection.query(
                expr=f'document_id == "{document_id}"',
                output_fields=["chunk_id", "document_id"],
                limit=100
            )

            assert len(milvus_results) == len(chunks), f"Milvus mismatch: {len(milvus_results)} vs {len(chunks)}"
            print(f"   ✓ {len(milvus_results)} vectors in Milvus")

        finally:
            await vector_store.disconnect()

        print("\n✅ All pipeline stages verified!")

        return {
            "document_id": document_id,
            "chunks": len(chunks),
            "entities": len(entities),
            "relationships": len(relationships),
            "status": "passed"
        }


if __name__ == "__main__":
    # Allow running standalone
    async def run_test():
        from httpx import ASGITransport, AsyncClient

        api_key = "amber-dev-key-2024"
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            test = TestIngestionPipeline()
            result = await test.test_complete_pipeline(
                client,
                api_key,
                ("test_integration.pdf", TEST_PDF_CONTENT, "application/pdf")
            )

            print(f"\n{'='*60}")
            print("TEST RESULTS:")
            print(f"{'='*60}")
            for key, value in result.items():
                print(f"  {key}: {value}")
            print(f"{'='*60}\n")

    asyncio.run(run_test())
