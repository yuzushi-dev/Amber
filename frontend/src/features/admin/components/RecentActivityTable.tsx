'use client';

import { useState, useMemo } from 'react';
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
import { Button } from '@/components/ui/button';
import { ChatHistoryItem } from '@/lib/api-admin';
import { ChevronLeft, ChevronRight, ShieldAlert, ThumbsUp, ThumbsDown } from 'lucide-react';
import { ChatDetailDialog } from './ChatDetailDialog';

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
    records: ChatHistoryItem[];
    isLoading?: boolean;
}

export default function RecentActivityTable({ records, isLoading = false }: RecentActivityTableProps) {
    // Use records.length as key to reset page when records change
    const recordsKey = records?.length ?? 0;
    const [page, setPage] = useState(1);
    const [prevRecordsKey, setPrevRecordsKey] = useState(recordsKey);
    const [selectedChatId, setSelectedChatId] = useState<string | null>(null);

    // Reset page when records change (before render, not in effect)
    if (recordsKey !== prevRecordsKey) {
        setPage(1);
        setPrevRecordsKey(recordsKey);
    }

    const pageSize = 10;

    const totalPages = Math.ceil((records?.length || 0) / pageSize);
    const paginatedRecords = useMemo(() => {
        if (!records) return [];
        const start = (page - 1) * pageSize;
        return records.slice(start, start + pageSize);
    }, [records, page]);

    if (isLoading) {
        return (
            <Card className="p-6">
                <div className="flex items-center justify-center py-8 text-muted-foreground">
                    Loading chat activity...
                </div>
            </Card>
        );
    }

    if (!records || records.length === 0) {
        return (
            <Card className="p-6">
                <div className="flex items-center justify-center py-8 text-muted-foreground">
                    No recent chat activity found.
                </div>
            </Card>
        );
    }

    return (
        <Card className="overflow-hidden border-border bg-card/50">
            <div className="overflow-x-auto">
                <Table>
                    <TableHeader className="bg-muted/40">
                        <TableRow className="border-border hover:bg-muted/30">
                            <TableHead className="w-[100px]">Time</TableHead>
                            <TableHead className="w-[120px]">Gruppo</TableHead>
                            <TableHead className="min-w-[200px]">Query</TableHead>
                            <TableHead className="min-w-[200px]">Response</TableHead>
                            <TableHead className="w-[100px] text-center">Feedback</TableHead>
                            <TableHead className="text-right">Tokens</TableHead>
                            <TableHead className="text-right">Cost</TableHead>
                            <TableHead className="w-[100px]">Model</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {paginatedRecords.map((row) => {
                            const time = new Date(row.created_at);
                            const costColor = row.cost < 0.001 ? 'text-success' : row.cost < 0.01 ? 'text-warning' : 'text-destructive';

                            const isRedacted = row.query_text === "[REDACTED - PRIVACY]";

                            return (
                                <TableRow 
                                    key={row.request_id} 
                                    className="border-border hover:bg-muted/20 cursor-pointer transition-colors"
                                    onClick={() => setSelectedChatId(row.request_id)}
                                >
                                    {/* Time */}
                                    <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                                        <div title={time.toLocaleString()}>
                                            {timeAgo(time)}
                                        </div>
                                    </TableCell>

                                    {/* Gruppo */}
                                    <TableCell>
                                        {row.group_name ? (
                                            <Badge variant="outline" className="text-[10px] truncate max-w-[110px]" title={row.group_name}>
                                                {row.group_name}
                                            </Badge>
                                        ) : (
                                            <span className="text-xs text-muted-foreground/50">—</span>
                                        )}
                                    </TableCell>

                                    {/* Input (Query) */}
                                    <TableCell>
                                        <div className="max-w-[250px] truncate text-sm" title={isRedacted ? 'Redacted' : row.query_text || ''}>
                                            {isRedacted ? (
                                                <span className="text-muted-foreground/70 italic flex items-center gap-1">
                                                    <ShieldAlert className="w-3 h-3" /> Redacted
                                                </span>
                                            ) : (
                                                row.query_text || '-'
                                            )}
                                        </div>
                                    </TableCell>

                                    {/* Output (Response) */}
                                    <TableCell>
                                        <div className="max-w-[250px] truncate text-sm text-muted-foreground" title={isRedacted ? 'Redacted' : row.response_preview || ''}>
                                            {isRedacted ? (
                                                <span className="text-muted-foreground/70 italic flex items-center gap-1">
                                                    <ShieldAlert className="w-3 h-3" /> Redacted
                                                </span>
                                            ) : (
                                                row.response_preview || '-'
                                            )}
                                        </div>
                                    </TableCell>

                                    {/* Feedback */}
                                    <TableCell className="text-center">
                                        {row.has_feedback ? (
                                            row.feedback_positive === false ? (
                                                <Badge variant="outline" className="border-destructive/30 text-destructive bg-destructive/10 gap-1">
                                                    <ThumbsDown className="w-3 h-3" fill="currentColor" />
                                                    Neg
                                                </Badge>
                                            ) : row.feedback_positive === true ? (
                                                <Badge variant="outline" className="border-success/30 text-success bg-success/10 gap-1">
                                                    <ThumbsUp className="w-3 h-3" fill="currentColor" />
                                                    Pos
                                                </Badge>
                                            ) : (
                                                // feedback present but sign unknown (e.g. multi-turn non-first row)
                                                <Badge variant="outline" className="border-muted-foreground/30 text-muted-foreground bg-muted/10 gap-1">
                                                    Yes
                                                </Badge>
                                            )
                                        ) : (
                                            <span className="text-xs text-muted-foreground/50">-</span>
                                        )}
                                    </TableCell>

                                    {/* Tokens */}
                                    <TableCell className="text-right">
                                        <div className="font-mono text-xs">
                                            {row.total_tokens?.toLocaleString() || 0}
                                        </div>
                                    </TableCell>

                                    {/* Cost */}
                                    <TableCell className="text-right">
                                        <div className={`font-mono text-xs ${costColor}`}>
                                            ${row.cost?.toFixed(4) || '0.0000'}
                                        </div>
                                    </TableCell>

                                    {/* Model */}
                                    <TableCell>
                                        <div className="text-xs font-medium truncate max-w-[80px]" title={row.model}>{row.model || '-'}</div>
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-muted/30">
                    <div className="text-xs text-muted-foreground/70">
                        Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, records.length)} of {records.length}
                    </div>
                    <div className="flex items-center gap-2">
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setPage(p => Math.max(1, p - 1))}
                            disabled={page === 1}
                            className="h-8 w-8"
                            aria-label="Previous page"
                        >
                            <ChevronLeft className="w-4 h-4" />
                        </Button>
                        <span className="text-xs text-muted-foreground">
                            Page {page} of {totalPages}
                        </span>
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                            disabled={page === totalPages}
                            className="h-8 w-8"
                            aria-label="Next page"
                        >
                            <ChevronRight className="w-4 h-4" />
                        </Button>
                    </div>
                </div>
            )}

            {/* Chat Detail Dialog */}
            <ChatDetailDialog
                open={!!selectedChatId}
                onOpenChange={(open) => !open && setSelectedChatId(null)}
                requestId={selectedChatId}
            />
        </Card>
    );
}
