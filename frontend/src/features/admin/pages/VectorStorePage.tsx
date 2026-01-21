/**
 * Vector Store Page
 * =================
 *
 * Vector database collections and statistics.
 * UI aligned with DocumentLibrary design patterns.
 */

import { useState } from 'react'
import { Layers, Box, HardDrive, RefreshCw, Database, Cpu, Trash2 } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearch } from '@tanstack/react-router'
import { motion, AnimatePresence } from 'framer-motion'
import { vectorStoreApi } from '@/lib/api-admin'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { PageSkeleton } from '../components/PageSkeleton'
import { EmbeddingMigration } from '../components/EmbeddingMigration'
import EmptyState from '@/components/ui/EmptyState'
import { toast } from 'sonner'


export default function VectorStorePage() {
    // Get query params for auto-migration
    const search = useSearch({ strict: false }) as { autoMigrate?: string; tenantId?: string }
    const autoMigrate = search.autoMigrate === 'true'
    const tenantId = search.tenantId || 'default'

    const { data, isLoading: loading, error, refetch } = useQuery({
        queryKey: ['vector-collections'],
        queryFn: () => vectorStoreApi.getCollections(),
        staleTime: 30000,
        refetchInterval: 30000,
    })

    const queryClient = useQueryClient()
    const [pendingDelete, setPendingDelete] = useState<string | null>(null)

    const deleteMutation = useMutation({
        mutationFn: (collectionName: string) => vectorStoreApi.deleteCollection(collectionName),
        onSuccess: (result) => {
            toast.success(result.message)
            queryClient.invalidateQueries({ queryKey: ['vector-collections'] })
            setPendingDelete(null)
        },
        onError: (err) => {
            toast.error(err instanceof Error ? err.message : 'Failed to delete collection')
            setPendingDelete(null)
        }
    })

    const handleDelete = (collectionName: string) => {
        if (pendingDelete === collectionName) {
            // Second click = confirm
            deleteMutation.mutate(collectionName)
        } else {
            // First click = show confirm state
            setPendingDelete(collectionName)
            // Auto-reset after 3 seconds
            setTimeout(() => setPendingDelete(null), 3000)
        }
    }

    const collections = data?.collections ?? []


    const formatBytes = (bytes: number) => {
        if (bytes === 0) return '0 B'
        const k = 1024
        const sizes = ['B', 'KB', 'MB', 'GB']
        const i = Math.floor(Math.log(bytes) / Math.log(k))
        return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
    }

    const formatNumber = (num: number) => num.toLocaleString()

    // Calculate totals
    const totalCollections = collections.length
    const totalVectors = collections.reduce((sum, col) => sum + col.count, 0)
    const totalMemoryMB = collections.reduce((sum, col) => sum + col.memory_mb, 0)

    if (loading && collections.length === 0) {
        return <PageSkeleton mode="list" />
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            {/* Embedding Migration Alert */}
            <EmbeddingMigration
                autoMigrate={autoMigrate}
                tenantId={tenantId}
                onMigrationComplete={() => refetch()}
            />

            {/* Header */}
            <header className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-display font-bold tracking-tight">Vector Store</h1>
                    <p className="text-muted-foreground mt-1">Manage your vector database collections.</p>
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        variant="outline"
                        onClick={() => refetch()}
                        disabled={loading}
                        className="gap-2"
                    >
                        <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
                        Refresh
                    </Button>
                </div>
            </header>

            {/* Error Alert */}
            {error && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="p-4 rounded-xl border border-destructive/50 bg-destructive/10 text-destructive"
                >
                    {error instanceof Error ? error.message : 'Failed to load vector store'}
                </motion.div>
            )}

            {/* Glass Stats Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {[
                    {
                        label: 'Collections',
                        value: totalCollections,
                        icon: Layers,
                        color: 'text-blue-400',
                        gradient: 'from-blue-500/20 to-blue-600/5'
                    },
                    {
                        label: 'Total Vectors',
                        value: totalVectors,
                        icon: Box,
                        color: 'text-purple-400',
                        gradient: 'from-purple-500/20 to-purple-600/5'
                    },
                    {
                        label: 'Memory Usage',
                        value: formatBytes(totalMemoryMB * 1024 * 1024),
                        icon: HardDrive,
                        color: 'text-green-400',
                        gradient: 'from-green-500/20 to-green-600/5',
                        isString: true
                    },
                    {
                        label: 'Dimensions',
                        value: collections[0]?.dimensions ?? '—',
                        icon: Cpu,
                        color: 'text-orange-400',
                        gradient: 'from-orange-500/20 to-orange-600/5',
                        isString: true
                    }
                ].map((card, idx) => (
                    <motion.div
                        key={card.label}
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: idx * 0.05 }}
                        className="relative overflow-hidden p-5 rounded-xl border border-white/5 bg-background/40 backdrop-blur-md shadow-lg group"
                    >
                        <div className={`absolute inset-0 bg-gradient-to-br ${card.gradient} opacity-0 group-hover:opacity-100 transition-opacity duration-500`} />
                        <div className="relative z-10 flex flex-col h-full justify-between">
                            <div className="flex justify-between items-start mb-2">
                                <p className="text-sm font-medium text-muted-foreground/80">{card.label}</p>
                                <card.icon className={cn("w-5 h-5", card.color)} />
                            </div>
                            <h2 className="text-3xl font-display font-bold tracking-tight">
                                {card.isString ? card.value : formatNumber(card.value as number)}
                            </h2>
                        </div>
                    </motion.div>
                ))}
            </div>

            {/* Collections Section */}
            <div className="space-y-4">
                {/* Section Header Bar */}
                <div className="p-2 rounded-xl border border-white/5 bg-black/20 backdrop-blur-md flex justify-between items-center shadow-inner">
                    <div className="flex items-center gap-2 px-3 text-sm text-muted-foreground">
                        <Database className="w-4 h-4" />
                        <span>{totalCollections} collection{totalCollections !== 1 ? 's' : ''}</span>
                    </div>
                    <div className="text-xs text-muted-foreground/60 pr-3">
                        Auto-refresh: 30s
                    </div>
                </div>

                {collections.length === 0 ? (
                    <EmptyState
                        icon={<Layers className="w-12 h-12 text-muted-foreground" />}
                        title="No vector collections"
                        description="Vector collections will appear here once documents are ingested."
                    />
                ) : (
                    <div className="space-y-2">
                        {/* Header Row */}
                        <div className="grid grid-cols-[2fr_100px_100px_120px_100px_80px] gap-4 px-6 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider opacity-60">
                            <div>Collection</div>
                            <div className="text-right">Vectors</div>
                            <div className="text-right">Dimensions</div>
                            <div>Index Type</div>
                            <div className="text-right">Memory</div>
                            <div className="text-right">Actions</div>
                        </div>

                        {/* Collection Rows */}
                        <ul className="space-y-2">
                            <AnimatePresence mode="popLayout">
                                {collections.map((collection, idx) => (
                                    <motion.li
                                        key={collection.name}
                                        layout
                                        initial={{ opacity: 0, x: -10 }}
                                        animate={{ opacity: 1, x: 0 }}
                                        exit={{ opacity: 0, scale: 0.95 }}
                                        transition={{ duration: 0.2, delay: idx * 0.03 }}
                                        className="group"
                                    >
                                        <div className="grid grid-cols-[2fr_100px_100px_120px_100px_80px] gap-4 items-center p-4 rounded-lg bg-background/40 backdrop-blur-sm border border-white/5 hover:bg-background/60 hover:border-white/10 hover:shadow-lg transition-all duration-300">
                                            {/* Collection Name */}
                                            <div className="flex items-center gap-4 min-w-0">
                                                <div className="p-2.5 rounded-lg bg-primary/10 text-primary ring-1 ring-primary/20 shrink-0">
                                                    <Layers className="w-5 h-5" />
                                                </div>
                                                <div className="min-w-0">
                                                    <span className="font-medium text-base block truncate">
                                                        {collection.name}
                                                    </span>
                                                </div>
                                            </div>

                                            {/* Vector Count */}
                                            <div className="text-right font-mono text-sm">
                                                {formatNumber(collection.count)}
                                            </div>

                                            {/* Dimensions */}
                                            <div className="text-right font-mono text-sm text-muted-foreground">
                                                {collection.dimensions ?? '—'}
                                            </div>

                                            {/* Index Type */}
                                            <div>
                                                <span className="px-2 py-1 bg-secondary/50 rounded text-xs font-mono">
                                                    {collection.index_type ?? 'Unknown'}
                                                </span>
                                            </div>

                                            {/* Memory */}
                                            <div className="text-right font-mono text-sm text-muted-foreground">
                                                {formatBytes(collection.memory_mb * 1024 * 1024)}
                                            </div>

                                            {/* Delete Button */}
                                            <div className="text-right">
                                                <Button
                                                    variant={pendingDelete === collection.name ? "destructive" : "ghost"}
                                                    size="sm"
                                                    onClick={() => handleDelete(collection.name)}
                                                    disabled={deleteMutation.isPending}
                                                    className="h-8 w-8 p-0"
                                                    title={pendingDelete === collection.name ? "Click again to confirm" : "Delete collection"}
                                                >
                                                    <Trash2 className="w-4 h-4" />
                                                </Button>
                                            </div>
                                        </div>
                                    </motion.li>
                                ))}
                            </AnimatePresence>
                        </ul>
                    </div>
                )}
            </div>
        </div>
    )
}
