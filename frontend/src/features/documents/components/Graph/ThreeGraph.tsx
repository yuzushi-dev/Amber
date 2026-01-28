import React, { useCallback, useMemo, useRef, useState, useEffect } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import * as THREE from 'three';
import { GraphEdge, GraphNode } from '@/types/graph';

interface ThreeGraphProps {
    nodes: GraphNode[];
    edges: GraphEdge[];
    onNodeClick?: (node: GraphNode) => void;
    highlightedNodeIds?: string[];
    zoomToNodeId?: string | null;
}

// Transform nodes/edges to force-graph format
interface ForceGraphNode {
    id: string;
    label: string;
    color: string;
    community_id?: number | null;
    type?: string | null;
    degree?: number;
    val: number;
    x?: number;
    y?: number;
    z?: number;
    isHighlighted?: boolean;
}

interface ForceGraphLink {
    source: string;
    target: string;
    weight: number;
    type?: string | null;
}

interface GraphData {
    nodes: ForceGraphNode[];
    links: ForceGraphLink[];
}

export default function ThreeGraph({
    nodes,
    edges,
    onNodeClick,
    highlightedNodeIds = [],
    zoomToNodeId
}: ThreeGraphProps) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- ForceGraph3D ref type is complex
    const fgRef = useRef<any>(null);
    const [hoveredNode, setHoveredNode] = useState<string | null>(null);

    const buildTheme = () => {
        const fallbackDark = 'hsl(0 0% 0%)';
        const fallbackLight = 'hsl(0 0% 100%)';
        if (typeof document === 'undefined') {
            return {
                background: fallbackDark,
                foreground: fallbackLight,
                nodes: {
                    entity: fallbackLight,
                    document: fallbackLight,
                    chunk: fallbackLight,
                    community: fallbackLight,
                    relationship: fallbackLight,
                },
                edges: {
                    default: fallbackLight,
                    highlight: fallbackLight,
                },
                communityColors: [fallbackLight, fallbackLight, fallbackLight, fallbackLight, fallbackLight],
            };
        }

        const style = getComputedStyle(document.documentElement);
        const readVar = (name: string, fallback: string) => {
            const value = style.getPropertyValue(name).trim();
            // Fix: THREE.Color doesn't parse space-separated HSL (CSS Color Level 4) well
            // Convert "38 100% 50%" -> "38, 100%, 50%"
            return value ? `hsl(${value.replace(/ /g, ', ')})` : fallback;
        };

        const background = readVar('--surface-950', fallbackDark);
        const foreground = readVar('--foreground', fallbackLight);

        return {
            background,
            foreground,
            nodes: {
                entity: readVar('--node-entity', foreground),
                document: readVar('--node-document', foreground),
                chunk: readVar('--node-chunk', foreground),
                community: readVar('--node-community', foreground),
                relationship: readVar('--node-relationship', foreground),
            },
            edges: {
                default: readVar('--edge-default', foreground),
                highlight: readVar('--edge-highlight', foreground),
            },
            communityColors: [
                readVar('--chart-1', foreground),
                readVar('--chart-2', foreground),
                readVar('--chart-3', foreground),
                readVar('--chart-4', foreground),
                readVar('--chart-5', foreground),
            ],
        };
    };

    const [theme, setTheme] = useState(buildTheme);

    useEffect(() => {
        setTheme(buildTheme());
    }, []);

    const getCommunityColor = useCallback((communityId?: number | null): string => {
        if (communityId === undefined || communityId === null) return theme.edges.default;
        const idNum = Number(communityId);
        if (!Number.isFinite(idNum)) return theme.edges.default;
        const idx = Math.abs(Math.trunc(idNum)) % theme.communityColors.length;
        return theme.communityColors[idx] || theme.edges.default;
    }, [theme]);


    // Transform data for force-graph-3d
    const graphData = useMemo<GraphData>(() => {
        const nodeMap = new Map(nodes.map(n => [n.id, n]));
        const highlightSet = new Set(highlightedNodeIds);

        return {
            nodes: nodes.map(node => {
                let color = theme.nodes.entity;
                if (node.type === 'Document') color = theme.nodes.document;
                else if (node.type === 'Chunk') color = theme.nodes.chunk;
                else if (node.community_id !== undefined && node.community_id !== null) {
                    color = getCommunityColor(node.community_id);
                }

                return {
                    id: node.id,
                    label: node.label,
                    color: color,
                    community_id: node.community_id,
                    type: node.type,
                    degree: node.degree,
                    val: Math.max(1, (node.degree || 1) * 2),
                    isHighlighted: highlightSet.has(node.id)
                };
            }),
            links: edges
                .filter(e => nodeMap.has(e.source) && nodeMap.has(e.target))
                .map(edge => ({
                    source: edge.source,
                    target: edge.target,
                    weight: edge.weight || 1,
                    type: edge.type,
                })),
        };
    }, [nodes, edges, highlightedNodeIds, theme, getCommunityColor]);

    // Zoom effect when zoomToNodeId changes
    React.useEffect(() => {
        if (zoomToNodeId && fgRef.current) {
            // Find the node object in the internal graph structure or current data
            // We need coords which are populated by the force engine
            // Wait a tick for graph to possibly settle if node is new?
            // Actually, we can just look it up in graphData, but coords (x,y,z) are mutable on the object
            // The graphData array objects ARE the d3 objects.

            const node = graphData.nodes.find(n => n.id === zoomToNodeId);
            if (node && typeof node.x === 'number' && typeof node.y === 'number' && typeof node.z === 'number') {
                const distance = 150;
                const distRatio = 1 + distance / Math.hypot(node.x, node.y, node.z);

                fgRef.current.cameraPosition(
                    { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
                    node, // lookAt
                    2000  // Transition duration (ms)
                );
            }
        }
    }, [zoomToNodeId, graphData]);

    const containerRef = useRef<HTMLDivElement>(null);
    const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

    // Handle container resize
    useEffect(() => {
        if (!containerRef.current) return;

        const updateDimensions = () => {
            if (containerRef.current) {
                setDimensions({
                    width: containerRef.current.clientWidth,
                    height: containerRef.current.clientHeight
                });
            }
        };

        const resizeObserver = new ResizeObserver(() => {
            // using requestAnimationFrame to throttle and avoid loop limit errors
            requestAnimationFrame(updateDimensions);
        });

        resizeObserver.observe(containerRef.current);
        updateDimensions(); // Initial size

        return () => resizeObserver.disconnect();
    }, [theme]);

    // Handle node click
    const handleNodeClick = useCallback((node: ForceGraphNode) => {
        if (onNodeClick) {
            onNodeClick({
                id: node.id,
                label: node.label,
                type: node.type,
                community_id: node.community_id,
                degree: node.degree,
            });
        }

        // Zoom to node with smooth animation
        if (fgRef.current && node.x !== undefined && node.y !== undefined && node.z !== undefined) {
            const distance = 150;
            const distRatio = 1 + distance / Math.hypot(node.x, node.y, node.z);

            fgRef.current.cameraPosition(
                { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
                node,
                1000
            );
        }
    }, [onNodeClick]);

    // Custom node rendering with premium glass-like glow effect
    const nodeThreeObject = useCallback((node: ForceGraphNode) => {
        const group = new THREE.Group();
        const baseSize = node.val || 4;

        // Core sphere with premium metallic effect
        const geometry = new THREE.SphereGeometry(baseSize, 32, 32);
        const color = new THREE.Color(node.color);

        // Use MeshStandardMaterial for better lighting response
        const coreMaterial = new THREE.MeshStandardMaterial({
            color: color,
            metalness: 0.4,
            roughness: 0.3,
            emissive: color,
            emissiveIntensity: 0.2,
        });

        const sphere = new THREE.Mesh(geometry, coreMaterial);
        group.add(sphere);

        // Inner glow layer
        const innerGlowGeometry = new THREE.SphereGeometry(baseSize * 1.2, 24, 24);
        const innerGlowMaterial = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: 0.15,
            side: THREE.BackSide,
        });
        const innerGlow = new THREE.Mesh(innerGlowGeometry, innerGlowMaterial);
        group.add(innerGlow);

        // Outer glow layer for depth
        const outerGlowGeometry = new THREE.SphereGeometry(baseSize * 1.8, 16, 16);
        const outerGlowMaterial = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: 0.05,
            side: THREE.BackSide,
        });
        const outerGlow = new THREE.Mesh(outerGlowGeometry, outerGlowMaterial);
        group.add(outerGlow);

        // Create text sprite for label with improved styling
        const label = node.label || node.id;
        const fontSize = 48;
        const fontFamily = "'Inter', 'Noto Sans', sans-serif";

        // Measure text to dynamically size canvas
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d')!;
        ctx.font = `600 ${fontSize}px ${fontFamily}`;
        const textMetrics = ctx.measureText(label);

        const textWidth = textMetrics.width;
        const padding = 40; // Horizontal padding
        const canvasWidth = Math.ceil(textWidth + padding * 2);
        const canvasHeight = 90; // Fixed height sufficient for font size + outline

        canvas.width = canvasWidth;
        canvas.height = canvasHeight;

        // Text outline for better readability
        ctx.font = `600 ${fontSize}px ${fontFamily}`;
        ctx.strokeStyle = theme.background;
        ctx.lineWidth = 4;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.strokeText(label, canvas.width / 2, canvas.height / 2);

        // Main text
        ctx.fillStyle = theme.foreground;
        ctx.fillText(label, canvas.width / 2, canvas.height / 2);

        const texture = new THREE.CanvasTexture(canvas);
        const spriteMaterial = new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            depthTest: false,
        });
        const sprite = new THREE.Sprite(spriteMaterial);

        // Scale sprite based on aspect ratio to prevent distortion
        // Base height scale is 8 units, width scales proportionally
        const baseHeight = 8;
        const aspectRatio = canvasWidth / canvasHeight;
        sprite.scale.set(baseHeight * aspectRatio, baseHeight, 1);
        sprite.position.y = -baseSize - 10;

        group.add(sprite);

        return group;
    }, []);

    return (
        <div
            ref={containerRef}
            className="relative w-full h-full min-h-[500px] rounded-lg overflow-hidden"
            style={{ backgroundColor: theme.background }}
        >
            {/* 3D Graph - Only render if we have dimensions to avoid full-screen default */}
            {dimensions.width > 0 && dimensions.height > 0 && (
                <ForceGraph3D
                    ref={fgRef}
                    width={dimensions.width}
                    height={dimensions.height}
                    graphData={graphData}
                    nodeLabel=""
                    nodeThreeObject={nodeThreeObject}
                    nodeThreeObjectExtend={false}
                    linkOpacity={0.3}
                    linkWidth={1}
                    linkColor={() => theme.edges.default}
                    backgroundColor={theme.background}
                    showNavInfo={false}
                    onNodeClick={handleNodeClick}
                    onNodeHover={(node: ForceGraphNode | null) => setHoveredNode(node?.id || null)}
                    d3AlphaDecay={0.02}
                    d3VelocityDecay={0.3}
                    warmupTicks={100}
                    cooldownTicks={0}
                />
            )}

            {/* Hovered node tooltip */}
            {hoveredNode && (
                <div className="absolute top-4 right-4 z-10 max-w-xs">
                    <div className="px-3 py-2 rounded-lg bg-surface-950/80 border border-[var(--primary)] backdrop-blur-sm shadow-glow-sm">
                        <p className="text-sm font-medium text-foreground">{hoveredNode}</p>
                    </div>
                </div>
            )}
        </div>
    );
}
