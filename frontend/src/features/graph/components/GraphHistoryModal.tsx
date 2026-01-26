import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
} from '@/components/ui/dialog';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import {
    Network,
    GitMerge,
    Scissors,
    Wand2,
    Trash2,
    Check,
    X,
    Undo2,
    Loader2,
    Clock,
    RotateCcw,
} from 'lucide-react';
import { graphHistoryApi, GraphEditHistory } from '@/lib/api-client';
import { toast } from 'sonner';
import { formatDistanceToNow } from 'date-fns';

interface GraphHistoryModalProps {
    isOpen: boolean;
    onClose: () => void;
    onActionComplete?: () => void;
}

const ACTION_ICONS: Record<GraphEditHistory['action_type'], React.ElementType> = {
    connect: Network,
    merge: GitMerge,
    prune: Scissors,
    heal: Wand2,
    delete_edge: Trash2,
    delete_node: Trash2,
};

const STATUS_STYLES: Record<GraphEditHistory['status'], { variant: 'default' | 'secondary' | 'destructive' | 'outline'; className: string }> = {
    pending: { variant: 'default', className: 'bg-amber-500/20 text-amber-400 border-amber-500/30 animate-pulse' },
    applied: { variant: 'secondary', className: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' },
    rejected: { variant: 'outline', className: 'bg-red-500/10 text-red-400/60 border-red-500/20' },
    undone: { variant: 'outline', className: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20' },
};

function formatPayloadDetails(actionType: string, payload: Record<string, unknown>): string {
    switch (actionType) {
        case 'connect':
            return `${payload.source} ↔ ${payload.target}`;
        case 'merge':
            const sources = (payload.source_ids as string[]) || [];
            return `${sources.join(', ')} → ${payload.target_id}`;
        case 'delete_edge':
            return `${payload.source} ↛ ${payload.target}`;
        case 'delete_node':
        case 'prune':
            return payload.node_id as string || 'Unknown';
        case 'heal':
            return `Suggested for ${payload.node_id || 'node'}`;
        default:
            return JSON.stringify(payload).slice(0, 50);
    }
}

export const GraphHistoryModal: React.FC<GraphHistoryModalProps> = ({
    isOpen,
    onClose,
    onActionComplete
}) => {
    const queryClient = useQueryClient();
    const [confirmingUndoId, setConfirmingUndoId] = useState<string | null>(null);

    const { data, isLoading, error } = useQuery({
        queryKey: ['graph-history'],
        queryFn: () => graphHistoryApi.list({ page_size: 50 }),
        enabled: isOpen,
        refetchInterval: isOpen ? 5000 : false, // Refetch while open
    });

    const applyMutation = useMutation({
        mutationFn: graphHistoryApi.apply,
        onSuccess: () => {
            toast.success('Edit applied');
            queryClient.invalidateQueries({ queryKey: ['graph-history'] });
            onActionComplete?.();
        },
        onError: (err: Error) => {
            toast.error('Failed to apply edit', { description: err.message });
        },
    });

    const rejectMutation = useMutation({
        mutationFn: graphHistoryApi.reject,
        onSuccess: () => {
            toast.info('Edit rejected');
            queryClient.invalidateQueries({ queryKey: ['graph-history'] });
        },
        onError: (err: Error) => {
            toast.error('Failed to reject edit', { description: err.message });
        },
    });

    const undoMutation = useMutation({
        mutationFn: graphHistoryApi.undo,
        onSuccess: () => {
            toast.success('Edit undone');
            setConfirmingUndoId(null);
            queryClient.invalidateQueries({ queryKey: ['graph-history'] });
            onActionComplete?.();
        },
        onError: (err: Error) => {
            toast.error('Failed to undo edit', { description: err.message });
            setConfirmingUndoId(null);
        },
    });

    const items = data?.items || [];

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="max-w-3xl max-h-[80vh] flex flex-col p-0 gap-0 overflow-hidden border-border shadow-2xl">
                <DialogHeader className="p-6 border-b border-white/5 bg-white/[0.02]">
                    <DialogTitle className="flex items-center gap-2">
                        <Clock className="h-5 w-5 text-amber-500" />
                        Graph Edit History
                    </DialogTitle>
                    <DialogDescription>
                        Review, apply, or undo graph modifications.
                    </DialogDescription>
                </DialogHeader>

                <div className="flex-1 overflow-auto">
                    {isLoading ? (
                        <div className="flex items-center justify-center py-12">
                            <Loader2 className="h-8 w-8 text-amber-500 animate-spin" />
                        </div>
                    ) : error ? (
                        <div className="text-center py-12 text-red-400">
                            Failed to load history: {(error as Error).message}
                        </div>
                    ) : items.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                            <RotateCcw className="h-12 w-12 mb-4 opacity-30" />
                            <p className="text-lg font-medium">No graph edits recorded yet</p>
                            <p className="text-sm opacity-70">Changes made to the knowledge graph will appear here</p>
                        </div>
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead className="w-[100px]">Status</TableHead>
                                    <TableHead className="w-[120px]">Action</TableHead>
                                    <TableHead>Details</TableHead>
                                    <TableHead className="w-[100px]">Time</TableHead>
                                    <TableHead className="w-[120px] text-right">Actions</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {items.map((item) => {
                                    const Icon = ACTION_ICONS[item.action_type] || Network;
                                    const statusStyle = STATUS_STYLES[item.status];
                                    const isConfirmingUndo = confirmingUndoId === item.id;
                                    const isLoading = applyMutation.isPending || rejectMutation.isPending || undoMutation.isPending;

                                    return (
                                        <TableRow
                                            key={item.id}
                                            className={`group transition-colors hover:bg-white/5 ${item.status === 'rejected' || item.status === 'undone' ? 'opacity-50' : ''}`}
                                        >
                                            <TableCell>
                                                <Badge variant={statusStyle.variant} className={statusStyle.className}>
                                                    {item.status.toUpperCase()}
                                                </Badge>
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex items-center gap-2">
                                                    <Icon className="h-4 w-4 text-amber-500" />
                                                    <span className="font-medium uppercase text-xs">
                                                        {item.action_type.replace('_', ' ')}
                                                    </span>
                                                </div>
                                            </TableCell>
                                            <TableCell className="font-mono text-xs text-muted-foreground">
                                                {formatPayloadDetails(item.action_type, item.payload)}
                                            </TableCell>
                                            <TableCell className="text-xs text-muted-foreground">
                                                {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}
                                            </TableCell>
                                            <TableCell className="text-right">
                                                {item.status === 'pending' && (
                                                    <div className="flex items-center justify-end gap-1">
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            className="h-7 w-7 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10"
                                                            onClick={() => applyMutation.mutate(item.id)}
                                                            disabled={isLoading}
                                                        >
                                                            {applyMutation.isPending ? (
                                                                <Loader2 className="h-4 w-4 animate-spin" />
                                                            ) : (
                                                                <Check className="h-4 w-4" />
                                                            )}
                                                        </Button>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            className="h-7 w-7 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                                                            onClick={() => rejectMutation.mutate(item.id)}
                                                            disabled={isLoading}
                                                        >
                                                            <X className="h-4 w-4" />
                                                        </Button>
                                                    </div>
                                                )}
                                                {item.status === 'applied' && (
                                                    <div className="flex items-center justify-end gap-1">
                                                        {isConfirmingUndo ? (
                                                            <>
                                                                <span className="text-xs text-muted-foreground mr-1">Sure?</span>
                                                                <Button
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    className="h-7 w-7 text-amber-400 hover:text-amber-300"
                                                                    onClick={() => undoMutation.mutate(item.id)}
                                                                    disabled={undoMutation.isPending}
                                                                >
                                                                    {undoMutation.isPending ? (
                                                                        <Loader2 className="h-4 w-4 animate-spin" />
                                                                    ) : (
                                                                        <Undo2 className="h-4 w-4" />
                                                                    )}
                                                                </Button>
                                                                <Button
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    className="h-7 w-7"
                                                                    onClick={() => setConfirmingUndoId(null)}
                                                                >
                                                                    <X className="h-4 w-4" />
                                                                </Button>
                                                            </>
                                                        ) : (
                                                            <TooltipProvider>
                                                                <Tooltip>
                                                                    <TooltipTrigger asChild>
                                                                        <span className="inline-flex" tabIndex={0}> {/* Wrapper for disabled state */}
                                                                            <Button
                                                                                variant="ghost"
                                                                                size="icon"
                                                                                className={`h-7 w-7 ${(!item.snapshot && ['prune', 'delete_node', 'delete_edge', 'merge'].includes(item.action_type)) ? 'opacity-50 cursor-not-allowed' : 'text-muted-foreground hover:text-amber-400'}`}
                                                                                onClick={() => setConfirmingUndoId(item.id)}
                                                                                disabled={isLoading || (!item.snapshot && ['prune', 'delete_node', 'delete_edge', 'merge'].includes(item.action_type))}
                                                                            >
                                                                                <RotateCcw className="h-4 w-4" />
                                                                            </Button>
                                                                        </span>
                                                                    </TooltipTrigger>
                                                                    <TooltipContent>
                                                                        <p>{(!item.snapshot && ['prune', 'delete_node', 'delete_edge', 'merge'].includes(item.action_type)) ? "Undo not available (no snapshot)" : "Undo edit"}</p>
                                                                    </TooltipContent>
                                                                </Tooltip>
                                                            </TooltipProvider>
                                                        )}
                                                    </div>
                                                )}
                                                {(item.status === 'rejected' || item.status === 'undone') && (
                                                    <span className="text-xs text-muted-foreground">—</span>
                                                )}
                                            </TableCell>
                                        </TableRow>
                                    );
                                })}
                            </TableBody>
                        </Table>
                    )}
                </div>
            </DialogContent>
        </Dialog>
    );
};
