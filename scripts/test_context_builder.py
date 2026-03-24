
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.generation.application.context_builder import ContextBuilder
from src.core.retrieval.domain.candidate import Candidate

def test_context_builder():
    builder = ContextBuilder(max_tokens=1000)
    
    # Test case 1: Candidate object with metadata
    c1 = Candidate(
        chunk_id="ch1",
        content="This is Carbonio Admin content.",
        metadata={"title": "Admin Guide", "product_context": "carbonio", "audience": "admin_cli"}
    )
    
    # Test case 2: Dict candidate (flattened or nested)
    c2 = {
        "content": "This is mixed context content.",
        "metadata": {"title": "Zendesk KB", "product_context": "mixed", "audience": "mixed"}
    }
    
    # Test case 3: Flattened dict
    c3 = {
        "content": "No product context here.",
        "title": "Old Doc"
    }

    res = builder.build([c1, c2, c3])
    print("--- Context Output ---")
    print(res.content)
    print("----------------------")
    
    # Verifications
    assert "[Product: carbonio] [Audience: admin_cli]" in res.content
    assert "[Product: mixed] [Audience: mixed]" in res.content
    assert "No product context here" in res.content
    assert "[Product:" not in res.content.split("\n\n")[-1]  # c3 shouldn't have it
    
    print("Verification Successful!")

if __name__ == "__main__":
    test_context_builder()
