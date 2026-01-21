import { useEffect, useState, useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { graphEditorApi, graphHistoryApi } from '@/lib/api-client';
import { GraphNode, GraphEdge } from '@/types/graph';
import ThreeGraph from '../../documents/components/Graph/ThreeGraph';
import { GraphToolbar, GraphMode } from '../../documents/components/Graph/GraphToolbar';
import { GraphSearchInput } from '../components/GraphSearchInput';
import { GraphHistoryModal } from '../components/GraphHistoryModal';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';

export default function GlobalGraphPage() {
    const queryClient = useQueryClient();
    const [graphData, setGraphData] = useState<{ nodes: GraphNode[], edges: GraphEdge[] }>({ nodes: [], edges: [] });
    const [isLoading, setIsLoading] = useState(false);
    const [hasSearched, setHasSearched] = useState(false);
    const [isInputFocused, setIsInputFocused] = useState(false);
    const [isExploring, setIsExploring] = useState(false); // New state for manual exploration without search
    const [highlightedNodes, setHighlightedNodes] = useState<string[]>([]);
    const [cameraFocusNode, setCameraFocusNode] = useState<string | null>(null);
    const [graphMode, setGraphMode] = useState<GraphMode>('view');
    const [showHistoryModal, setShowHistoryModal] = useState(false);

    // Query for pending edit count
    const { data: pendingCount = 0 } = useQuery({
        queryKey: ['graph-history-pending-count'],
        queryFn: graphHistoryApi.getPendingCount,
        refetchInterval: 10000, // Refresh every 10s
    });

    // Derived state for UI view mode
    const isInteractive = hasSearched || isExploring;

    // Initial load of top nodes for background
    useEffect(() => {
        const loadTopNodes = async () => {
            try {
                // Fetch top 15 nodes for ambient background
                const nodes = await graphEditorApi.getTopNodes(15);
                setGraphData({ nodes, edges: [] });
            } catch (error) {
                console.error("Failed to load top nodes", error);
            }
        };
        loadTopNodes();
    }, []);

    const handleSearch = async (query: string) => {
        if (!query.trim()) return;

        setIsLoading(true);
        setCameraFocusNode(null); // Reset focus to trigger change

        try {
            const results = await graphEditorApi.searchNodes(query);
            if (results.length === 0) {
                toast.info("No nodes found");
                setIsLoading(false);
                return;
            }

            // Highlight results
            setHighlightedNodes(results.map(n => n.id));

            // Provide immediate feedback by showing results
            // Fetch neighborhood of the first top result to give context immediately
            let initialNodes = [...results];
            let initialEdges: GraphEdge[] = [];

            if (results.length > 0) {
                const firstNode = results[0];
                const neighborhood = await graphEditorApi.getNeighborhood(firstNode.id);

                // Merge neighborhood
                // Deduplicate nodes
                const nodeMap = new Map(initialNodes.map(n => [n.id, n]));
                neighborhood.nodes.forEach(n => nodeMap.set(n.id, n));
                initialNodes = Array.from(nodeMap.values());
                initialEdges = neighborhood.edges;

                // Focus camera on top result
                setCameraFocusNode(firstNode.id);
            }

            setGraphData({ nodes: initialNodes, edges: initialEdges });
            setHasSearched(true);
        } catch (error) {
            console.error(error);
            toast.error("Search failed");
        } finally {
            setIsLoading(false);
        }
    };

    // State for multi-node selection (connect, merge modes)
    const [selectedNodes, setSelectedNodes] = useState<GraphNode[]>([]);

    const handleNodeClick = async (node: GraphNode) => {
        // Handle different modes
        if (graphMode === 'prune') {
            // Create pending prune/delete_node action with snapshot for undo
            try {
                await graphHistoryApi.create({
                    action_type: 'prune',
                    payload: { node_id: node.id, label: node.label },
                    snapshot: { node }, // Store full node for undo restoration
                    source_view: 'global'
                });
                toast.success(`Queued "${node.label}" for pruning`, {
                    description: 'Open History to review and apply'
                });
                // Invalidate pending count and history list
                queryClient.invalidateQueries({ queryKey: ['graph-history-pending-count'] });
                queryClient.invalidateQueries({ queryKey: ['graph-history'] });
            } catch (error) {
                console.error(error);
                toast.error('Failed to queue prune action');
            }
            return;
        }

        if (graphMode === 'connect') {
            // Track node selection for connecting
            if (selectedNodes.length === 0) {
                setSelectedNodes([node]);
                setHighlightedNodes([node.id]);
                toast.info(`Selected "${node.label}" as source`, {
                    description: 'Click another node to connect'
                });
            } else if (selectedNodes.length === 1) {
                const source = selectedNodes[0];
                if (source.id === node.id) {
                    toast.warning('Cannot connect a node to itself');
                    return;
                }
                // Create pending connect action
                try {
                    await graphHistoryApi.create({
                        action_type: 'connect',
                        payload: {
                            source: source.id,
                            target: node.id,
                            type: 'RELATED_TO'
                        },
                        source_view: 'global'
                    });
                    toast.success(`Queued connection: "${source.label}" → "${node.label}"`, {
                        description: 'Open History to review and apply'
                    });
                    queryClient.invalidateQueries({ queryKey: ['graph-history-pending-count'] });
                    queryClient.invalidateQueries({ queryKey: ['graph-history'] });
                } catch (error) {
                    console.error(error);
                    toast.error('Failed to queue connect action');
                }
                // Reset selection
                setSelectedNodes([]);
                setHighlightedNodes([]);
            }
            return;
        }

        if (graphMode === 'merge') {
            // Track node selection for merging (first selected = target, rest = sources)
            const isAlreadySelected = selectedNodes.some(n => n.id === node.id);
            if (isAlreadySelected) {
                // Deselect
                const updated = selectedNodes.filter(n => n.id !== node.id);
                setSelectedNodes(updated);
                setHighlightedNodes(updated.map(n => n.id));
                toast.info(`Deselected "${node.label}"`);
            } else {
                const updated = [...selectedNodes, node];
                setSelectedNodes(updated);
                setHighlightedNodes(updated.map(n => n.id));

                if (updated.length === 1) {
                    toast.info(`Selected "${node.label}" as merge target`, {
                        description: 'Select more nodes to merge into this one, then switch to View mode to confirm'
                    });
                } else {
                    toast.info(`Added "${node.label}" to merge selection (${updated.length} nodes)`);
                }
            }
            return;
        }

        if (graphMode === 'heal') {
            // AI-assisted healing - show suggestions for this node
            toast.info(`Heal mode for "${node.label}"`, {
                description: 'AI suggestions coming soon'
            });
            return;
        }

        // View mode - expand neighborhood
        try {
            const neighborhood = await graphEditorApi.getNeighborhood(node.id);

            setGraphData(prev => {
                const nodeMap = new Map(prev.nodes.map(n => [n.id, n]));
                const existingEdgeKeys = new Set(prev.edges.map(e => `${e.source}-${e.target}`));

                neighborhood.nodes.forEach(n => nodeMap.set(n.id, n));

                const newEdges = neighborhood.edges.filter(e =>
                    !existingEdgeKeys.has(`${e.source}-${e.target}`)
                );

                return {
                    nodes: Array.from(nodeMap.values()),
                    edges: [...prev.edges, ...newEdges]
                };
            });
            toast.success(`Expanded ${node.label}`);
            setCameraFocusNode(node.id); // Also focus on clicked node
        } catch (error) {
            console.error(error);
            toast.error("Failed to expand node");
        }
    };

    // Handle mode changes - process merge selections when switching back to view
    const handleModeChange = async (newMode: GraphMode) => {
        // If leaving merge mode with multiple selections, create pending merge
        if (graphMode === 'merge' && newMode !== 'merge' && selectedNodes.length >= 2) {
            const [target, ...sources] = selectedNodes;
            try {
                await graphHistoryApi.create({
                    action_type: 'merge',
                    payload: {
                        target_id: target.id,
                        source_ids: sources.map(n => n.id)
                    },
                    source_view: 'global'
                });
                toast.success(`Queued merge: ${sources.length} nodes → "${target.label}"`, {
                    description: 'Open History to review and apply'
                });
                queryClient.invalidateQueries({ queryKey: ['graph-history-pending-count'] });
                queryClient.invalidateQueries({ queryKey: ['graph-history'] });
            } catch (error) {
                console.error(error);
                toast.error('Failed to queue merge action');
            }
        }

        // Reset selections when changing modes
        setSelectedNodes([]);
        setHighlightedNodes([]);
        setGraphMode(newMode);
    };

    const handleClear = useCallback(async () => {
        setHasSearched(false);
        setIsInputFocused(false);
        setHighlightedNodes([]);
        setCameraFocusNode(null);
        // Reload top nodes
        const nodes = await graphEditorApi.getTopNodes(15);
        setGraphData({ nodes, edges: [] });
    }, []);

    return (
        <div className="relative w-full h-full min-h-[calc(100vh-4rem)] bg-[#110c0a] overflow-hidden group/page">

            {/* 3D Graph Container - Click to enter explore mode */}
            <div
                className={`absolute inset-0 transition-all duration-1000 ease-in-out ${isInteractive ? 'blur-0' : 'blur-sm grayscale-[0.8] brightness-[0.4]'} cursor-pointer`}
                onClick={() => !isInteractive && setIsExploring(true)}
            >
                <ThreeGraph
                    nodes={graphData.nodes}
                    edges={graphData.edges}
                    onNodeClick={handleNodeClick}
                    highlightedNodeIds={highlightedNodes}
                    zoomToNodeId={cameraFocusNode}
                />
            </div>

            {/* Overlay Gradient: only present when NOT interactive to help text legibility */}
            {!isInteractive && (
                <div
                    className="absolute inset-0 bg-gradient-to-t from-[#110c0a] via-transparent to-transparent pointer-events-none"
                    style={{ background: 'radial-gradient(circle at center, transparent 0%, #110c0a 120%)' }}
                />
            )}

            {/* UI Layer */}
            <div className="absolute inset-0 z-10 pointer-events-none flex flex-col items-center">

                {/* Toolbar - Only visible when interacting */}
                {isInteractive && (
                    <div className="absolute top-4 left-4 pointer-events-auto animate-in fade-in zoom-in duration-300">
                        <GraphToolbar
                            mode={graphMode}
                            onModeChange={handleModeChange}
                            onHistoryClick={() => setShowHistoryModal(true)}
                            pendingCount={pendingCount}
                        />
                    </div>
                )}

                {/* Search Container */}
                <motion.div
                    initial={{ top: "40%" }}
                    animate={{
                        top: isInteractive || isInputFocused ? "4%" : "40%",
                        scale: isInteractive ? 0.9 : 1
                    }}
                    transition={{ type: "spring", stiffness: 100, damping: 20 }}
                    className="absolute w-full flex flex-col items-center pointer-events-auto px-4"
                >
                    <div className="mb-6 text-center space-y-2 select-none">
                        <motion.h1
                            animate={{ opacity: isInteractive ? 0 : 1, y: isInteractive ? -20 : 0, height: isInteractive ? 0 : 'auto' }}
                            className="text-5xl font-bold tracking-tighter text-white drop-shadow-2xl font-display"
                            style={{ textShadow: '0 4px 20px rgba(0,0,0,0.8)' }}
                        >
                            Global Graph Explorer
                        </motion.h1>
                        <motion.p
                            animate={{ opacity: isInteractive ? 0 : 1, height: isInteractive ? 0 : 'auto' }}
                            className="text-zinc-400 text-lg max-w-md mx-auto font-medium"
                        >
                            Navigate the entire knowledge base. <br />
                            <span className="text-zinc-500 text-sm">Type to search or click background to explore.</span>
                        </motion.p>
                    </div>

                    <GraphSearchInput
                        onSearch={handleSearch}
                        onClear={handleClear}
                        onFocusChange={setIsInputFocused}
                        isSearching={isLoading}
                        className="shadow-2xl"
                    />
                </motion.div>

                {/* Loading State Overlay */}
                {isLoading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/40 backdrop-blur-sm z-50">
                        <div className="flex flex-col items-center gap-4 p-6 rounded-2xl bg-surface-900 border border-amber-500/20 shadow-xl">
                            <Loader2 className="w-10 h-10 text-amber-500 animate-spin" />
                            <p className="text-sm font-medium text-muted-foreground animate-pulse">Exploring connections...</p>
                        </div>
                    </div>
                )}
            </div>

            {/* Stats / Legend Bottom Right */}
            {isInteractive && (
                <motion.div
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="absolute bottom-8 right-8 pointer-events-auto"
                >
                    <div className="p-4 rounded-xl bg-surface-950/80 backdrop-blur-md border border-white/10 shadow-xl">
                        <div className="text-xs text-muted-foreground space-y-1">
                            <p>Nodes: <span className="text-amber-500 font-mono">{graphData.nodes.length}</span></p>
                            <p>Edges: <span className="text-amber-500 font-mono">{graphData.edges.length}</span></p>
                        </div>
                    </div>
                </motion.div>
            )}

            {/* History Modal */}
            <GraphHistoryModal
                isOpen={showHistoryModal}
                onClose={() => setShowHistoryModal(false)}
                onActionComplete={() => {
                    // Reload graph data when an action is applied/undone
                    graphEditorApi.getTopNodes(15).then(nodes => {
                        setGraphData({ nodes, edges: [] });
                    });
                }}
            />
        </div>
    );
}
