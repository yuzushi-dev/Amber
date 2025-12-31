/**
 * Curation Page
 * =============
 * 
 * Queue for reviewing analyst-reported flags and data quality issues.
 */

import { useState, useEffect } from 'react'
import { Flag, Check, X, GitMerge, RefreshCw, Eye } from 'lucide-react'
import { curationApi, FlagSummary, FlagDetail, CurationStats } from '@/lib/api-admin'

export default function CurationPage() {
    const [flags, setFlags] = useState<FlagSummary[]>([])
    const [stats, setStats] = useState<CurationStats | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selectedFlag, setSelectedFlag] = useState<FlagDetail | null>(null)
    const [statusFilter, setStatusFilter] = useState<string>('pending')
    const [resolvingId, setResolvingId] = useState<string | null>(null)

    useEffect(() => {
        loadData()
    }, [statusFilter])

    const loadData = async () => {
        try {
            setLoading(true)
            const [flagsData, statsData] = await Promise.all([
                curationApi.listFlags({ status: statusFilter, limit: 50 }),
                curationApi.getStats()
            ])
            setFlags(flagsData.flags)
            setStats(statsData)
            setError(null)
        } catch (err) {
            setError('Failed to load curation queue')
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    const handleViewFlag = async (flagId: string) => {
        try {
            const detail = await curationApi.getFlag(flagId)
            setSelectedFlag(detail)
        } catch (err) {
            console.error('Failed to load flag details:', err)
        }
    }

    const handleResolve = async (flagId: string, action: 'accept' | 'reject' | 'merge') => {
        try {
            setResolvingId(flagId)
            await curationApi.resolveFlag(flagId, { action })
            await loadData()
            setSelectedFlag(null)
        } catch (err) {
            console.error('Failed to resolve flag:', err)
        } finally {
            setResolvingId(null)
        }
    }

    const getTypeColor = (type: string) => {
        switch (type) {
            case 'wrong_fact':
                return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
            case 'bad_link':
                return 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400'
            case 'wrong_entity':
            case 'missing_entity':
                return 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400'
            case 'duplicate_entity':
            case 'merge_suggestion':
                return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400'
            default:
                return 'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400'
        }
    }

    return (
        <div className="p-6 max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">Curation Queue</h1>
                    <p className="text-muted-foreground">
                        Review and resolve analyst-reported issues
                    </p>
                </div>
                <button
                    onClick={loadData}
                    disabled={loading}
                    className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

            {/* Stats Cards */}
            {stats && (
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                    <div className="bg-card border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Pending</div>
                        <div className="text-2xl font-bold text-yellow-600">{stats.pending_count}</div>
                    </div>
                    <div className="bg-card border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Accepted</div>
                        <div className="text-2xl font-bold text-green-600">{stats.accepted_count}</div>
                    </div>
                    <div className="bg-card border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Rejected</div>
                        <div className="text-2xl font-bold text-red-600">{stats.rejected_count}</div>
                    </div>
                    <div className="bg-card border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Merged</div>
                        <div className="text-2xl font-bold text-blue-600">{stats.merged_count}</div>
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
            <div className="flex gap-2 mb-4">
                {['pending', 'accepted', 'rejected', 'merged'].map(status => (
                    <button
                        key={status}
                        onClick={() => setStatusFilter(status)}
                        className={`px-4 py-2 rounded-md capitalize transition-colors ${statusFilter === status
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-muted hover:bg-muted/80'
                            }`}
                    >
                        {status}
                    </button>
                ))}
            </div>

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6">
                    <p className="text-red-800 dark:text-red-400">{error}</p>
                </div>
            )}

            {/* Flags Table */}
            <div className="bg-card border rounded-lg overflow-hidden">
                <table className="w-full">
                    <thead className="bg-muted/50">
                        <tr>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground">Type</th>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground">Reporter</th>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground">Preview</th>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground">Created</th>
                            <th className="text-right px-4 py-3 font-medium text-muted-foreground">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y">
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
                                        <button
                                            onClick={() => handleViewFlag(flag.id)}
                                            className="p-2 hover:bg-muted rounded transition-colors"
                                            title="View details"
                                        >
                                            <Eye className="w-4 h-4" />
                                        </button>
                                        {flag.status === 'pending' && (
                                            <>
                                                <button
                                                    onClick={() => handleResolve(flag.id, 'accept')}
                                                    disabled={resolvingId === flag.id}
                                                    className="p-2 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded transition-colors"
                                                    title="Accept"
                                                >
                                                    <Check className="w-4 h-4" />
                                                </button>
                                                <button
                                                    onClick={() => handleResolve(flag.id, 'reject')}
                                                    disabled={resolvingId === flag.id}
                                                    className="p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
                                                    title="Reject"
                                                >
                                                    <X className="w-4 h-4" />
                                                </button>
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
                className="fixed inset-0 bg-black/50 z-40"
                onClick={onClose}
            />

            {/* Drawer */}
            <div className="fixed right-0 top-0 h-full w-full max-w-xl bg-card border-l z-50 overflow-y-auto">
                <div className="p-6">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="text-lg font-semibold">Flag Details</h2>
                        <button
                            onClick={onClose}
                            className="p-2 hover:bg-muted rounded transition-colors"
                        >
                            <X className="w-5 h-5" />
                        </button>
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
                            <button
                                onClick={() => onResolve(flag.id, 'accept')}
                                disabled={resolving}
                                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors disabled:opacity-50"
                            >
                                <Check className="w-4 h-4" />
                                Accept
                            </button>
                            <button
                                onClick={() => onResolve(flag.id, 'reject')}
                                disabled={resolving}
                                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors disabled:opacity-50"
                            >
                                <X className="w-4 h-4" />
                                Reject
                            </button>
                            {(flag.type === 'duplicate_entity' || flag.type === 'merge_suggestion') && (
                                <button
                                    onClick={() => onResolve(flag.id, 'merge')}
                                    disabled={resolving}
                                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50"
                                >
                                    <GitMerge className="w-4 h-4" />
                                    Merge
                                </button>
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
