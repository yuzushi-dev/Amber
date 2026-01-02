/**
 * Vector Store Page
 * =================
 *
 * Vector database statistics and collection management.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { Layers, Box, HardDrive, RefreshCw, Database } from 'lucide-react'
import { vectorStoreApi, VectorCollectionInfo } from '@/lib/api-admin'
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

export default function VectorStorePage() {
    const [collections, setCollections] = useState<VectorCollectionInfo[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const loadCollections = useCallback(async () => {
        try {
            setLoading(true)
            const data = await vectorStoreApi.getCollections()
            setCollections(data.collections)
            setError(null)
        } catch (err) {
            setError('Failed to load vector store statistics')
            console.error(err)
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        loadCollections()

        // Auto-refresh every 30 seconds
        const interval = setInterval(() => {
            loadCollections()
        }, 30000)

        return () => clearInterval(interval)
    }, [loadCollections])

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
                    <h1 className="text-2xl font-bold">Vector Store</h1>
                    <p className="text-muted-foreground">
                        Vector database collections and statistics
                    </p>
                </div>
                <button
                    onClick={loadCollections}
                    disabled={loading}
                    className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

            {error && (
                <Alert variant="destructive" className="mb-6">
                    <AlertDescription>{error}</AlertDescription>
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
