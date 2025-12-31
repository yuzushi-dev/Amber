from typing import Dict, Optional

def get_adaptive_weights(
    domain: Optional[str] = None,
    query_type: Optional[str] = None,
    tenant_config: Optional[Dict[str, float]] = None
) -> Dict[str, float]:
    """
    Returns adaptive fusion weights based on document domain or query classification.
    """
    # Default balanced weights
    weights = {
        "vector": 1.0,
        "graph": 1.0,
        "community": 1.0
    }
    
    # Adjust based on domain (from Phase 1 classification)
    if domain:
        domain = domain.lower()
        if domain in ["technical", "legal", "scientific"]:
            # These benefit more from keyword/graph precision
            weights["graph"] = 1.2
            weights["vector"] = 0.8
        elif domain in ["conversational", "creative"]:
            # These benefit more from semantic vector similarity
            weights["vector"] = 1.2
            weights["graph"] = 0.8
            
    # Adjust based on query type (from Phase 5 routing)
    if query_type:
        query_type = query_type.upper()
        if query_type == "GLOBAL":
            weights["community"] = 1.5
            weights["vector"] = 0.5
        elif query_type == "LOCAL":
            weights["graph"] = 1.3
            weights["vector"] = 0.7
            
    # Apply tenant-specific overrides if provided
    if tenant_config:
        for k, v in tenant_config.items():
            if k in weights:
                weights[k] = v

    return weights
