import { useEffect, useState } from 'react'
import { Loader2, Sparkles, Plus, X } from 'lucide-react'
import { toast } from 'sonner'

import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { graphEditorApi, graphHistoryApi } from '@/lib/api-client'
import { HealingSuggestion } from '@/types/graph'

interface HealSuggestionsDialogProps {
    open: boolean
    nodeId: string | null
    nodeLabel: string
    sourceView: 'global' | 'document'
    onOpenChange: (open: boolean) => void
    onQueued: () => void
}

export function HealSuggestionsDialog({
    open,
    nodeId,
    nodeLabel,
    sourceView,
    onOpenChange,
    onQueued,
}: HealSuggestionsDialogProps) {
    const [loading, setLoading] = useState(false)
    const [suggestions, setSuggestions] = useState<HealingSuggestion[]>([])
    const [processingId, setProcessingId] = useState<string | null>(null)

    useEffect(() => {
        if (!open || !nodeId) return

        let cancelled = false
        const run = async () => {
            setLoading(true)
            setSuggestions([])
            try {
                const result = await graphEditorApi.heal({ node_id: nodeId })
                if (!cancelled) setSuggestions(result)
            } catch (err) {
                console.error('heal failed:', err)
                if (!cancelled) toast.error('Healing analysis failed')
            } finally {
                if (!cancelled) setLoading(false)
            }
        }
        run()
        return () => {
            cancelled = true
        }
    }, [open, nodeId])

    const queueConnect = async (target: HealingSuggestion) => {
        if (!nodeId) return
        setProcessingId(target.id)
        try {
            await graphHistoryApi.create({
                action_type: 'connect',
                payload: {
                    source: nodeId,
                    target: target.id,
                    type: 'RELATED_TO',
                },
                source_view: sourceView,
            })
            toast.success(`Queued: "${nodeLabel}" → "${target.name}"`, {
                description: 'Open History to review and apply',
            })
            setSuggestions(prev => prev.filter(s => s.id !== target.id))
            onQueued()
        } catch (err) {
            console.error(err)
            toast.error('Failed to queue connection')
        } finally {
            setProcessingId(null)
        }
    }

    const dismiss = (target: HealingSuggestion) => {
        setSuggestions(prev => prev.filter(s => s.id !== target.id))
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Sparkles className="w-5 h-5 text-primary" />
                        Heal: {nodeLabel}
                    </DialogTitle>
                    <DialogDescription>
                        Suggestions based on semantic similarity. Accept to queue a connection
                        in the graph history for review.
                    </DialogDescription>
                </DialogHeader>

                <div className="min-h-[200px] max-h-[60vh] overflow-y-auto">
                    {loading ? (
                        <div className="flex items-center justify-center py-12 gap-3 text-muted-foreground text-sm">
                            <Loader2 className="w-5 h-5 animate-spin" />
                            Analyzing similar contexts…
                        </div>
                    ) : suggestions.length === 0 ? (
                        <div className="py-12 text-center text-sm text-muted-foreground">
                            No connection candidates found.
                        </div>
                    ) : (
                        <ul className="space-y-2">
                            {suggestions.map(s => (
                                <li
                                    key={s.id}
                                    className="p-3 rounded-md border border-border/60 bg-muted/30 flex items-start gap-3"
                                >
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className="font-medium truncate">{s.name}</span>
                                            <Badge variant="outline" className="text-xs">
                                                {s.type}
                                            </Badge>
                                            <Badge
                                                variant={s.confidence >= 0.8 ? 'success' : 'secondary'}
                                                className="text-xs"
                                            >
                                                {Math.round(s.confidence * 100)}%
                                            </Badge>
                                        </div>
                                        <p className="text-xs text-muted-foreground line-clamp-2">
                                            {s.reason}
                                        </p>
                                        {s.description && (
                                            <p className="text-xs text-muted-foreground/80 mt-1 italic line-clamp-2">
                                                {s.description}
                                            </p>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-1 shrink-0">
                                        <Button
                                            variant="outline"
                                            size="icon"
                                            className="h-7 w-7"
                                            onClick={() => queueConnect(s)}
                                            disabled={processingId === s.id}
                                            aria-label="Queue connection"
                                        >
                                            {processingId === s.id ? (
                                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                            ) : (
                                                <Plus className="w-3.5 h-3.5" />
                                            )}
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-7 w-7"
                                            onClick={() => dismiss(s)}
                                            aria-label="Dismiss suggestion"
                                        >
                                            <X className="w-3.5 h-3.5" />
                                        </Button>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>

                <DialogFooter>
                    <Button variant="ghost" onClick={() => onOpenChange(false)}>
                        Close
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
