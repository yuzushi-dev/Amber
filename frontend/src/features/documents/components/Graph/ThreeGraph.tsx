import { useCallback, useMemo, useRef, useState } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import * as THREE from 'three';
import { GraphEdge, GraphNode } from '@/types/graph';

// Amber Theme Colors derived from globals.css
const THEME = {
    background: '#110c0a', // hsl(32, 10%, 7%) -> converted to hex for Three.js
    primary: '#ff9d00',    // hsl(38, 100%, 50%)
    nodes: {
        entity: '#ffaa00',      // hsl(40, 100%, 50%)
        document: '#5296fa',    // hsl(217, 91%, 60%)
        chunk: '#22c55e',       // hsl(142, 71%, 45%)
        community: '#a855f7',   // hsl(280, 70%, 55%)
        relationship: '#ff7f50' // hsl(18, 100%, 64%)
    },
    edges: {
        default: '#565666',   // hsl(240, 9%, 35%)
        highlight: '#ffd580'  // hsl(40, 100%, 65%)
    }
};

// Community colors mapped to Amber palette variants
// We want specific types to predictable colors if possible
const COMMUNITY_COLORS = [
    '#ff9d00', // amber-500 (Default/Primary)
    '#f97316', // orange-500
    '#06b6d4', // cyan-500 (Tech/System)
    '#8b5cf6', // violet-500 (Person/Role)
    '#10b981', // emerald-500 (Location/Geo)
    '#3b82f6', // blue-500 (Organization)
    '#ec4899', // pink-500 (Event)
    '#ef4444', // red-500 (Critical)
];

function getCommunityColor(communityId?: number | null): string {
    if (communityId === undefined || communityId === null) return THEME.edges.default;
    const idNum = Number(communityId);
    if (!Number.isFinite(idNum)) return THEME.edges.default;

    // For now we rely on the hash to distribute across these colors
    // In the future we can add a explicit map like { "PERSON_HASH": VIOLET } if needed
    const idx = Math.abs(Math.trunc(idNum)) % COMMUNITY_COLORS.length;
    return COMMUNITY_COLORS[idx];
}

interface ThreeGraphProps {
    nodes: GraphNode[];
    edges: GraphEdge[];
    onNodeClick?: (node: GraphNode) => void;
}

// Transform nodes/edges to force-graph format
interface GraphData {
    nodes: Array<{
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
    }>;
    links: Array<{
        source: string;
        target: string;
        weight: number;
        type?: string | null;
    }>;
}

export default function ThreeGraph({ nodes, edges, onNodeClick }: ThreeGraphProps) {
    const fgRef = useRef<any>(null);
    const [hoveredNode, setHoveredNode] = useState<string | null>(null);


    // Transform data for force-graph-3d
    const graphData = useMemo<GraphData>(() => {
        const nodeMap = new Map(nodes.map(n => [n.id, n]));

        return {
            nodes: nodes.map(node => {
                let color = THEME.nodes.entity;
                if (node.type === 'Document') color = THEME.nodes.document;
                else if (node.type === 'Chunk') color = THEME.nodes.chunk;
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
    }, [nodes, edges]);

    // Handle node click
    const handleNodeClick = useCallback((node: any) => {
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
        if (fgRef.current) {
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
    const nodeThreeObject = useCallback((node: any) => {
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
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d')!;
        const fontSize = 48;
        const label = node.label || node.id;

        canvas.width = 512;
        canvas.height = 72;

        // Text outline for better readability
        ctx.font = `600 ${fontSize}px 'Inter', 'Noto Sans', sans-serif`;
        ctx.strokeStyle = '#000000';
        ctx.lineWidth = 4;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.strokeText(label.substring(0, 30), canvas.width / 2, canvas.height / 2);

        // Main text
        ctx.fillStyle = '#f8fafc'; // slate-50 (bright text)
        ctx.fillText(label.substring(0, 30), canvas.width / 2, canvas.height / 2);

        const texture = new THREE.CanvasTexture(canvas);
        const spriteMaterial = new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            depthTest: false,
        });
        const sprite = new THREE.Sprite(spriteMaterial);
        sprite.scale.set(45, 6, 1);
        sprite.position.y = -baseSize - 8;

        group.add(sprite);

        return group;
    }, []);

    return (
        <div className="relative w-full h-full min-h-[500px] rounded-lg overflow-hidden" style={{ backgroundColor: THEME.background }}>
            {/* 3D Graph */}
            <ForceGraph3D
                ref={fgRef}
                graphData={graphData}
                nodeLabel=""
                nodeThreeObject={nodeThreeObject}
                nodeThreeObjectExtend={false}
                linkOpacity={0.3}
                linkWidth={1}
                linkColor={() => THEME.edges.default}
                backgroundColor={THEME.background}
                showNavInfo={false}
                onNodeClick={handleNodeClick}
                onNodeHover={(node) => setHoveredNode(node?.id || null)}
                d3AlphaDecay={0.02}
                d3VelocityDecay={0.3}
                warmupTicks={100}
                cooldownTicks={0}
            />

            {/* Hovered node tooltip */}
            {hoveredNode && (
                <div className="absolute top-4 right-4 z-10 max-w-xs">
                    <div className="px-3 py-2 rounded-lg bg-black/80 border border-[var(--primary)] backdrop-blur-sm shadow-glow-sm">
                        <p className="text-sm font-medium text-white">{hoveredNode}</p>
                    </div>
                </div>
            )}
        </div>
    );
}
