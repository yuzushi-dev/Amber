'use client';

import React, { useEffect, useState } from 'react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogBody,
    DialogFooter,
    DialogClose,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2, User, Bot, AlertTriangle, ShieldAlert, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import { chatHistoryApi } from '@/lib/api-admin';
import { ConversationDetail } from '@/lib/api-admin';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

interface ChatDetailDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    requestId: string | null;
}

export function ChatDetailDialog({ open, onOpenChange, requestId }: ChatDetailDialogProps) {
    const [detail, setDetail] = useState<ConversationDetail | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [expandedSource, setExpandedSource] = useState<number | null>(null);

    useEffect(() => {
        if (open && requestId) {
            let isMounted = true;
            setIsLoading(true);
            setError(null);
            
            chatHistoryApi.getDetail(requestId)
                .then((data) => {
                    if (isMounted) {
                        setDetail(data);
                        setIsLoading(false);
                    }
                })
                .catch((err) => {
                    if (isMounted) {
                        console.error('Failed to load chat detail', err);
                        setError('Failed to load conversation details. It may have been deleted or you do not have permission.');
                        setIsLoading(false);
                    }
                });

            return () => {
                isMounted = false;
            };
        } else if (!open) {
            // Reset state on close
            setTimeout(() => {
                setDetail(null);
                setError(null);
                setExpandedSource(null);
            }, 300);
        }
    }, [open, requestId]);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-3xl h-[85vh] flex flex-col">
                <DialogHeader className="flex-shrink-0">
                    <DialogTitle className="flex items-center justify-between pr-8">
                        <span>Conversation Details</span>
                        {detail && (
                            <Badge variant="outline" className="font-mono text-xs">
                                {detail.tenant_id}
                            </Badge>
                        )}
                    </DialogTitle>
                    <DialogClose onClose={() => onOpenChange(false)} />
                </DialogHeader>

                <DialogBody className="flex-grow overflow-hidden flex flex-col p-0">
                    {isLoading ? (
                        <div className="flex-grow flex items-center justify-center">
                            <Loader2 className="w-8 h-8 animate-spin text-muted-foreground/50" />
                        </div>
                    ) : error ? (
                        <div className="flex-grow flex flex-col items-center justify-center p-6 text-center text-muted-foreground">
                            <AlertTriangle className="w-10 h-10 mb-4 text-warning" />
                            <p>{error}</p>
                        </div>
                    ) : detail ? (
                        <ScrollArea className="flex-grow h-full p-6">
                            <div className="space-y-6 pb-6">
                                {/* Meta Information */}
                                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground mb-4">
                                    <Badge variant="secondary">Model: {detail.model}</Badge>
                                    <Badge variant="secondary">ID: {detail.request_id}</Badge>
                                    <span>{new Date(detail.created_at).toLocaleString()}</span>
                                </div>

                                {/* User Query */}
                                <div className="space-y-2">
                                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                                        <User className="w-4 h-4" />
                                        <span>User Query</span>
                                    </div>
                                    <div className="bg-muted/30 p-4 rounded-lg text-sm border border-border/50">
                                        {detail.query_text === "[REDACTED - PRIVACY]" ? (
                                            <div className="flex items-center gap-2 text-muted-foreground italic">
                                                <ShieldAlert className="w-4 h-4" />
                                                Content redacted for privacy (no user feedback)
                                            </div>
                                        ) : (
                                            <div className="whitespace-pre-wrap">{detail.query_text}</div>
                                        )}
                                    </div>
                                </div>

                                {/* Assistant Response */}
                                <div className="space-y-2">
                                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                                        <Bot className="w-4 h-4" />
                                        <span>Assistant Response</span>
                                    </div>
                                    <div className="bg-primary/5 p-4 rounded-lg text-sm border border-primary/10">
                                        {detail.response_text === "[REDACTED - PRIVACY]" ? (
                                            <div className="flex items-center gap-2 text-muted-foreground italic">
                                                <ShieldAlert className="w-4 h-4" />
                                                Content redacted for privacy (no user feedback)
                                            </div>
                                        ) : (
                                            <div className="whitespace-pre-wrap">{detail.response_text}</div>
                                        )}
                                    </div>
                                </div>

                                {/* Sources */}
                                {detail.sources && detail.sources.length > 0 && (
                                    <div className="space-y-2 mt-6">
                                        <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                                            <svg className="w-4 h-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path></svg>
                                            <span>Sources</span>
                                        </div>
                                        <div className="grid grid-cols-1 gap-2">
                                            {detail.sources.map((source, idx) => {
                                                const isRule = source.document_id?.startsWith('rule_doc_') || source.document_id?.startsWith('global_rule_');
                                                const isMemory = source.document_id?.startsWith('user_fact_');
                                                const isExpanded = expandedSource === idx;

                                                return (
                                                    <div 
                                                        key={idx} 
                                                        className={cn(
                                                            "bg-muted/20 rounded-lg border border-border/50 text-xs transition-all",
                                                            (isRule || isMemory) && "cursor-pointer hover:bg-muted/30"
                                                        )}
                                                        onClick={() => {
                                                            if (isRule || isMemory) {
                                                                setExpandedSource(isExpanded ? null : idx);
                                                            }
                                                        }}
                                                    >
                                                        <div className="p-3">
                                                            <div className="font-semibold mb-1 flex items-center justify-between">
                                                                <div className="flex items-center gap-2">
                                                                    {isRule ? (
                                                                        <Badge variant="outline" className="text-[10px] h-4 bg-orange-500/10 text-orange-600 border-orange-500/20">Rule</Badge>
                                                                    ) : isMemory ? (
                                                                        <Badge variant="outline" className="text-[10px] h-4 bg-purple-500/10 text-purple-600 border-purple-500/20">Memory</Badge>
                                                                    ) : (
                                                                        <Badge variant="outline" className="text-[10px] h-4 bg-blue-500/10 text-blue-600 border-blue-500/20">Doc</Badge>
                                                                    )}
                                                                    <span className="truncate max-w-[200px]">{source.title || `Source ${idx + 1}`}</span>
                                                                </div>
                                                                <div className="flex items-center gap-2">
                                                                    {source.index && <Badge variant="secondary" className="text-[10px] h-4 leading-tight">[{source.index}]</Badge>}
                                                                    {!isRule && !isMemory && source.document_id && (
                                                                        <a 
                                                                            href={`/admin/data/documents/${source.document_id}`} 
                                                                            target="_blank" 
                                                                            rel="noopener noreferrer"
                                                                            className="text-muted-foreground hover:text-primary transition-colors"
                                                                            onClick={(e) => e.stopPropagation()}
                                                                        >
                                                                            <ExternalLink className="w-3 h-3" />
                                                                        </a>
                                                                    )}
                                                                    {(isRule || isMemory) && (
                                                                        isExpanded ? <ChevronUp className="w-3 h-3 text-muted-foreground" /> : <ChevronDown className="w-3 h-3 text-muted-foreground" />
                                                                    )}
                                                                </div>
                                                            </div>
                                                            <div className={cn(
                                                                "text-muted-foreground whitespace-pre-wrap",
                                                                !isExpanded && "line-clamp-2"
                                                            )}>
                                                                {isExpanded ? (source.text || source.content_preview) : (source.content_preview || source.text)}
                                                            </div>
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </ScrollArea>
                    ) : (
                        <div className="flex-grow flex items-center justify-center text-muted-foreground">
                            No conversation selected.
                        </div>
                    )}
                </DialogBody>

                <DialogFooter className="flex-shrink-0 flex items-center justify-between sm:justify-between border-t bg-muted/10">
                    <div className="flex gap-4 text-xs text-muted-foreground font-mono">
                        {detail && (
                            <>
                                <div title="Input / Output Tokens">
                                    Tokens: {detail.input_tokens} / {detail.output_tokens}
                                </div>
                                <div>
                                    Total: {detail.total_tokens}
                                </div>
                                <div className={detail.cost > 0.01 ? "text-warning" : ""}>
                                    Cost: ${detail.cost.toFixed(4)}
                                </div>
                            </>
                        )}
                    </div>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Close
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
