"""
Unit tests for QueryUseCase._extract_taxonomy_metrics
"""


from src.core.retrieval.application.use_cases_query import QueryUseCase


class TestExtractTaxonomyMetrics:
    """Tests for the static helper that pulls taxonomy_routing data from trace."""

    def test_returns_none_for_empty_trace(self):
        assert QueryUseCase._extract_taxonomy_metrics([]) is None

    def test_returns_none_when_step_absent(self):
        trace = [
            {"step": "vector_search", "duration_ms": 10},
            {"step": "global_search", "duration_ms": 5},
        ]
        assert QueryUseCase._extract_taxonomy_metrics(trace) is None

    def test_extracts_commercial_admin(self):
        trace = [
            {
                "step": "taxonomy_routing",
                "inferred_edition": "commercial",
                "inferred_audience": "admin",
                "broadening_stage": "strict",
                "strict_candidate_count": 120,
                "duration_ms": 2,
            }
        ]
        result = QueryUseCase._extract_taxonomy_metrics(trace)
        assert result is not None
        assert result["inferred_edition"] == "commercial"
        assert result["inferred_audience"] == "admin"
        assert result["broadening_stage"] == "strict"
        assert result["strict_candidate_count"] == 120

    def test_extracts_ce_admin(self):
        trace = [
            {
                "step": "taxonomy_routing",
                "inferred_edition": "ce",
                "inferred_audience": "admin",
                "broadening_stage": "strict",
                "strict_candidate_count": 82,
                "duration_ms": 1,
            }
        ]
        result = QueryUseCase._extract_taxonomy_metrics(trace)
        assert result["inferred_edition"] == "ce"

    def test_extracts_user_audience(self):
        trace = [
            {
                "step": "taxonomy_routing",
                "inferred_edition": "commercial",
                "inferred_audience": "user",
                "broadening_stage": "strict",
                "strict_candidate_count": 38,
            }
        ]
        result = QueryUseCase._extract_taxonomy_metrics(trace)
        assert result["inferred_audience"] == "user"

    def test_extracts_broadening_stage(self):
        trace = [
            {
                "step": "taxonomy_routing",
                "inferred_edition": "commercial",
                "inferred_audience": "admin",
                "broadening_stage": "edition_only",
                "strict_candidate_count": 0,
            }
        ]
        result = QueryUseCase._extract_taxonomy_metrics(trace)
        assert result["broadening_stage"] == "edition_only"
        assert result["strict_candidate_count"] == 0

    def test_returns_first_taxonomy_step(self):
        trace = [
            {"step": "vector_search", "duration_ms": 5},
            {
                "step": "taxonomy_routing",
                "inferred_edition": "commercial",
                "inferred_audience": "admin",
                "broadening_stage": "strict",
                "strict_candidate_count": 50,
            },
            {
                "step": "taxonomy_routing",
                "inferred_edition": "ce",
                "inferred_audience": "admin",
                "broadening_stage": "strict",
                "strict_candidate_count": 99,
            },
        ]
        result = QueryUseCase._extract_taxonomy_metrics(trace)
        assert result["inferred_edition"] == "commercial"

    def test_handles_none_trace(self):
        assert QueryUseCase._extract_taxonomy_metrics(None) is None

    def test_missing_fields_return_none_values(self):
        trace = [{"step": "taxonomy_routing"}]
        result = QueryUseCase._extract_taxonomy_metrics(trace)
        assert result is not None
        assert result["inferred_edition"] is None
        assert result["broadening_stage"] is None
