
import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from src.api.main import app
from src.core.graph.neo4j_client import neo4j_client

@pytest.fixture
def api_key() -> str:
    return "amber-dev-key-2024"

@pytest.fixture
async def test_client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

class TestSimilarity:
    
    @pytest.mark.asyncio
    async def test_similarity_creation(
        self,
        test_client: AsyncClient,
        api_key: str
    ):
        import uuid
        run_id = str(uuid.uuid4())
        # Create two documents with similar but not identical content to avoid deduplication
        # Doc 1
        text_1 = f"The quick brown fox jumps over the lazy dog. {run_id} " * 20
        # Doc 2 (Semantically similar)
        text_2 = f"A fast brown fox leaps over a lazy dog. {run_id} " * 20
        
        async def create_pdf(text, filename):
            pdf_content = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length {len(text) + 100} >>
stream
BT
/F1 12 Tf
10 700 Td
({text}) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
trailer
<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF
""".encode()
            files = {"file": (filename, pdf_content, "application/pdf")}
            
            # Force eager (needs to be done globally or once)
            from src.workers.celery_app import celery_app
            celery_app.conf.task_always_eager = True
            celery_app.conf.task_eager_propagates = True
            
            # Patch process_communities
            from unittest.mock import patch
            with patch("src.workers.tasks.process_communities"):
                print(f"Uploading {filename}...")
                response = await test_client.post(
                    "/v1/documents",
                    headers={"X-API-Key": api_key},
                    files=files
                )
                assert response.status_code == 202
                return response.json()["document_id"]

        # Upload Doc 1
        doc_id_1 = await create_pdf(text_1, "doc1.pdf")
        
        # Wait for Doc 1
        print("Waiting for Doc 1 processing...")
        for _ in range(30):
            await asyncio.sleep(1)
            resp = await test_client.get(f"/v1/documents/{doc_id_1}", headers={"X-API-Key": api_key})
            if resp.json()["status"] in ["ready", "failed"]:
                break
        assert resp.json()["status"] == "ready"

        # Upload Doc 2
        doc_id_2 = await create_pdf(text_2, "doc2.pdf")
        
        # Wait for Doc 2
        print("Waiting for Doc 2 processing...")
        for _ in range(30):
            await asyncio.sleep(1)
            resp = await test_client.get(f"/v1/documents/{doc_id_2}", headers={"X-API-Key": api_key})
            if resp.json()["status"] in ["ready", "failed"]:
                break
        assert resp.json()["status"] == "ready"

        # Check Neo4j for Similarity Edges BETWEEN keys
        print("Checking for Similarity Edges...")
        await neo4j_client.connect()
        try:
            # Check edge from Doc 2 chunk to Doc 1 chunk
            # Note: We query CHUNKS but filtered by doc_id
            query = """
            MATCH (c1:Chunk {document_id: $doc2})-[r:SIMILAR_TO]->(c2:Chunk {document_id: $doc1})
            RETURN count(r) as count
            """
            result = await neo4j_client.execute_read(query, {"doc1": doc_id_1, "doc2": doc_id_2})
            count = result[0]["count"]
            print(f"Similarity Edges from Doc2 to Doc1: {count}")
            
            if count == 0:
                 # Debug: Check if ANY edge exists for Doc 2
                 debug_q = "MATCH (c1:Chunk {document_id: $doc2})-[r:SIMILAR_TO]->(c2) RETURN c2.document_id as target, r.score as score"
                 debug_res = await neo4j_client.execute_read(debug_q, {"doc2": doc_id_2})
                 print("DEBUG: All similarity edges for Doc2:", debug_res)

            assert count > 0, "No similarity edges created between similar documents!"

        finally:
            await neo4j_client.close()
