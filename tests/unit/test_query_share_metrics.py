from src.core.retrieval.application.use_cases_query import QueryUseCase


def test_extract_share_metrics_from_trace():
    trace = [
        {
            "step": "resolve_vector_targets",
            "targets": [
                {
                    "tenant_id": "default",
                    "requested_document_ids_count": 3,
                    "document_ids_count": 1,
                    "acl_filtered_out_count": 2,
                }
            ],
        },
        {
            "step": "resolve_graph_targets",
            "targets": [
                {
                    "tenant_id": "default",
                    "requested_document_ids_count": 4,
                    "document_ids_count": 2,
                    "acl_filtered_out_count": 2,
                }
            ],
        },
        {
            "step": "vector_search",
            "targets": [
                {"tenant_id": "default", "results_count": 2},
                {"tenant_id": "tenant-pe", "results_count": 3},
            ],
        },
        {
            "step": "global_search",
            "targets": [
                {"tenant_id": "default", "results_count": 1},
            ],
        },
    ]

    assert QueryUseCase._extract_share_metrics("tenant-pe", trace) == {
        "local_hits": 3,
        "shared_hits": 3,
        "acl_filtered_results": 4,
    }
