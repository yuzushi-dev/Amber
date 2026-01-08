export interface GraphNode {
    id: string;
    label: string;
    type?: string | null;
    community_id?: number | null;
    degree?: number;
    color?: string;
    val?: number;
    x?: number;
    y?: number;
    z?: number;
    // For Heal/Merge UI
    description?: string;
}

export interface GraphEdge {
    source: string;
    target: string;
    weight?: number;
    type?: string | null;
    description?: string;
}

export interface HealingSuggestion {
    id: string;
    name: string;
    type: string;
    description: string;
    confidence: number;
    reason: string;
}

export interface HealRequest {
    node_id: string;
}

export interface MergeRequest {
    target_id: string;
    source_ids: string[];
}

export interface EdgeRequest {
    source: string;
    target: string;
    type?: string;
    description?: string;
}
