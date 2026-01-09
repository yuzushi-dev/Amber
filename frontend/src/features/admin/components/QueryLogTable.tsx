import { useState } from 'react'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { QueryMetrics } from '@/lib/api-admin'
import { ChevronLeft, ChevronRight, XCircle, CheckCircle } from 'lucide-react'

// Simple time ago helper
function timeAgo(date: Date) {
    const seconds = Math.floor((new Date().getTime() - date.getTime()) / 1000)
    let interval = seconds / 31536000
    if (interval > 1) return Math.floor(interval) + " years ago"
    interval = seconds / 2592000
    if (interval > 1) return Math.floor(interval) + " months ago"
    interval = seconds / 86400
    if (interval > 1) return Math.floor(interval) + " days ago"
    interval = seconds / 3600
    if (interval > 1) return Math.floor(interval) + " hours ago"
    interval = seconds / 60
    if (interval > 1) return Math.floor(interval) + " minutes ago"
    return Math.floor(seconds) + " seconds ago"
}

interface QueryLogTableProps {
    data: QueryMetrics[]
    isLoading?: boolean
}

export function QueryLogTable({ data, isLoading }: QueryLogTableProps) {
    const [page, setPage] = useState(1)
    const pageSize = 15

    const totalPages = Math.ceil(data.length / pageSize)
    const paginatedData = data.slice((page - 1) * pageSize, page * pageSize)

    if (isLoading) {
        return (
            <Card className="p-6">
                <div className="flex items-center justify-center py-8 text-neutral-400">
                    Loading query logs...
                </div>
            </Card>
        )
    }

    if (data.length === 0) {
        return (
            <Card className="p-6">
                <div className="flex items-center justify-center py-8 text-neutral-400">
                    No query logs found.
                </div>
            </Card>
        )
    }

    return (
        <Card className="overflow-hidden border-neutral-800 bg-neutral-900/50">
            <div className="overflow-x-auto">
                <Table>
                    <TableHeader className="bg-neutral-900">
                        <TableRow className="border-neutral-800 hover:bg-neutral-900">
                            <TableHead className="w-[180px]">Time</TableHead>
                            <TableHead className="w-[100px]">Status</TableHead>
                            <TableHead className="min-w-[300px]">Query</TableHead>
                            <TableHead className="text-right">Latency</TableHead>
                            <TableHead className="text-right">Tokens</TableHead>
                            <TableHead className="text-right">Cost</TableHead>
                            <TableHead className="w-[120px]">Model</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {paginatedData.map((row) => (
                            <TableRow key={row.query_id} className="border-neutral-800 hover:bg-neutral-800/50">
                                <TableCell className="whitespace-nowrap font-mono text-xs text-neutral-400">
                                    <div title={new Date(row.timestamp).toLocaleString()}>
                                        {timeAgo(new Date(row.timestamp))}
                                    </div>
                                    <div className="text-[10px] text-neutral-500 truncate w-24">
                                        {row.query_id}
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <div className="flex items-center gap-2">
                                        {row.success ? (
                                            <Badge variant="outline" className="border-green-500/30 text-green-400 bg-green-500/10">
                                                <CheckCircle className="w-3 h-3 mr-1" />
                                                OK
                                            </Badge>
                                        ) : (
                                            <Badge variant="outline" className="border-red-500/30 text-red-400 bg-red-500/10">
                                                <XCircle className="w-3 h-3 mr-1" />
                                                ERR
                                            </Badge>
                                        )}
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <div className="max-w-[400px]">
                                        <div className="font-medium truncate" title={row.query}>
                                            {row.query}
                                        </div>
                                        {row.error_message && (
                                            <div className="text-xs text-red-400 mt-1 truncate" title={row.error_message}>
                                                {row.error_message}
                                            </div>
                                        )}
                                        {row.conversation_id && (
                                            <div className="text-[10px] text-neutral-500 mt-0.5 truncate font-mono">
                                                Conv: {row.conversation_id}
                                            </div>
                                        )}
                                    </div>
                                </TableCell>
                                <TableCell className="text-right">
                                    <div className="font-mono text-xs">
                                        <span className={row.total_latency_ms > 2000 ? 'text-amber-400' : ''}>
                                            {Math.round(row.total_latency_ms)}ms
                                        </span>
                                    </div>
                                    <div className="text-[10px] text-neutral-500">
                                        Ret: {Math.round(row.retrieval_latency_ms)} / Gen: {Math.round(row.generation_latency_ms)}
                                    </div>
                                </TableCell>
                                <TableCell className="text-right">
                                    <div className="font-mono text-xs">
                                        {row.tokens_used.toLocaleString()}
                                    </div>
                                    <div className="text-[10px] text-neutral-500" title="Input / Output">
                                        {row.input_tokens.toLocaleString()} / {row.output_tokens.toLocaleString()}
                                    </div>
                                </TableCell>
                                <TableCell className="text-right">
                                    <div className={`font-mono text-xs ${row.cost_estimate > 0.01 ? 'text-amber-400' : 'text-neutral-300'}`}>
                                        ${row.cost_estimate.toFixed(4)}
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <div className="text-xs font-medium">{row.model || '-'}</div>
                                    <div className="text-[10px] text-neutral-500">{row.provider || '-'}</div>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-neutral-800 bg-neutral-900/30">
                    <div className="text-xs text-neutral-500">
                        Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, data.length)} of {data.length} entries
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setPage(p => Math.max(1, p - 1))}
                            disabled={page === 1}
                            className="p-1 rounded hover:bg-neutral-800 disabled:opacity-30 disabled:cursor-not-allowed"
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </button>
                        <span className="text-xs text-neutral-400">
                            Page {page} of {totalPages}
                        </span>
                        <button
                            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                            disabled={page === totalPages}
                            className="p-1 rounded hover:bg-neutral-800 disabled:opacity-30 disabled:cursor-not-allowed"
                        >
                            <ChevronRight className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            )}
        </Card>
    )
}
