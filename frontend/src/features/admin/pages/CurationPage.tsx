/**
 * CurationPage.tsx
 * ================
 * 
 * Queue for reviewing analyst-reported flags and data quality issues.
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Flag, Check, X, GitMerge, RefreshCw, Eye } from 'lucide-react'
import { curationApi, FlagDetail } from '@/lib/api-admin'
import { Button } from '@/components/ui/button'
import { PageHeader } from '../components/PageHeader'

export default function CurationPage() {
    const queryClient = useQueryClient()
    const [selectedFlag, setSelectedFlag] = useState<FlagDetail | null>(null)
    const [statusFilter, setStatusFilter] = useState<string>('pending')
    const [resolvingId, setResolvingId] = useState<string | null>(null)

    // Use React Query with caching for flags
    const { data: flagsData, isLoading: loadingFlags, error: flagsError, refetch: refetchFlags } = useQuery({
        queryKey: ['curation-flags', statusFilter],
        queryFn: () => curationApi.listFlags({ status: statusFilter, limit: 50 }),
        staleTime: 30000,
    })

    // Use React Query with caching for stats
    const { data: stats, isLoading: loadingStats } = useQuery({
        queryKey: ['curation-stats'],
        queryFn: () => curationApi.getStats(),
        staleTime: 30000,
    })

    const flags = flagsData?.flags ?? []
    const loading = loadingFlags || loadingStats
    const error = flagsError ? 'Failed to load curation queue' : null

    const handleViewFlag = async (flagId: string) => {
        try {
            const detail = await curationApi.getFlag(flagId)
            setSelectedFlag(detail)
        } catch (err) {
            console.error('Failed to load flag details:', err)
        }
    }

    const resolveMutation = useMutation({
        mutationFn: ({ flagId, action }: { flagId: string; action: 'accept' | 'reject' | 'merge' }) =>
            curationApi.resolveFlag(flagId, { action }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['curation-flags'] })
            queryClient.invalidateQueries({ queryKey: ['curation-stats'] })
            setSelectedFlag(null)
            setResolvingId(null)
        },
        onError: (err) => {
            console.error('Failed to resolve flag:', err)
            setResolvingId(null)
        },
    })

    const handleResolve = (flagId: string, action: 'accept' | 'reject' | 'merge') => {
        setResolvingId(flagId)
        resolveMutation.mutate({ flagId, action })
    }

    const getTypeColor = (type: string) => {
        switch (type) {
            case 'wrong_fact':
                return 'bg-destructive/10 text-destructive border border-destructive/20'
            case 'bad_link':
                return 'bg-warning-muted text-warning-foreground border border-warning/30'
            case 'wrong_entity':
            case 'missing_entity':
                return 'bg-info-muted text-info-foreground border border-info/30'
            case 'duplicate_entity':
            case 'merge_suggestion':
                return 'bg-primary/10 text-primary border border-primary/30'
            default:
                return 'bg-muted text-muted-foreground border border-border'
        }
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="Curation Queue"
                description="Review and resolve analyst-reported issues."
                actions={
                    <Button
                        onClick={() => refetchFlags()}
                        disabled={loading}
                        variant="outline"
                        className="gap-2 h-9 text-xs"
                    >
                        <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                        Refresh
                    </Button>
                }
            />

            {/* Stats Cards */}
            {stats && (
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                    <div className="bg-card border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Pending</div>
                        <div className="text-2xl font-bold text-warning">{stats.pending_count}</div>
                    </div>
                    <div className="bg-card border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Accepted</div>
                        <div className="text-2xl font-bold text-success">{stats.accepted_count}</div>
                    </div>
                    <div className="bg-card border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Rejected</div>
                        <div className="text-2xl font-bold text-destructive">{stats.rejected_count}</div>
                    </div>
                    <div className="bg-card border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Merged</div>
                        <div className="text-2xl font-bold text-info">{stats.merged_count}</div>
                    </div>
                    <div className="bg-card border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Avg Resolution</div>
                        <div className="text-2xl font-bold">
                            {stats.avg_resolution_time_hours
                                ? `${stats.avg_resolution_time_hours.toFixed(1)}h`
                                : '—'}
                        </div>
                    </div>
                </div>
            )}

            {/* Filter Tabs */}
            <div className="flex gap-2">
                {['pending', 'accepted', 'rejected', 'merged'].map(status => (
                    <Button
                        key={status}
                        onClick={() => setStatusFilter(status)}
                        variant={statusFilter === status ? 'default' : 'ghost'}
                        className="capitalize h-8 text-xs"
                    >
                        {status}
                    </Button>
                ))}
            </div>

            {error && (
                <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4">
                    <p className="text-destructive">{error}</p>
                </div>
            )}

            {/* Flags Table */}
            <div className="bg-card border rounded-lg overflow-hidden">
                <table className="w-full">
                    <thead className="bg-muted/50">
                        <tr>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground text-sm">Type</th>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground text-sm">Reporter</th>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground text-sm">Preview</th>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground text-sm">Created</th>
                            <th className="text-right px-4 py-3 font-medium text-muted-foreground text-sm">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y border-t border-border/50">
                        {flags.length === 0 && !loading && (
                            <tr>
                                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                                    No {statusFilter} flags found
                                </td>
                            </tr>
                        )}
                        {flags.map((flag) => (
                            <tr key={flag.id} className="hover:bg-muted/30 transition-colors">
                                <td className="px-4 py-3">
                                    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${getTypeColor(flag.type)}`}>
                                        <Flag className="w-3 h-3" />
                                        {flag.type.replace('_', ' ')}
                                    </span>
                                </td>
                                <td className="px-4 py-3 text-sm">{flag.reported_by}</td>
                                <td className="px-4 py-3">
                                    <div className="text-sm truncate max-w-xs" title={flag.snippet_preview || ''}>
                                        {flag.snippet_preview || flag.comment || '—'}
                                    </div>
                                </td>
                                <td className="px-4 py-3 text-sm text-muted-foreground">
                                    {new Date(flag.created_at).toLocaleDateString()}
                                </td>
                                <td className="px-4 py-3 text-right">
                                    <div className="flex items-center justify-end gap-1">
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => handleViewFlag(flag.id)}
                                            className="px-2 h-8 w-8"
                                            title="View details"
                                            aria-label={`View details for flag ${flag.id.slice(0, 8)}`}
                                        >
                                            <Eye className="w-4 h-4" />
                                        </Button>
                                        {flag.status === 'pending' && (
                                            <>
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={() => handleResolve(flag.id, 'accept')}
                                                    disabled={resolvingId === flag.id}
                                                    className="px-2 h-8 w-8 text-success hover:text-success/80 hover:bg-success/10"
                                                    title="Accept"
                                                    aria-label={`Accept flag ${flag.id.slice(0, 8)}`}
                                                >
                                                    <Check className="w-4 h-4" />
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={() => handleResolve(flag.id, 'reject')}
                                                    disabled={resolvingId === flag.id}
                                                    className="px-2 h-8 w-8 text-destructive hover:text-destructive/80 hover:bg-destructive/10"
                                                    title="Reject"
                                                    aria-label={`Reject flag ${flag.id.slice(0, 8)}`}
                                                >
                                                    <X className="w-4 h-4" />
                                                </Button>
                                            </>
                                        )}
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Detail Drawer */}
            {selectedFlag && (
                <FlagDetailDrawer
                    flag={selectedFlag}
                    onClose={() => setSelectedFlag(null)}
                    onResolve={handleResolve}
                    resolving={resolvingId === selectedFlag.id}
                />
            )}
        </div>
    )
}

interface FlagDetailDrawerProps {
    flag: FlagDetail
    onClose: () => void
    onResolve: (id: string, action: 'accept' | 'reject' | 'merge') => void
    resolving: boolean
}

function FlagDetailDrawer({ flag, onClose, onResolve, resolving }: FlagDetailDrawerProps) {
    return (
        <>
            {/* Backdrop */}
            <div
                className="fixed inset-0 bg-background/60 z-40"
                onClick={onClose}
            />

            {/* Drawer */}
            <div className="fixed right-0 top-0 h-full w-full max-w-xl bg-card border-l z-50 overflow-y-auto shadow-2xl">
                <div className="p-6">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="text-lg font-semibold">Flag Details</h2>
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={onClose}
                            aria-label="Close flag details"
                        >
                            <X className="w-5 h-5" />
                        </Button>
                    </div>

                    {/* Flag Info */}
                    <div className="space-y-4 mb-6">
                        <div>
                            <label className="text-sm text-muted-foreground">Type</label>
                            <div className="font-medium capitalize">{flag.type.replace('_', ' ')}</div>
                        </div>
                        <div>
                            <label className="text-sm text-muted-foreground">Status</label>
                            <div className="font-medium capitalize">{flag.status}</div>
                        </div>
                        <div>
                            <label className="text-sm text-muted-foreground">Reported By</label>
                            <div className="font-medium">{flag.reported_by}</div>
                        </div>
                        {flag.comment && (
                            <div>
                                <label className="text-sm text-muted-foreground">Comment</label>
                                <div className="font-medium">{flag.comment}</div>
                            </div>
                        )}
                    </div>

                    {/* Context */}
                    <div className="border-t pt-4 mb-6">
                        <h3 className="font-medium mb-3">Context</h3>

                        {flag.context.query_text && (
                            <div className="mb-4">
                                <label className="text-sm text-muted-foreground">Original Query</label>
                                <div className="bg-muted p-3 rounded-md text-sm">
                                    {flag.context.query_text}
                                </div>
                            </div>
                        )}

                        {flag.context.chunk_text && (
                            <div className="mb-4">
                                <label className="text-sm text-muted-foreground">Source Chunk</label>
                                <div className="bg-muted p-3 rounded-md text-sm max-h-48 overflow-y-auto">
                                    {flag.context.chunk_text}
                                </div>
                            </div>
                        )}

                        {flag.context.entity_name && (
                            <div className="mb-4">
                                <label className="text-sm text-muted-foreground">Entity</label>
                                <div className="font-medium">{flag.context.entity_name}</div>
                            </div>
                        )}

                        {flag.context.document_title && (
                            <div className="mb-4">
                                <label className="text-sm text-muted-foreground">Document</label>
                                <div className="font-medium">{flag.context.document_title}</div>
                            </div>
                        )}
                    </div>

                    {/* Actions */}
                    {flag.status === 'pending' && (
                        <div className="flex gap-2">
                            <Button
                                onClick={() => onResolve(flag.id, 'accept')}
                                disabled={resolving}
                                className="flex-1 gap-2 bg-success text-success-foreground hover:bg-success/90"
                            >
                                <Check className="w-4 h-4" />
                                Accept
                            </Button>
                            <Button
                                onClick={() => onResolve(flag.id, 'reject')}
                                disabled={resolving}
                                className="flex-1 gap-2 bg-destructive text-destructive-foreground hover:bg-destructive/90"
                            >
                                <X className="w-4 h-4" />
                                Reject
                            </Button>
                            {(flag.type === 'duplicate_entity' || flag.type === 'merge_suggestion') && (
                                <Button
                                    onClick={() => onResolve(flag.id, 'merge')}
                                    disabled={resolving}
                                    className="flex-1 gap-2 bg-info text-info-foreground hover:bg-info/90"
                                >
                                    <GitMerge className="w-4 h-4" />
                                    Merge
                                </Button>
                            )}
                        </div>
                    )}

                    {/* Resolution Info */}
                    {flag.resolved_at && (
                        <div className="border-t pt-4 mt-6">
                            <h3 className="font-medium mb-3">Resolution</h3>
                            <div className="space-y-2 text-sm">
                                <div>
                                    <span className="text-muted-foreground">Resolved by: </span>
                                    {flag.resolved_by}
                                </div>
                                <div>
                                    <span className="text-muted-foreground">Resolved at: </span>
                                    {new Date(flag.resolved_at).toLocaleString()}
                                </div>
                                {flag.resolution_notes && (
                                    <div>
                                        <span className="text-muted-foreground">Notes: </span>
                                        {flag.resolution_notes}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </>
    )
}
