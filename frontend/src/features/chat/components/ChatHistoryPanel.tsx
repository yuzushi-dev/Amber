/**
 * ChatHistoryPanel
 * ================
 * Slide-in panel showing past conversations for the client (/amber/chat) view.
 * Fetches from GET /v1/chat/history and navigates by setting ?request_id.
 */

import { useEffect, useState, useCallback } from 'react'
import { useNavigate, useRouterState } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { chatApi, ChatHistoryItem } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { X, MessageSquarePlus, Clock, Trash2 } from 'lucide-react'
import { FormatDate } from '@/components/ui/date-format'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

interface ChatHistoryPanelProps {
    open: boolean
    onClose: () => void
}

const PAGE_SIZE = 20

export function ChatHistoryPanel({ open, onClose }: ChatHistoryPanelProps) {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const routerState = useRouterState()
    const searchParams = routerState.location.search as { request_id?: string }
    const activeId = searchParams.request_id

    const [offset, setOffset] = useState(0)
    const [allConversations, setAllConversations] = useState<ChatHistoryItem[]>([])
    const [hasMore, setHasMore] = useState(true)
    const [deletingId, setDeletingId] = useState<string | null>(null)

    const { data, isLoading, isFetching } = useQuery({
        queryKey: ['chat-history-client', offset],
        queryFn: () => chatApi.list({ limit: PAGE_SIZE, offset }),
        enabled: open,
    })

    useEffect(() => {
        if (data) {
            setAllConversations(prev =>
                offset === 0
                    ? data.conversations
                    : [...prev, ...data.conversations.filter(c => !prev.some(p => p.request_id === c.request_id))]
            )
            setHasMore(offset + data.conversations.length < data.total)
        }
    }, [data, offset])

    // Reset when panel reopens
    useEffect(() => {
        if (open) {
            setOffset(0)
            setAllConversations([])
            setHasMore(true)
        }
    }, [open])

    const loadMore = useCallback(() => {
        if (!isFetching && hasMore) {
            setOffset(prev => prev + PAGE_SIZE)
        }
    }, [isFetching, hasMore])

    const handleSelect = (item: ChatHistoryItem) => {
        navigate({ to: '/amber/chat', search: { request_id: item.request_id } })
        onClose()
    }

    const handleNewChat = () => {
        navigate({ to: '/amber/chat', search: {} })
        onClose()
    }

    const handleDelete = async (e: React.MouseEvent, item: ChatHistoryItem) => {
        e.stopPropagation()
        setDeletingId(item.request_id)
        try {
            await chatApi.delete(item.request_id)
            setAllConversations(prev => prev.filter(c => c.request_id !== item.request_id))
            queryClient.invalidateQueries({ queryKey: ['chat-history-client'] })
            toast.success('Conversation deleted')
            if (activeId === item.request_id) {
                navigate({ to: '/amber/chat', search: {} })
            }
        } catch {
            toast.error('Failed to delete conversation')
        } finally {
            setDeletingId(null)
        }
    }

    return (
        <>
            {/* Backdrop */}
            {open && (
                <div
                    className="fixed inset-0 z-30 bg-black/20 backdrop-blur-[2px]"
                    onClick={onClose}
                />
            )}

            {/* Panel */}
            <aside
                className={cn(
                    "fixed top-0 left-0 z-40 h-full w-72 bg-card border-r border-border/60 flex flex-col shadow-xl transition-transform duration-300 ease-out",
                    open ? "translate-x-0" : "-translate-x-full"
                )}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-4 py-4 border-b border-border/60">
                    <div className="flex items-center gap-2">
                        <Clock className="w-4 h-4 text-muted-foreground" />
                        <span className="text-sm font-semibold">History</span>
                    </div>
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
                        <X className="w-4 h-4" />
                    </Button>
                </div>

                {/* New Chat */}
                <div className="px-3 py-3 border-b border-border/40">
                    <Button
                        variant="outline"
                        size="sm"
                        className="w-full justify-start gap-2 text-primary border-primary/20 hover:bg-primary/5"
                        onClick={handleNewChat}
                    >
                        <MessageSquarePlus className="w-4 h-4" />
                        New conversation
                    </Button>
                </div>

                {/* Conversation list */}
                <div className="flex-1 overflow-y-auto py-2">
                    {isLoading && offset === 0 ? (
                        <div className="space-y-2 px-3 pt-1">
                            {Array.from({ length: 6 }).map((_, i) => (
                                <Skeleton key={i} className="h-12 w-full rounded-lg" />
                            ))}
                        </div>
                    ) : allConversations.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-4">
                            <MessageSquarePlus className="w-8 h-8 text-muted-foreground/30" />
                            <p className="text-xs text-muted-foreground/60">No past conversations yet</p>
                        </div>
                    ) : (
                        <>
                            {allConversations.map(item => (
                                <div
                                    key={item.request_id}
                                    onClick={() => handleSelect(item)}
                                    className={cn(
                                        "group mx-2 my-0.5 px-3 py-2.5 rounded-lg cursor-pointer flex flex-col gap-1 transition-colors",
                                        activeId === item.request_id
                                            ? "bg-primary/10 text-primary"
                                            : "hover:bg-muted/60 text-foreground"
                                    )}
                                >
                                    <div className="flex items-start justify-between gap-1">
                                        <p className="text-xs font-medium line-clamp-2 flex-1 leading-relaxed">
                                            {item.query_text || 'Untitled conversation'}
                                        </p>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-5 w-5 shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-md transition-all"
                                            onClick={(e) => handleDelete(e, item)}
                                            disabled={deletingId === item.request_id}
                                        >
                                            <Trash2 className="w-3 h-3" />
                                        </Button>
                                    </div>
                                    <FormatDate
                                        date={item.created_at}
                                        mode="short"
                                        className="text-[10px] text-muted-foreground/50"
                                    />
                                </div>
                            ))}

                            {hasMore && (
                                <div className="flex justify-center py-3">
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="text-xs text-muted-foreground"
                                        onClick={loadMore}
                                        disabled={isFetching}
                                    >
                                        {isFetching ? 'Loading…' : 'Load more'}
                                    </Button>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </aside>
        </>
    )
}
