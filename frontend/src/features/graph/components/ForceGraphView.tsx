
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

// Get colors from CSS custom properties (design system tokens)
const getNodeColor = (type: string): string => {
    const root = document.documentElement;
    const style = getComputedStyle(root);

    switch (type) {
        case 'entity':
            return `hsl(${style.getPropertyValue('--node-entity').trim()})`;
        case 'document':
            return `hsl(${style.getPropertyValue('--node-document').trim()})`;
        case 'community':
            return `hsl(${style.getPropertyValue('--node-community').trim()})`;
        case 'chunk':
            return `hsl(${style.getPropertyValue('--node-chunk').trim()})`;
        default:
            return `hsl(${style.getPropertyValue('--muted-foreground').trim()})`;
    }
};

const ForceGraphView: React.FC<ForceGraphViewProps> = ({
    data,
    mode = '3d',
    onNodeClick,
    width,
    height
}) => {
    const { graphRef } = useGraphForce();
    const { theme } = useTheme(); // To adjust background color

    const isDark = theme === 'dark';
    const backgroundColor = isDark ? '#020817' : '#ffffff'; // Match shadcn ui background
    const linkColor = isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)';

    const processedData = useMemo(() => {
        return {
            nodes: data.nodes.map(node => ({
                ...node,
                color: node.color || getNodeColor(node.group)
            })),
            links: data.links
        };
    }, [data]);

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
