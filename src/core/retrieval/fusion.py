
from src.core.models.candidate import Candidate


def fuse_results(
    results_groups: dict[str, list[Candidate]],
    k: int = 60,
    weights: dict[str, float] = None
) -> list[Candidate]:
    """
    Reciprocal Rank Fusion (RRF) to combine multiple ranked lists.
    Formula: score = sum(weight / (k + rank))

    Args:
        results_groups: Dictionary mapping source name to its list of Candidates.
        k: Smoothing constant (default 60).
        weights: Optional dictionary of weights per source.
    """
    if weights is None:
        weights = dict.fromkeys(results_groups.keys(), 1.0)

    fused_scores = {} # chunk_id -> rrf_score
    candidates_map = {} # chunk_id -> Candidate (latest/best version)

    for source, candidates in results_groups.items():
        weight = weights.get(source, 1.0)

        for rank, candidate in enumerate(candidates, start=1):
            chunk_id = candidate.chunk_id

            # Calculate RRF contribution
            rrf_contrib = weight / (k + rank)

            if chunk_id not in fused_scores:
                fused_scores[chunk_id] = 0.0
                candidates_map[chunk_id] = candidate

            fused_scores[chunk_id] += rrf_contrib

            # Update source to 'hybrid' if multiple sources found the same chunk
            if candidates_map[chunk_id].source != candidate.source:
                candidates_map[chunk_id].source = "hybrid"

    # Create final sorted list
    final_candidates = []
    for chunk_id, score in fused_scores.items():
        candidate = candidates_map[chunk_id]
        candidate.score = score
        final_candidates.append(candidate)

    # Sort by descending RRF score
    final_candidates.sort(key=lambda x: x.score, reverse=True)

    return final_candidates
