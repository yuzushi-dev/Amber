import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2, Trash2, Eye, Bug, Layers } from 'lucide-react'
import { toast } from 'sonner'

import { graphEditorApi } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@/components/ui/tooltip'

// Feature flag — flip when bulk-prune is reviewed safe for prod.
// Backend endpoint remains callable (curl/CLI) for staged rollout.
const BULK_PRUNE_ENABLED = false
const BULK_PRUNE_DISABLED_REASON =
    'Bulk prune is temporarily disabled in the UI pending safety review (no snapshot/undo in graph_history). Use the CLI or /v1/graph/editor/bulk-prune for now.'

interface GraphAnomaliesPanelProps {
    className?: string
}

type Criterion = 'orphans' | 'leaves'

export function GraphAnomaliesPanel({ className }: GraphAnomaliesPanelProps) {
    const queryClient = useQueryClient()
    const [confirmCriterion, setConfirmCriterion] = useState<Criterion | null>(null)
    const [degreeLt, setDegreeLt] = useState<number>(2)

    const { data, isLoading, refetch } = useQuery({
        queryKey: ['graph-anomalies'],
        queryFn: () => graphEditorApi.getAnomalies({ limit: 50, degree_threshold: 1 }),
        refetchInterval: 60_000,
        staleTime: 30_000,
    })

    const dryRunMutation = useMutation({
        mutationFn: (criterion: Criterion) =>
            graphEditorApi.bulkPrune({
                criterion,
                degree_lt: criterion === 'leaves' ? degreeLt : undefined,
                dry_run: true,
                cap: 500,
            }),
    })

    const applyMutation = useMutation({
        mutationFn: (criterion: Criterion) =>
            graphEditorApi.bulkPrune({
                criterion,
                degree_lt: criterion === 'leaves' ? degreeLt : undefined,
                dry_run: false,
                cap: 500,
            }),
        onSuccess: (result) => {
            toast.success(`Pruned ${result.deleted} nodes (${result.criterion})`)
            setConfirmCriterion(null)
            queryClient.invalidateQueries({ queryKey: ['graph-anomalies'] })
            queryClient.invalidateQueries({ queryKey: ['graph-health'] })
            queryClient.invalidateQueries({ queryKey: ['graph-top-nodes'] })
            refetch()
        },
        onError: (err) => {
            console.error(err)
            toast.error('Bulk prune failed')
        },
    })

    const openConfirm = async (criterion: Criterion) => {
        try {
            await dryRunMutation.mutateAsync(criterion)
            setConfirmCriterion(criterion)
        } catch (err) {
            console.error(err)
            toast.error('Could not preview bulk prune')
        }
    }

    if (isLoading || !data) {
        return (
            <div className={`p-4 rounded-xl bg-surface-950/80 backdrop-blur-md border border-white/5 shadow-xl ${className ?? ''}`}>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Loading anomalies…
                </div>
            </div>
        )
    }

    const orphanCount = data.orphans.length
    const leafCount = data.leaves.length
    const dupCount = data.duplicate_candidates.length

    return (
        <div className={`p-4 rounded-xl bg-surface-950/80 backdrop-blur-md border border-white/5 shadow-xl space-y-3 ${className ?? ''}`}>
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                <span className="flex items-center gap-2">
                    <Bug className="w-3.5 h-3.5 text-warning" />
                    Anomalies
                </span>
                <button
                    onClick={() => refetch()}
                    className="text-[10px] uppercase tracking-wider hover:text-foreground transition-colors"
                    aria-label="Refresh anomalies"
                >
                    refresh
                </button>
            </div>

            <ul className="space-y-2 text-xs">
                <li className="flex items-center justify-between">
                    <span className="flex items-center gap-2">
                        <AlertTriangle className={`w-3 h-3 ${orphanCount > 0 ? 'text-destructive' : 'text-muted-foreground/60'}`} />
                        Orphan entities
                    </span>
                    <div className="flex items-center gap-2">
                        <Badge variant="outline" className="font-mono text-[10px]">
                            {orphanCount}
                        </Badge>
                        {orphanCount > 0 && (
                            <TooltipProvider>
                                <Tooltip delayDuration={150}>
                                    <TooltipTrigger asChild>
                                        <span tabIndex={0}>
                                            <Button
                                                size="sm"
                                                variant="ghost"
                                                className="h-6 px-2 text-[10px]"
                                                onClick={() => openConfirm('orphans')}
                                                disabled={!BULK_PRUNE_ENABLED || dryRunMutation.isPending}
                                            >
                                                <Trash2 className="w-3 h-3 mr-1" /> Prune
                                            </Button>
                                        </span>
                                    </TooltipTrigger>
                                    <TooltipContent side="left" className="max-w-[260px] text-xs">
                                        {BULK_PRUNE_ENABLED
                                            ? 'Preview (dry-run) then confirm to delete.'
                                            : BULK_PRUNE_DISABLED_REASON}
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        )}
                    </div>
                </li>
                <li className="flex items-center justify-between">
                    <span className="flex items-center gap-2">
                        <Layers className={`w-3 h-3 ${leafCount > 0 ? 'text-warning' : 'text-muted-foreground/60'}`} />
                        Leaves (degree &le; 1)
                    </span>
                    <div className="flex items-center gap-2">
                        <Badge variant="outline" className="font-mono text-[10px]">
                            {leafCount}
                        </Badge>
                        {leafCount > 0 && (
                            <TooltipProvider>
                                <Tooltip delayDuration={150}>
                                    <TooltipTrigger asChild>
                                        <span tabIndex={0}>
                                            <Button
                                                size="sm"
                                                variant="ghost"
                                                className="h-6 px-2 text-[10px]"
                                                onClick={() => openConfirm('leaves')}
                                                disabled={!BULK_PRUNE_ENABLED || dryRunMutation.isPending}
                                            >
                                                <Trash2 className="w-3 h-3 mr-1" /> Prune &lt;{degreeLt}
                                            </Button>
                                        </span>
                                    </TooltipTrigger>
                                    <TooltipContent side="left" className="max-w-[260px] text-xs">
                                        {BULK_PRUNE_ENABLED
                                            ? `Delete entities with degree < ${degreeLt}.`
                                            : BULK_PRUNE_DISABLED_REASON}
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        )}
                    </div>
                </li>
                <li className="flex items-center justify-between">
                    <span className="flex items-center gap-2">
                        <Eye className="w-3 h-3 text-muted-foreground/60" />
                        Duplicate candidates
                    </span>
                    <Badge variant="outline" className="font-mono text-[10px]">{dupCount}</Badge>
                </li>
                <li className="flex items-center justify-between">
                    <span className="text-muted-foreground/80">Dense communities</span>
                    <span className="font-mono text-[10px] text-muted-foreground">
                        {data.dense_communities.slice(0, 3).map(c => c.count).join(' · ') || '—'}
                    </span>
                </li>
            </ul>

            <div className="flex items-center gap-2 text-[10px] text-muted-foreground/80">
                <span>Leaf threshold:</span>
                <input
                    type="number"
                    min={2}
                    max={5}
                    value={degreeLt}
                    onChange={(e) => setDegreeLt(Math.max(2, Math.min(5, Number(e.target.value) || 2)))}
                    className="w-12 h-6 px-2 rounded bg-foreground/5 border border-white/10 text-foreground"
                />
            </div>

            <Dialog open={!!confirmCriterion} onOpenChange={(open) => !open && setConfirmCriterion(null)}>
                <DialogContent className="sm:max-w-md">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <AlertTriangle className="w-5 h-5 text-destructive" />
                            Bulk prune confirmation
                        </DialogTitle>
                        <DialogDescription>
                            About to delete{' '}
                            <b>{dryRunMutation.data?.would_delete.length ?? 0}</b>{' '}
                            entities by criterion <b>{confirmCriterion}</b>.
                            Cap 500 per call. Action cannot be undone.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="max-h-48 overflow-y-auto border border-border/40 rounded-md p-2 bg-muted/20 text-xs font-mono">
                        {(dryRunMutation.data?.would_delete ?? []).slice(0, 50).map(id => (
                            <div key={id} className="truncate">{id}</div>
                        ))}
                        {(dryRunMutation.data?.would_delete.length ?? 0) > 50 && (
                            <div className="text-muted-foreground italic">
                                …and {(dryRunMutation.data?.would_delete.length ?? 0) - 50} more
                            </div>
                        )}
                    </div>
                    <DialogFooter>
                        <Button variant="ghost" onClick={() => setConfirmCriterion(null)}>
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={() => confirmCriterion && applyMutation.mutate(confirmCriterion)}
                            disabled={applyMutation.isPending}
                        >
                            {applyMutation.isPending ? (
                                <>
                                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                    Pruning…
                                </>
                            ) : (
                                <>
                                    <Trash2 className="w-4 h-4 mr-2" />
                                    Confirm prune
                                </>
                            )}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
