import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'

import { apiClient } from '@/lib/api-client'
import { GraphNode, GraphEdge } from '@/types/graph'
import ThreeGraph from '../Graph/ThreeGraph'

interface DocumentSubgraphProps {
    documentId: string
}

interface SubgraphResponse {
    nodes: GraphNode[]
    edges: GraphEdge[]
}

export default function DocumentSubgraph({ documentId }: DocumentSubgraphProps) {
    const { data, isLoading, error } = useQuery<SubgraphResponse>({
        queryKey: ['document-subgraph', documentId],
        queryFn: async () => {
            const response = await apiClient.get<SubgraphResponse>(
                `/documents/${documentId}/subgraph`,
                { params: { limit_nodes: 200, limit_edges: 500 } }
            )
            return response.data
        },
        staleTime: 60_000,
    })

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-full text-muted-foreground text-sm gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading subgraph…
            </div>
        )
    }

    if (error || !data) {
        return (
            <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                Failed to load subgraph.
            </div>
        )
    }

    if (data.nodes.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-sm gap-1">
                <p>No entities extracted from this document yet.</p>
                <p className="text-xs">Subgraph will appear once ingestion completes.</p>
            </div>
        )
    }

    return (
        <div className="relative w-full h-full">
            <ThreeGraph
                nodes={data.nodes}
                edges={data.edges}
                onNodeClick={() => { /* read-only view */ }}
                highlightedNodeIds={[]}
                zoomToNodeId={null}
            />
            <div className="absolute bottom-3 right-3 px-3 py-1.5 rounded-md bg-background/70 backdrop-blur-md border border-border text-xs text-muted-foreground font-mono">
                {data.nodes.length} nodes · {data.edges.length} edges
            </div>
        </div>
    )
}
