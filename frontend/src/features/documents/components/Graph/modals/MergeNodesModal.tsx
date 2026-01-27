import React, { useState } from 'react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Loader2, GitMerge } from 'lucide-react';
import { graphEditorApi } from '@/lib/api-client';
import { GraphNode } from '@/types/graph';
import { toast } from 'sonner';

interface MergeNodesModalProps {
    isOpen: boolean;
    onClose: () => void;
    nodes: GraphNode[];
    onMergeComplete: () => void;
}

export const MergeNodesModal: React.FC<MergeNodesModalProps> = ({
    isOpen,
    onClose,
    nodes,
    onMergeComplete
}) => {
    const [targetId, setTargetId] = useState<string>(nodes[0]?.id || "");
    const [loading, setLoading] = useState(false);

    if (nodes.length < 2) return null;

    const handleMerge = async () => {
        if (!targetId) return;

        setLoading(true);
        const sourceIds = nodes.filter(n => n.id !== targetId).map(n => n.id);

        try {
            await graphEditorApi.merge({
                target_id: targetId,
                source_ids: sourceIds
            });
            toast.success("Nodes merged successfully");
            onMergeComplete();
            onClose();
        } catch (error) {
            console.error(error);
            toast.error("Failed to merge nodes");
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="sm:max-w-md p-0 gap-0 overflow-hidden border-border shadow-2xl">
                <DialogHeader className="p-6 border-b border-white/5 bg-foreground/[0.02]">
                    <DialogTitle className="flex items-center gap-2">
                        <GitMerge className="h-5 w-5 text-primary" />
                        Merge Nodes
                    </DialogTitle>
                    <DialogDescription>
                        Select the primary node to keep. Other nodes will be merged into it, transferring all relationships.
                    </DialogDescription>
                </DialogHeader>

                <div className="p-6 space-y-3">
                    {/* Native Radio Group Replacement */}
                    {nodes.map(node => (
                        <div key={node.id} className="flex items-center space-x-2 p-2 rounded hover:bg-muted/50 cursor-pointer" onClick={() => setTargetId(node.id)}>
                            <input
                                type="radio"
                                id={node.id}
                                name="targetNode"
                                checked={node.id === targetId}
                                onChange={() => setTargetId(node.id)}
                                className="accent-primary h-4 w-4"
                            />
                            <div className="flex-1 cursor-pointer">
                                <div className="font-medium text-foreground">{node.label}</div>
                                <div className="text-xs text-muted-foreground flex items-center gap-2">
                                    <span>Type: {node.type || 'Unknown'}</span>
                                    <span>•</span>
                                    <span>Degree: {node.degree || 0}</span>
                                </div>
                            </div>
                            {node.id === targetId && (
                                <span className="text-[10px] bg-primary text-primary-foreground px-1.5 py-0.5 rounded font-bold">Target</span>
                            )}
                        </div>
                    ))}
                </div>


                <DialogFooter className="gap-2 sm:gap-0 p-4 bg-muted/5 border-t border-white/5">
                    <div className="text-[10px] text-muted-foreground flex-1 flex items-center">
                        {nodes.length - 1} node(s) will be deleted.
                    </div>
                    <Button variant="ghost" onClick={onClose} disabled={loading} className="hover:bg-foreground/5">Cancel</Button>
                    <Button onClick={handleMerge} disabled={loading || !targetId}>
                        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                        Merge
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
