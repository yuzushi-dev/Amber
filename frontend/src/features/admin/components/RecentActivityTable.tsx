'use client';

import React, { useState, useMemo, useEffect } from 'react';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { QueryMetrics } from '@/lib/api-admin';
import { ChevronLeft, ChevronRight, FileText, MessageSquare, Database, Zap, CheckCircle, XCircle } from 'lucide-react';

// Operation category mapping based on backend operation types
const OPERATION_INFO: Record<string, { icon: React.ReactNode; variant: 'success' | 'warning' | 'info' | 'destructive' | 'secondary'; label: string }> = {
    'rag_query': { icon: <MessageSquare className="w-3 h-3" />, variant: 'success', label: 'RAG' },
    'chat_query': { icon: <MessageSquare className="w-3 h-3" />, variant: 'info', label: 'Chat' },
    'summarization': { icon: <FileText className="w-3 h-3" />, variant: 'warning', label: 'Summary' },
    'extraction': { icon: <Database className="w-3 h-3" />, variant: 'secondary', label: 'Extraction' },
};

const getOperationInfo = (op: string) => {
    return OPERATION_INFO[op] || { icon: <Zap className="w-3 h-3" />, variant: 'secondary' as const, label: op || 'Unknown' };
};

// Simple time ago helper
function timeAgo(date: Date) {
    const seconds = Math.floor((new Date().getTime() - date.getTime()) / 1000);
    let interval = seconds / 86400;
    if (interval > 1) return Math.floor(interval) + "d ago";
    interval = seconds / 3600;
    if (interval > 1) return Math.floor(interval) + "h ago";
    interval = seconds / 60;
    if (interval > 1) return Math.floor(interval) + "m ago";
    return "just now";
}

interface RecentActivityTableProps {
    records: QueryMetrics[];
    isLoading?: boolean;
}

export default function RecentActivityTable({ records, isLoading = false }: RecentActivityTableProps) {
    const [page, setPage] = useState(1);
    const pageSize = 5;

    // Reset to page 1 when records change
    useEffect(() => {
        setPage(1);
    }, [records?.length]);

    const totalPages = Math.ceil((records?.length || 0) / pageSize);
    const paginatedRecords = useMemo(() => {
        if (!records) return [];
        const start = (page - 1) * pageSize;
        return records.slice(start, start + pageSize);
    }, [records, page]);

    if (isLoading) {
        return (
            <Card className="p-6">
                <div className="flex items-center justify-center py-8 text-neutral-400">
                    Loading activity...
                </div>
            </Card>
        );
    }

    if (!records || records.length === 0) {
        return (
            <Card className="p-6">
                <div className="flex items-center justify-center py-8 text-neutral-400">
                    No recent activity found.
                </div>
            </Card>
        );
    }

    return (
        <Card className="overflow-hidden border-neutral-800 bg-neutral-900/50">
            <div className="overflow-x-auto">
                <Table>
                    <TableHeader className="bg-neutral-900">
                        <TableRow className="border-neutral-800 hover:bg-neutral-900">
                            <TableHead className="w-[100px]">Time</TableHead>
                            <TableHead className="w-[100px]">Type</TableHead>
                            <TableHead className="min-w-[200px]">Input</TableHead>
                            <TableHead className="min-w-[200px]">Output</TableHead>
                            <TableHead className="text-right">Tokens</TableHead>
                            <TableHead className="text-right">Cost</TableHead>
                            <TableHead className="text-right">Latency</TableHead>
                            <TableHead className="w-[100px]">Model</TableHead>
                            <TableHead className="w-[80px]">Status</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {paginatedRecords.map((row) => {
                            const info = getOperationInfo(row.operation);
                            const time = new Date(row.timestamp);
                            const costColor = row.cost_estimate < 0.001 ? 'text-emerald-400' : row.cost_estimate < 0.01 ? 'text-amber-400' : 'text-red-400';

                            return (
                                <TableRow key={row.query_id} className="border-neutral-800 hover:bg-neutral-800/50">
                                    {/* Time */}
                                    <TableCell className="whitespace-nowrap font-mono text-xs text-neutral-400">
                                        <div title={time.toLocaleString()}>
                                            {timeAgo(time)}
                                        </div>
                                    </TableCell>

                                    {/* Type Badge */}
                                    <TableCell>
                                        <Badge variant={info.variant} className="gap-1">
                                            {info.icon}
                                            {info.label}
                                        </Badge>
                                    </TableCell>

                                    {/* Input (Query) */}
                                    <TableCell>
                                        <div className="max-w-[250px] truncate text-sm" title={row.query}>
                                            {row.query || '-'}
                                        </div>
                                    </TableCell>

                                    {/* Output (Response) */}
                                    <TableCell>
                                        <div className="max-w-[250px] truncate text-sm text-neutral-400" title={row.response || ''}>
                                            {row.response || <span className="text-neutral-500 italic">No output</span>}
                                        </div>
                                    </TableCell>

                                    {/* Tokens */}
                                    <TableCell className="text-right">
                                        <div className="font-mono text-xs">
                                            {row.tokens_used?.toLocaleString() || 0}
                                        </div>
                                        <div className="text-[10px] text-neutral-500">
                                            {row.input_tokens || 0} / {row.output_tokens || 0}
                                        </div>
                                    </TableCell>

                                    {/* Cost */}
                                    <TableCell className="text-right">
                                        <div className={`font-mono text-xs ${costColor}`}>
                                            ${row.cost_estimate?.toFixed(4) || '0.0000'}
                                        </div>
                                    </TableCell>

                                    {/* Latency */}
                                    <TableCell className="text-right">
                                        <div className="font-mono text-xs">
                                            {Math.round(row.total_latency_ms || 0)}ms
                                        </div>
                                    </TableCell>

                                    {/* Model */}
                                    <TableCell>
                                        <div className="text-xs font-medium">{row.model || '-'}</div>
                                        <div className="text-[10px] text-neutral-500">{row.provider || ''}</div>
                                    </TableCell>

                                    {/* Status */}
                                    <TableCell>
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
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-neutral-800 bg-neutral-900/30">
                    <div className="text-xs text-neutral-500">
                        Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, records.length)} of {records.length}
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
    );
}
