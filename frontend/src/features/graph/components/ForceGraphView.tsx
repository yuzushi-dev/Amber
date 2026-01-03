
import React, { useMemo } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import ForceGraph3D from 'react-force-graph-3d';
import { useGraphForce } from '../hooks/useGraphForce';
import { useTheme } from 'next-themes'; // Note: Assuming next-themes or similar provider is available, otherwise generic CSS variable usage

interface GraphNode {
    id: string;
    group: 'document' | 'entity' | 'community';
    val: number; // size
    name: string;
    color?: string;
}

interface GraphLink {
    source: string;
    target: string;
    width?: number;
}

interface ForceGraphViewProps {
    data: {
        nodes: GraphNode[];
        links: GraphLink[];
    };
    mode?: '2d' | '3d';
    onNodeClick?: (node: any) => void;
    width?: number;
    height?: number;
}

const ForceGraphView: React.FC<ForceGraphViewProps> = ({
    data,
    mode = '3d',
    onNodeClick,
    width,
    height
}) => {
    const { graphRef } = useGraphForce();
    const { theme, resolvedTheme } = useTheme(); // To adjust background color

    const activeTheme = resolvedTheme || theme;
    const prefersDark = typeof window !== 'undefined'
        && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark = activeTheme === 'dark' || (activeTheme !== 'light' && prefersDark);
    const backgroundColor = isDark ? '#020817' : '#ffffff'; // Match shadcn ui background
    const linkColor = isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)';

    const processedData = useMemo(() => {
        const defaultColors = {
            entity: isDark ? '#60a5fa' : '#2563eb',
            document: isDark ? '#f59e0b' : '#d97706',
            community: isDark ? '#10b981' : '#059669',
            chunk: isDark ? '#a855f7' : '#7c3aed',
            default: isDark ? '#94a3b8' : '#64748b',
        };

        const getColorMap = () => {
            if (typeof document === 'undefined') {
                return defaultColors;
            }

            const style = getComputedStyle(document.documentElement);
            const readVar = (name: string, fallback: string) => {
                const value = style.getPropertyValue(name).trim();
                return value ? `hsl(${value})` : fallback;
            };

            return {
                entity: readVar('--node-entity', defaultColors.entity),
                document: readVar('--node-document', defaultColors.document),
                community: readVar('--node-community', defaultColors.community),
                chunk: readVar('--node-chunk', defaultColors.chunk),
                default: readVar('--muted-foreground', defaultColors.default),
            };
        };

        const colorMap = getColorMap();

        return {
            nodes: data.nodes.map(node => ({
                ...node,
                color: node.color || colorMap[node.group] || colorMap.default
            })),
            links: data.links
        };
    }, [data, isDark, theme, resolvedTheme]);

    const commonProps = {
        graphData: processedData,
        nodeLabel: 'name',
        nodeColor: 'color',
        onNodeClick: onNodeClick,
        width: width,
        height: height,
        backgroundColor: backgroundColor,
        linkColor: () => linkColor,
    };

    if (mode === '2d') {
        return (
            <ForceGraph2D
                ref={graphRef as any}
                {...commonProps}
                nodeRelSize={6}
                linkDirectionalArrowLength={3.5}
                linkDirectionalArrowRelPos={1}
            />
        );
    }

    return (
        <ForceGraph3D
            ref={graphRef as any}
            {...commonProps}
            nodeOpacity={0.9}
            linkOpacity={0.3}
            linkDirectionalArrowLength={3.5}
            linkDirectionalArrowRelPos={1}
            nodeResolution={16}
        />
    );
};

export default ForceGraphView;
