/**
 * Maintenance Page
 * ================
 * 
 * System maintenance, statistics, cache management, and maintenance actions.
 */

import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
    Database,
    HardDrive,
    Trash2,
    RefreshCw,
    AlertTriangle,
    FileText,
    Box,
    Share2,
    Users
} from 'lucide-react'
import { maintenanceApi, MaintenanceResult } from '@/lib/api-admin'
import { StatCard } from '@/components/ui/StatCard'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Alert, AlertDescription } from '@/components/ui/alert'

export default function MaintenancePage() {
    const queryClient = useQueryClient()
    const [actionResult, setActionResult] = useState<MaintenanceResult | null>(null)
    const [showConfirm, setShowConfirm] = useState<string | null>(null)

    // Use React Query with caching
    const { data: stats, isLoading: loading, error, refetch } = useQuery({
        queryKey: ['maintenance-stats'],
        queryFn: () => maintenanceApi.getStats(),
        staleTime: 30000, // Cache for 30 seconds
        refetchInterval: 60000, // Auto-refetch every minute
    })

    const clearCacheMutation = useMutation({
        mutationFn: () => maintenanceApi.clearCache(),
        onSuccess: (result) => {
            setActionResult(result)
            queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] })
            setShowConfirm(null)
        },
    })

    const pruneOrphansMutation = useMutation({
        mutationFn: () => maintenanceApi.pruneOrphans(),
        onSuccess: (result) => {
            setActionResult(result)
            queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] })
            setShowConfirm(null)
        },
    })

    const handleClearCache = () => {
        clearCacheMutation.mutate()
    }

    const handlePruneOrphans = () => {
        pruneOrphansMutation.mutate()
    }

    const executing = clearCacheMutation.isPending ? 'cache' : pruneOrphansMutation.isPending ? 'prune' : null

    const formatBytes = (bytes: number) => {
        if (bytes === 0) return '0 B'
        const k = 1024
        const sizes = ['B', 'KB', 'MB', 'GB']
        const i = Math.floor(Math.log(bytes) / Math.log(k))
        return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
    }

    if (loading && !stats) {
        return (
            <div className="p-6 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
        )
    }

    return (
        <div className="p-6 pb-32 max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">System Maintenance</h1>
                    <p className="text-muted-foreground">
                        System statistics and maintenance tools
                    </p>
                </div>
                <button
                    onClick={() => refetch()}
                    disabled={loading}
                    className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

            {error && (
                <Alert variant="destructive" className="mb-6">
                    <AlertDescription>{error instanceof Error ? error.message : 'Failed to load statistics'}</AlertDescription>
                </Alert>
            )}

            {actionResult && (
                <Alert
                    variant={actionResult.status === 'success' ? 'success' : 'warning'}
                    className="mb-6"
                    dismissible
                    onDismiss={() => setActionResult(null)}
                >
                    <div className="font-medium">{actionResult.operation}</div>
                    <AlertDescription className="mt-1">{actionResult.message}</AlertDescription>
                </Alert>
            )}

            {/* Database Stats */}
            <div className="mb-8">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Database className="w-5 h-5" />
                    Database Counts
                </h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <StatCard
                        icon={FileText}
                        label="Documents"
                        value={stats?.database.documents_total ?? 0}
                        subLabel={`${stats?.database.documents_ready ?? 0} ready`}
                    />
                    <StatCard
                        icon={Box}
                        label="Chunks"
                        value={stats?.database.chunks_total ?? 0}
                    />
                    <StatCard
                        icon={Users}
                        label="Entities"
                        value={stats?.database.entities_total ?? 0}
                    />
                    <StatCard
                        icon={Share2}
                        label="Relationships"
                        value={stats?.database.relationships_total ?? 0}
                    />
                </div>
            </div>

            {/* Cache Stats */}
            <div className="mb-8">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <HardDrive className="w-5 h-5" />
                    Cache Status
                </h2>
                <div className="bg-card border rounded-lg p-6">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-6">
                        <div>
                            <div className="text-sm text-muted-foreground">Memory Used</div>
                            <div className="text-xl font-bold">
                                {formatBytes(stats?.cache.memory_used_bytes ?? 0)}
                            </div>
                        </div>
                        <div>
                            <div className="text-sm text-muted-foreground">Total Keys</div>
                            <div className="text-xl font-bold">
                                {stats?.cache.keys_total ?? 0}
                            </div>
                        </div>
                        <div>
                            <div className="text-sm text-muted-foreground">Hit Rate</div>
                            <div className="text-xl font-bold text-green-600">
                                {stats?.cache.hit_rate != null ? `${stats.cache.hit_rate}%` : '—'}
                            </div>
                        </div>
                        <div>
                            <div className="text-sm text-muted-foreground">Evictions</div>
                            <div className="text-xl font-bold">
                                {stats?.cache.evictions ?? 0}
                            </div>
                        </div>
                    </div>

                    {/* Memory Bar */}
                    <div className="space-y-2">
                        <div className="flex justify-between text-sm">
                            <span className="text-muted-foreground">Memory Usage</span>
                            <span>{stats?.cache.memory_usage_percent ?? 0}%</span>
                        </div>
                        <div className="h-3 bg-muted rounded-full overflow-hidden">
                            <div
                                className={`h-full transition-all ${(stats?.cache.memory_usage_percent ?? 0) > 90
                                    ? 'bg-red-500'
                                    : (stats?.cache.memory_usage_percent ?? 0) > 70
                                        ? 'bg-yellow-500'
                                        : 'bg-green-500'
                                    }`}
                                style={{ width: `${stats?.cache.memory_usage_percent ?? 0}%` }}
                            />
                        </div>
                    </div>
                </div>
            </div>

            {/* Maintenance Actions */}
            <div>
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <AlertTriangle className="w-5 h-5" />
                    Maintenance Actions
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <ActionCard
                        icon={Trash2}
                        title="Clear Cache"
                        description="Remove all cached queries, embeddings, and responses from Redis."
                        buttonText="Clear Cache"
                        buttonVariant="warning"
                        onClick={() => setShowConfirm('cache')}
                        loading={executing === 'cache'}
                    />
                    <ActionCard
                        icon={Trash2}
                        title="Prune Orphans"
                        description="Remove orphan entities and chunks not connected to any documents."
                        buttonText="Prune Orphans"
                        buttonVariant="warning"
                        onClick={() => setShowConfirm('prune')}
                        loading={executing === 'prune'}
                    />
                </div>
            </div>

            {/* Confirmation Dialog */}
            <ConfirmDialog
                open={showConfirm !== null}
                onOpenChange={(open) => !open && setShowConfirm(null)}
                title={showConfirm === 'cache' ? 'Clear Cache?' : 'Prune Orphans?'}
                description={
                    showConfirm === 'cache'
                        ? 'This will remove all cached data. Queries may be slower until the cache warms up.'
                        : 'This will permanently remove orphan nodes from the graph. This cannot be undone.'
                }
                onConfirm={showConfirm === 'cache' ? handleClearCache : handlePruneOrphans}
                variant="destructive"
                loading={executing !== null}
            />
        </div>
    )
}

// StatCard imported from components/ui/StatCard

interface ActionCardProps {
    icon: React.ComponentType<{ className?: string }>
    title: string
    description: string
    buttonText: string
    buttonVariant: 'warning' | 'danger'
    onClick: () => void
    loading?: boolean
}

function ActionCard({ icon: Icon, title, description, buttonText, buttonVariant, onClick, loading }: ActionCardProps) {
    return (
        <div className="bg-card border rounded-lg p-6">
            <div className="flex items-start gap-4">
                <div className={`p-3 rounded-lg ${buttonVariant === 'danger'
                    ? 'bg-[hsl(var(--destructive)_/_0.1)]'
                    : 'bg-warning-muted'
                    }`}>
                    <Icon className={`w-6 h-6 ${buttonVariant === 'danger'
                        ? 'text-destructive'
                        : 'text-warning'
                        }`} />
                </div>
                <div className="flex-1">
                    <h3 className="font-medium mb-1">{title}</h3>
                    <p className="text-sm text-muted-foreground mb-4">{description}</p>
                    <button
                        onClick={onClick}
                        disabled={loading}
                        className={`px-4 py-2 rounded-md text-white transition-colors disabled:opacity-50 ${buttonVariant === 'danger'
                            ? 'bg-destructive hover:bg-destructive/90'
                            : 'bg-warning hover:bg-warning/90'
                            }`}
                    >
                        {loading ? 'Processing...' : buttonText}
                    </button>
                </div>
            </div>
        </div>
    )
}

