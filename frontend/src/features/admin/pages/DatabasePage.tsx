/**
 * Database Page
 * =============
 * 
 * Database statistics, cache management, and maintenance actions.
 */

import React, { useState, useEffect } from 'react'
import {
    Database,
    HardDrive,
    Layers,
    Trash2,
    RefreshCw,
    AlertTriangle,
    CheckCircle,
    FileText,
    Box,
    Share2,
    Users
} from 'lucide-react'
import { maintenanceApi, SystemStats, MaintenanceResult } from '@/lib/api-admin'

export default function DatabasePage() {
    const [stats, setStats] = useState<SystemStats | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [actionResult, setActionResult] = useState<MaintenanceResult | null>(null)
    const [showConfirm, setShowConfirm] = useState<string | null>(null)
    const [executing, setExecuting] = useState<string | null>(null)

    useEffect(() => {
        loadStats()
    }, [])

    const loadStats = async () => {
        try {
            setLoading(true)
            const data = await maintenanceApi.getStats()
            setStats(data)
            setError(null)
        } catch (err) {
            setError('Failed to load system statistics')
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    const handleClearCache = async () => {
        try {
            setExecuting('cache')
            setShowConfirm(null)
            const result = await maintenanceApi.clearCache()
            setActionResult(result)
            await loadStats()
        } catch (err) {
            console.error('Clear cache failed:', err)
        } finally {
            setExecuting(null)
        }
    }

    const handlePruneOrphans = async () => {
        try {
            setExecuting('prune')
            setShowConfirm(null)
            const result = await maintenanceApi.pruneOrphans()
            setActionResult(result)
            await loadStats()
        } catch (err) {
            console.error('Prune orphans failed:', err)
        } finally {
            setExecuting(null)
        }
    }

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
        <div className="p-6 max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">Database Administration</h1>
                    <p className="text-muted-foreground">
                        System statistics and maintenance tools
                    </p>
                </div>
                <button
                    onClick={loadStats}
                    disabled={loading}
                    className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6">
                    <p className="text-red-800 dark:text-red-400">{error}</p>
                </div>
            )}

            {actionResult && (
                <div className={`border rounded-lg p-4 mb-6 flex items-center gap-3 ${actionResult.status === 'success'
                        ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                        : 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800'
                    }`}>
                    <CheckCircle className="w-5 h-5 text-green-600" />
                    <div>
                        <div className="font-medium">{actionResult.operation}</div>
                        <div className="text-sm text-muted-foreground">{actionResult.message}</div>
                    </div>
                    <button
                        onClick={() => setActionResult(null)}
                        className="ml-auto p-1 hover:bg-black/10 rounded"
                    >
                        ×
                    </button>
                </div>
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

            {/* Vector Store */}
            <div className="mb-8">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Layers className="w-5 h-5" />
                    Vector Store
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <StatCard
                        icon={Layers}
                        label="Collections"
                        value={stats?.vector_store.collections_count ?? 0}
                    />
                    <StatCard
                        icon={Box}
                        label="Total Vectors"
                        value={stats?.vector_store.vectors_total ?? 0}
                    />
                    <StatCard
                        icon={HardDrive}
                        label="Index Size"
                        value={formatBytes(stats?.vector_store.index_size_bytes ?? 0)}
                        isString
                    />
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

            {/* Confirmation Modal */}
            {showConfirm && (
                <ConfirmModal
                    title={showConfirm === 'cache' ? 'Clear Cache?' : 'Prune Orphans?'}
                    message={
                        showConfirm === 'cache'
                            ? 'This will remove all cached data. Queries may be slower until the cache warms up.'
                            : 'This will permanently remove orphan nodes from the graph. This cannot be undone.'
                    }
                    onConfirm={showConfirm === 'cache' ? handleClearCache : handlePruneOrphans}
                    onCancel={() => setShowConfirm(null)}
                />
            )}
        </div>
    )
}

interface StatCardProps {
    icon: React.ComponentType<{ className?: string }>
    label: string
    value: number | string
    subLabel?: string
    isString?: boolean
}

function StatCard({ icon: Icon, label, value, subLabel, isString }: StatCardProps) {
    return (
        <div className="bg-card border rounded-lg p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-2">
                <Icon className="w-4 h-4" />
                <span className="text-sm">{label}</span>
            </div>
            <div className="text-2xl font-bold">
                {isString ? value : typeof value === 'number' ? value.toLocaleString() : value}
            </div>
            {subLabel && (
                <div className="text-sm text-muted-foreground">{subLabel}</div>
            )}
        </div>
    )
}

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
                <div className={`p-3 rounded-lg ${buttonVariant === 'danger' ? 'bg-red-100 dark:bg-red-900/30' : 'bg-yellow-100 dark:bg-yellow-900/30'
                    }`}>
                    <Icon className={`w-6 h-6 ${buttonVariant === 'danger' ? 'text-red-600' : 'text-yellow-600'
                        }`} />
                </div>
                <div className="flex-1">
                    <h3 className="font-medium mb-1">{title}</h3>
                    <p className="text-sm text-muted-foreground mb-4">{description}</p>
                    <button
                        onClick={onClick}
                        disabled={loading}
                        className={`px-4 py-2 rounded-md text-white transition-colors disabled:opacity-50 ${buttonVariant === 'danger'
                                ? 'bg-red-600 hover:bg-red-700'
                                : 'bg-yellow-600 hover:bg-yellow-700'
                            }`}
                    >
                        {loading ? 'Processing...' : buttonText}
                    </button>
                </div>
            </div>
        </div>
    )
}

interface ConfirmModalProps {
    title: string
    message: string
    onConfirm: () => void
    onCancel: () => void
}

function ConfirmModal({ title, message, onConfirm, onCancel }: ConfirmModalProps) {
    return (
        <>
            <div className="fixed inset-0 bg-black/50 z-40" onClick={onCancel} />
            <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-card border rounded-lg p-6 w-full max-w-md z-50">
                <h3 className="text-lg font-semibold mb-2">{title}</h3>
                <p className="text-muted-foreground mb-6">{message}</p>
                <div className="flex gap-3 justify-end">
                    <button
                        onClick={onCancel}
                        className="px-4 py-2 border rounded-md hover:bg-muted transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={onConfirm}
                        className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors"
                    >
                        Confirm
                    </button>
                </div>
            </div>
        </>
    )
}
