import React from 'react';
import { X, Network, Wand2, Hash, Layers } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
// import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';

import { GraphNode } from '@/types/graph';

interface NodeSidebarProps {
    node: GraphNode | null;
    onClose: () => void;
    onHeal: (nodeId: string) => void;
}

export const NodeSidebar: React.FC<NodeSidebarProps> = ({
    node,
    onClose,
    onHeal
}) => {
    if (!node) return null;

    return (
        <div className="absolute top-0 right-0 h-full w-80 bg-background/95 backdrop-blur-md border-l shadow-xl z-20 flex flex-col transition-transform duration-300 ease-in-out">
            {/* Header */}
            <div className="p-4 border-b flex items-start justify-between bg-muted/20">
                <div className="space-y-1">
                    <h3 className="font-semibold text-lg leading-tight break-words">{node.label}</h3>
                    <Badge variant="outline" className="text-xs font-normal">
                        {node.type || 'Entity'}
                    </Badge>
                </div>
                <Button variant="ghost" size="icon" className="h-8 w-8 -mr-2 -mt-2" onClick={onClose}>
                    <X className="h-4 w-4" />
                </Button>
            </div>

            <ScrollArea className="flex-1">
                <div className="p-4 space-y-6">
                    {/* Stats Grid */}
                    <div className="grid grid-cols-2 gap-3">
                        <div className="p-3 rounded-lg bg-card border flex flex-col items-center justify-center gap-1 text-center">
                            <Network className="h-4 w-4 text-primary mb-1" />
                            <span className="text-2xl font-bold">{node.degree || 0}</span>
                            <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Connections</span>
                        </div>
                        <div className="p-3 rounded-lg bg-card border flex flex-col items-center justify-center gap-1 text-center">
                            <Hash className="h-4 w-4 text-primary mb-1" />
                            <span className="text-2xl font-bold">{node.community_id ?? '-'}</span>
                            <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Community</span>
                        </div>
                    </div>

                    <div className="h-px bg-border my-4" />

                    {/* Description */}
                    <div className="space-y-2">
                        <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                            <Layers className="h-4 w-4" />
                            Description
                        </div>
                        <p className="text-sm text-foreground/90 leading-relaxed min-h-[4rem]">
                            {node.description || "No description available for this entity."}
                        </p>
                    </div>

                    <div className="h-px bg-border my-4" />
                </div>

            </ScrollArea>

            {/* Footer Actions */}
            <div className="p-4 border-t bg-muted/20 space-y-2">
                <Button
                    className="w-full gap-2"
                    variant="default"
                    onClick={() => onHeal(node.id)}
                >
                    <Wand2 className="h-4 w-4" />
                    Heal / Suggest Connections
                </Button>
            </div>
        </div>
    );
};
