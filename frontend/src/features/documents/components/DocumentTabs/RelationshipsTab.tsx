import React, { useEffect, useState, useMemo, Suspense } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { apiClient } from '@/lib/api-client';
import { GraphNode, GraphEdge } from '@/types/graph';
import { GraphMode, GraphToolbar } from '../Graph/GraphToolbar';
import { NodeSidebar } from '../Graph/NodeSidebar';
import { HealingSuggestionsModal } from '../Graph/modals/HealingSuggestionsModal';
import { MergeNodesModal } from '../Graph/modals/MergeNodesModal';
import { graphEditorApi } from '@/lib/api-client';
// import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GitMerge } from 'lucide-react';

// Lazy load ThreeGraph
const ThreeGraph = React.lazy(() => import('../Graph/ThreeGraph'));

interface Relationship {
    source: string;
    source_type?: string;
    target: string;
    target_type?: string;
    type: string;
    description: string;
    weight: number;
}

interface RelationshipsTabProps {
    documentId: string;
}

const RelationshipsTab: React.FC<RelationshipsTabProps> = ({ documentId }) => {
    const [relationships, setRelationships] = useState<Relationship[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Graph State
    const [mode, setMode] = useState<GraphMode>('view');
    const [isSidebarOpen, setIsSidebarOpen] = useState(false);
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

    // Connect Mode
    const [connectSource, setConnectSource] = useState<string | null>(null);

    // Heal Mode
    const [isHealingModalOpen, setIsHealingModalOpen] = useState(false);
    const [healingNodeId, setHealingNodeId] = useState<string | null>(null);
    const [healingNodeName, setHealingNodeName] = useState<string | null>(null);

    // Merge Mode
    const [isMergeModalOpen, setIsMergeModalOpen] = useState(false);
    const [mergeCandidates, setMergeCandidates] = useState<GraphNode[]>([]);

    const fetchRelationships = async () => {
        try {
            const response = await apiClient.get<Relationship[]>(`/documents/${documentId}/relationships`);
            setRelationships(response.data);
        } catch (err) {
            console.error(err);
            setError('Failed to load relationships');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (documentId) {
            fetchRelationships();
        }
    }, [documentId]);

    // Handle Mode Changes
    const handleModeChange = (newMode: GraphMode) => {
        setMode(newMode);
        // Reset states
        setConnectSource(null);
        setMergeCandidates([]);
        setIsSidebarOpen(false);
    };

    // Handle Node Click based on Mode
    const handleNodeClick = (node: GraphNode) => {
        if (mode === 'view') {
            setSelectedNode(node);
            setIsSidebarOpen(true);
        }
        else if (mode === 'connect') {
            if (!connectSource) {
                setConnectSource(node.id);
                // toast.info(`Source selected: ${node.label}. Select target node.`);
                console.log(`Source selected: ${node.label}`);
            } else {
                if (connectSource === node.id) {
                    setConnectSource(null);
                    // toast.info("Connection cancelled");
                    return;
                }
                const sourceId = connectSource;
                setConnectSource(null); // Reset immediately to avoid double clicks

                // toast.promise replacement
                graphEditorApi.createEdge({ source: sourceId, target: node.id })
                    .then(() => {
                        fetchRelationships(); // Refresh graph
                        alert('Nodes connected!');
                    })
                    .catch(() => alert('Failed to connect nodes'));
            }
        }
        else if (mode === 'heal') {
            setHealingNodeId(node.id);
            setHealingNodeName(node.label);
            setIsHealingModalOpen(true);
        }
        else if (mode === 'merge') {
            setMergeCandidates(prev => {
                const found = prev.find(n => n.id === node.id);
                if (found) {
                    return prev.filter(n => n.id !== node.id);
                } else {
                    return [...prev, node];
                }
            });
        }
        else if (mode === 'prune') {
            if (confirm(`Are you sure you want to delete node "${node.label}"? This will also remove its connections.`)) {
                graphEditorApi.deleteNode(node.id)
                    .then(() => {
                        alert("Node deleted");
                        fetchRelationships();
                    })
                    .catch(() => alert("Failed to delete node"));
            }
        }
    };

    const handleHealFromSidebar = (nodeId: string) => {
        const node = nodes.find(n => n.id === nodeId);
        if (node) {
            setHealingNodeId(node.id);
            setHealingNodeName(node.label);
            setIsHealingModalOpen(true);
        }
    };

    const handleConnectSuggestion = async (targetId: string, type: string) => {
        if (healingNodeId) {
            await graphEditorApi.createEdge({ source: healingNodeId, target: targetId, type });
            fetchRelationships();
        }
    };


    // Transform logic (copied from original)
    const { nodes, edges } = useMemo(() => {
        const nodeMap = new Map<string, GraphNode>();
        const edgesList: GraphEdge[] = [];

        // Map common entity types to specific color IDs to ensure visual variety
        const PREDEFINED_COLOR_MAP: Record<string, number> = {
            'Organization': 5, // Blue
            'PERSON': 3,       // Violet
            'GEO': 4,          // Emerald
            'LOCATION': 4,     // Emerald
            'DATE': 1,         // Orange
            'TIME': 1,         // Orange
            'EVENT': 6,        // Pink
            'DOCUMENT': 2,     // Cyan
            'File Format': 2,  // Cyan
            'Image Format': 2, // Cyan
            'CONCEPT': 0,      // Amber
            'Concept': 0,      // Amber
            'PRODUCT': 7,      // Red
            'Product': 7,      // Red
            'SERVICE': 0,      // Amber
            'ACTION': 6,       // Pink
            'Action': 6,       // Pink
            'ITEM': 4,         // Emerald
            'RESOURCE': 5,     // Blue
            'COMPONENT': 2,    // Cyan
            'Folder': 1,       // Orange
            'Address Book': 3, // Violet (Role/Person related)
            'ROLE': 3,         // Violet
            'GROUP': 7,        // Red
            'TASK': 6,         // Pink
            'PROCEDURE': 5,    // Blue
            'CLI_COMMAND': 0   // Amber
        };

        const getTypeColorId = (type: string = 'UNKNOWN') => {
            if (PREDEFINED_COLOR_MAP[type] !== undefined) return PREDEFINED_COLOR_MAP[type];
            const upper = type.toUpperCase();
            if (PREDEFINED_COLOR_MAP[upper] !== undefined) return PREDEFINED_COLOR_MAP[upper];

            let hash = 0;
            for (let i = 0; i < type.length; i++) {
                const char = type.charCodeAt(i);
                hash = ((hash << 5) - hash) + char;
                hash = hash & hash;
            }
            return Math.abs(hash);
        };

        relationships.forEach(rel => {
            if (!nodeMap.has(rel.source)) {
                nodeMap.set(rel.source, {
                    id: rel.source,
                    label: rel.source,
                    type: rel.source_type || 'Entity',
                    degree: 0,
                    community_id: getTypeColorId(rel.source_type || 'Entity'),
                    description: 'Loaded from graph' // Placeholder
                });
            }
            if (!nodeMap.has(rel.target)) {
                nodeMap.set(rel.target, {
                    id: rel.target,
                    label: rel.target,
                    type: rel.target_type || 'Entity',
                    degree: 0,
                    community_id: getTypeColorId(rel.target_type || 'Entity'),
                    description: 'Loaded from graph'
                });
            }

            const sourceNode = nodeMap.get(rel.source)!;
            const targetNode = nodeMap.get(rel.target)!;
            sourceNode.degree = (sourceNode.degree || 0) + 1;
            targetNode.degree = (targetNode.degree || 0) + 1;

            edgesList.push({
                source: rel.source,
                target: rel.target,
                weight: rel.weight,
                type: rel.type
            });
        });

        return {
            nodes: Array.from(nodeMap.values()),
            edges: edgesList
        };
    }, [relationships]);


    if (!documentId) return <div className="p-4 text-center text-yellow-500">No document ID provided</div>;
    if (loading) return <div className="p-4 text-center">Loading relationships...</div>;
    if (error) return <div className="p-4 text-center text-red-500">{error}</div>;

    return (
        <Card className="border-0 shadow-none h-full flex flex-col overflow-hidden relative group">
            <CardContent className="flex-1 p-0 min-h-[600px] relative">

                {/* Toolbar */}
                <GraphToolbar
                    mode={mode}
                    onModeChange={handleModeChange}
                />

                {/* Merge Action Button (Floating when candidates selected) */}
                {mode === 'merge' && mergeCandidates.length >= 2 && (
                    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20">
                        <Button onClick={() => setIsMergeModalOpen(true)} className="gap-2 shadow-lg">
                            <GitMerge className="h-4 w-4" />
                            Merge {mergeCandidates.length} Candidates
                        </Button>
                    </div>
                )}

                {/* Sidebar */}
                {isSidebarOpen && selectedNode && (
                    <NodeSidebar
                        node={selectedNode}
                        onClose={() => setIsSidebarOpen(false)}
                        onHeal={handleHealFromSidebar}
                    />
                )}

                {relationships.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-muted-foreground p-8">
                        No relationships found for this document.
                    </div>
                ) : (
                    <Suspense fallback={<div className="h-[600px] w-full flex items-center justify-center bg-black/5 rounded-lg animate-pulse">Loading 3D Graph...</div>}>
                        <ThreeGraph
                            nodes={nodes}
                            edges={edges}
                            onNodeClick={handleNodeClick}
                        />
                    </Suspense>
                )}
            </CardContent>

            {/* Modals */}
            <HealingSuggestionsModal
                isOpen={isHealingModalOpen}
                onClose={() => setIsHealingModalOpen(false)}
                nodeId={healingNodeId}
                nodeName={healingNodeName}
                onConnect={handleConnectSuggestion}
            />

            <MergeNodesModal
                isOpen={isMergeModalOpen}
                onClose={() => setIsMergeModalOpen(false)}
                nodes={mergeCandidates}
                onMergeComplete={() => {
                    setMergeCandidates([]);
                    fetchRelationships();
                }}
            />

            {connectSource && (
                <div className="absolute top-4 right-4 z-10 bg-primary text-primary-foreground px-3 py-1.5 rounded-full text-sm font-medium shadow-lg animate-pulse">
                    Select Target Node to Connect
                </div>
            )}
        </Card>
    );
};

export default RelationshipsTab;
