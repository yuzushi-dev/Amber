
import React, { useState, useEffect } from 'react';
import ForceGraphView from '../../graph/components/ForceGraphView';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Box, Layers } from 'lucide-react';

// Mock data generator for demonstration
interface GraphNode {
    id: string
    group: 'document' | 'entity' | 'community'
    val: number
    name: string
}

interface GraphLink {
    source: string
    target: string
}

interface GraphData {
    nodes: GraphNode[]
    links: GraphLink[]
}

const generateMockData = (count = 20): GraphData => {
    const nodes: GraphNode[] = [];
    const links: GraphLink[] = [];

    // Query Node
    nodes.push({ id: '0', group: 'document', val: 20, name: 'Query Context' });

    for (let i = 1; i <= count; i++) {
        const group = (Math.random() > 0.7 ? 'document' : 'entity') as 'document' | 'entity';
        nodes.push({
            id: String(i),
            group: group,
            val: group === 'document' ? 10 : 5,
            name: `${group === 'document' ? 'Doc' : 'Entity'} ${i}`
        });

        // Link to query
        if (Math.random() > 0.5) {
            links.push({ source: '0', target: String(i) });
        }

        // Random link
        if (i > 1 && Math.random() > 0.7) {
            links.push({ source: String(i), target: String(Math.floor(Math.random() * i)) });
        }
    }
    return { nodes, links };
};

const EntityGraph: React.FC = () => {
    const [mode, setMode] = useState<'2d' | '3d'>('3d');
    const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
    // TODO: Fetch real data

    useEffect(() => {
        // Load mock data on mount
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setData(generateMockData(30));
    }, []);

    const toggleMode = () => {
        setMode(prev => prev === '2d' ? '3d' : '2d');
    };

    return (
        <Card className="h-full w-full overflow-hidden relative border-0 shadow-none bg-[hsl(var(--surface-950))]">
            <div className="absolute top-4 right-4 z-10 flex gap-2">
                <Button
                    variant="secondary"
                    size="sm"
                    onClick={toggleMode}
                    className="bg-background/80 backdrop-blur-sm shadow-sm"
                >
                    {mode === '2d' ? <Box className="w-4 h-4 mr-2" /> : <Layers className="w-4 h-4 mr-2" />}
                    {mode === '2d' ? 'Switch to 3D' : 'Switch to 2D'}
                </Button>
            </div>

            <div className="h-full w-full">
                <ForceGraphView
                    data={data}
                    mode={mode}
                    onNodeClick={(node: GraphNode) => console.log('Clicked:', node)}
                />
            </div>
        </Card>
    );
};

export default EntityGraph;
