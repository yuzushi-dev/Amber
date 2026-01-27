
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
    onNodeClick?: (node: GraphNode) => void;
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
    const style = typeof document !== 'undefined'
        ? getComputedStyle(document.documentElement)
        : null;
    const readVar = (name: string, fallback: string) => {
        if (!style) return fallback;
        const value = style.getPropertyValue(name).trim();
        return value ? `hsl(${value})` : fallback;
    };
    const readVarAlpha = (name: string, alpha: number, fallback: string) => {
        if (!style) return fallback;
        const value = style.getPropertyValue(name).trim();
        return value ? `hsl(${value} / ${alpha})` : fallback;
    };
    const backgroundColor = readVar('--background', isDark ? 'hsl(0 0% 0%)' : 'hsl(0 0% 100%)');
    const linkColor = readVarAlpha('--edge-default', 0.2, isDark ? 'hsl(0 0% 100% / 0.2)' : 'hsl(0 0% 0% / 0.2)');

    const processedData = useMemo(() => {
        const fallbackColor = isDark ? 'hsl(0 0% 100%)' : 'hsl(0 0% 0%)';
        const defaultColors = {
            entity: fallbackColor,
            document: fallbackColor,
            community: fallbackColor,
            chunk: fallbackColor,
            default: fallbackColor,
        };

        const colorMap = {
            entity: readVar('--node-entity', defaultColors.entity),
            document: readVar('--node-document', defaultColors.document),
            community: readVar('--node-community', defaultColors.community),
            chunk: readVar('--node-chunk', defaultColors.chunk),
            default: readVar('--muted-foreground', defaultColors.default),
        };

        return {
            nodes: data.nodes.map(node => ({
                ...node,
                color: node.color || colorMap[node.group] || colorMap.default
            })),
            links: data.links
        };
    }, [data, isDark]);

    const commonProps = {
        graphData: processedData,
        nodeLabel: 'name',
        nodeColor: 'color',
        onNodeClick: onNodeClick as any,
        width: width,
        height: height,
        backgroundColor: backgroundColor,
        linkColor: () => linkColor,
    };

    if (mode === '2d') {
        return (
            <ForceGraph2D
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
