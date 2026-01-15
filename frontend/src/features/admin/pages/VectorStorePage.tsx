/**
 * Vector Store Page
 * =================
 *
 * Vector database statistics and collection management.
 */

import { Layers, Box, HardDrive, RefreshCw, Database } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { vectorStoreApi } from '@/lib/api-admin'
import { Button } from '@/components/ui/button'
import { StatCard } from '@/components/ui/StatCard'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'

export default function VectorStorePage() {
    // Use React Query with caching and auto-refresh
    const { data, isLoading: loading, error, refetch } = useQuery({
        queryKey: ['vector-collections'],
        queryFn: () => vectorStoreApi.getCollections(),
        staleTime: 30000, // Cache for 30 seconds
        refetchInterval: 30000, // Auto-refresh every 30 seconds
    })

    const collections = data?.collections ?? []

    const formatBytes = (bytes: number) => {
        if (bytes === 0) return '0 B'
        const k = 1024
        const sizes = ['B', 'KB', 'MB', 'GB']
        const i = Math.floor(Math.log(bytes) / Math.log(k))
        return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
    }

    const formatNumber = (num: number) => {
        return num.toLocaleString()
    }

    // Calculate totals
    const totalCollections = collections.length
    const totalVectors = collections.reduce((sum, col) => sum + col.count, 0)
    const totalMemoryMB = collections.reduce((sum, col) => sum + col.memory_mb, 0)

    if (loading && collections.length === 0) {
        return <PageSkeleton />
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="Vector Store"
                description="Vector database collections and statistics."
                actions={
                    <Button
                        variant="outline"
                        onClick={() => refetch()}
                        disabled={loading}
                        className="gap-2 h-9 text-xs"
                    >
                        <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                        Refresh
                    </Button>
                }
            />

            {error && (
                <Alert variant="destructive" className="mb-6">
                    <AlertDescription>{error instanceof Error ? error.message : 'Failed to load vector store'}</AlertDescription>
                </Alert>
            )}

            {/* Overview Stats */}
            <div className="mb-8">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Database className="w-5 h-5" />
                    Overview
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <StatCard
                        icon={Layers}
                        label="Collections"
                        value={totalCollections}
                    />
                    <StatCard
                        icon={Box}
                        label="Total Vectors"
                        value={totalVectors}
                    />
                    <StatCard
                        icon={HardDrive}
                        label="Memory Usage"
                        value={formatBytes(totalMemoryMB * 1024 * 1024)}
                        isString
                    />
                </div>
            </div>

            {/* Collections Table */}
            <div>
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Layers className="w-5 h-5" />
                    Collections
                </h2>

                {collections.length === 0 ? (
                    <div className="bg-card border rounded-lg p-8 text-center">
                        <Database className="w-12 h-12 mx-auto mb-3 text-muted-foreground/50" />
                        <p className="text-muted-foreground">No vector collections found</p>
                    </div>
                ) : (
                    <div className="bg-card border rounded-lg overflow-hidden">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Collection Name</TableHead>
                                    <TableHead className="text-right">Vector Count</TableHead>
                                    <TableHead className="text-right">Dimensions</TableHead>
                                    <TableHead>Index Type</TableHead>
                                    <TableHead className="text-right">Memory</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {collections.map((collection) => (
                                    <TableRow key={collection.name}>
                                        <TableCell className="font-medium">
                                            {collection.name}
                                        </TableCell>
                                        <TableCell className="text-right font-mono">
                                            {formatNumber(collection.count)}
                                        </TableCell>
                                        <TableCell className="text-right font-mono">
                                            {collection.dimensions ?? '—'}
                                        </TableCell>
                                        <TableCell>
                                            <span className="px-2 py-1 bg-secondary rounded text-xs font-mono">
                                                {collection.index_type ?? 'Unknown'}
                                            </span>
                                        </TableCell>
                                        <TableCell className="text-right font-mono">
                                            {formatBytes(collection.memory_mb * 1024 * 1024)}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                )}
            </div>

            {/* Auto-refresh indicator */}
            <div className="mt-6 text-center text-sm text-muted-foreground">
                Auto-refreshing every 30 seconds
            </div>
        </div>
    )
}
