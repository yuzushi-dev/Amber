/**
 * ChatHistoryPanel
 * ================
 * Collapsible inline sidebar showing past conversations for the client (/amber/chat) view.
 * Fetches from GET /v1/chat/history and navigates by setting ?request_id.
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate, useRouterState, Link } from '@tanstack/react-router'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { chatApi, ChatHistoryItem } from '@/lib/api-client'
import { Skeleton } from '@/components/ui/skeleton'
import { MessageSquarePlus, MessageCircle, Trash2, ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import { useChatStore } from '@/features/chat/store'

const PAGE_SIZE = 20

// Format date for grouping
const formatDate = (dateString: string): string => {
    if (!dateString) return ''
    const date = new Date(dateString)
    return date.toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    })
}

export function ChatHistoryPanel() {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const routerState = useRouterState()
    const searchParams = routerState.location.search as { request_id?: string }
    const activeId = searchParams.request_id

    const [collapsed, setCollapsed] = useState(false)
    const { lastHistoryUpdate } = useChatStore()
    const scrollContainerRef = useRef<HTMLElement>(null)

    const { data, isLoading, isFetching, fetchNextPage, hasNextPage } = useInfiniteQuery({
        queryKey: ['chat-history-client'],
        queryFn: ({ pageParam }) => chatApi.list({ limit: PAGE_SIZE, offset: pageParam as number }),
        initialPageParam: 0,
        getNextPageParam: (lastPage, allPages) => {
            const loaded = allPages.reduce((acc, p) => acc + p.conversations.length, 0)
            return loaded < lastPage.total ? loaded : undefined
        },
    })

    const allConversations = data?.pages.flatMap(p => p.conversations) ?? []
    const hasMore = !!hasNextPage

    // Invalidate and refresh list when a new conversation completes
    useEffect(() => {
        if (lastHistoryUpdate > 0) {
            queryClient.invalidateQueries({ queryKey: ['chat-history-client'] })
        }
    }, [lastHistoryUpdate, queryClient])

    const loadMore = useCallback(() => {
        if (!isFetching && hasMore) fetchNextPage()
    }, [isFetching, hasMore, fetchNextPage])

    // Scroll handler for infinite scroll
    useEffect(() => {
        const container = scrollContainerRef.current
        if (!container) return

        const handleScroll = () => {
            const { scrollTop, scrollHeight, clientHeight } = container
            // Load more when within 100px of bottom
            if (scrollHeight - scrollTop - clientHeight < 100) {
                loadMore()
            }
        }

        container.addEventListener('scroll', handleScroll)
        return () => container.removeEventListener('scroll', handleScroll)
    }, [loadMore])

    const handleDelete = async (e: React.MouseEvent, item: ChatHistoryItem) => {
        e.preventDefault()
        e.stopPropagation()
        if (!window.confirm('Are you sure you want to delete this conversation?')) {
            return
        }
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
        }
    }

    return (
        <aside
            className={cn(
                "context-sidebar h-full flex flex-col border-r transition-[width,background-color,box-shadow] duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] shrink-0",
                // Glass material
                "bg-background/80 backdrop-blur-xl border-white/5 shadow-xl supports-[backdrop-filter]:bg-background/60",
                collapsed ? "w-16 items-center" : "w-64"
            )}
        >
            <nav ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto py-4" aria-label="Section navigation">
                {/* Conversations Section */}
                <div>
                    {!collapsed && (
                        <h3 className="px-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                            Conversations
                        </h3>
                    )}
                    <ul className="space-y-1 px-2">
                        <li>
                            <Link
                                to="/amber/chat"
                                search={{}}
                                className={cn(
                                    "flex items-center gap-3 px-3 py-2 rounded-md transition-colors",
                                    "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1",
                                    "bg-primary text-primary-foreground hover:bg-primary/90 font-medium shadow-sm",
                                    collapsed && "justify-center px-2"
                                )}
                                title={collapsed ? "New Chat" : undefined}
                            >
                                <MessageSquarePlus className="w-4 h-4 shrink-0" />
                                {!collapsed && <span className="text-sm">New Chat</span>}
                            </Link>
                        </li>
                    </ul>
                </div>

                {/* Recent Conversations */}
                <div className="mt-4">
                    {!collapsed && (
                        <h3 className="px-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                            Recent
                        </h3>
                    )}

                    <ul className="space-y-1 px-2">
                        {isLoading && offset === 0 ? (
                            !collapsed && (
                                <>
                                    {[1, 2, 3].map((i) => (
                                        <li key={i} className="px-3 py-2">
                                            <div className="space-y-2">
                                                <Skeleton className="h-4 w-3/4" />
                                                <Skeleton className="h-3 w-1/2" />
                                            </div>
                                        </li>
                                    ))}
                                </>
                            )
                        ) : allConversations.length === 0 ? (
                            !collapsed && (
                                <li className="px-3 py-2 text-sm text-muted-foreground">
                                    No recent conversations
                                </li>
                            )
                        ) : (
                            allConversations.map((conversation) => {
                                const preview = conversation.query_text || 'Untitled conversation'
                                const displayText = preview.length > 30 ? preview.substring(0, 30) + '...' : preview
                                const isActive = activeId === conversation.request_id

                                return (
                                    <li key={conversation.request_id} className="group relative">
                                        <Link
                                            to="/amber/chat"
                                            search={{ request_id: conversation.request_id }}
                                            className={cn(
                                                "flex items-start gap-3 px-3 py-2 rounded-md transition-colors",
                                                "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1",
                                                isActive
                                                    ? "bg-secondary text-secondary-foreground font-medium"
                                                    : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                                                collapsed && "justify-center px-2",
                                                !collapsed && "pr-8" // Add padding for delete button
                                            )}
                                            title={collapsed ? preview : undefined}
                                        >
                                            <MessageCircle className="w-4 h-4 shrink-0 mt-0.5" />
                                            {!collapsed && (
                                                <div className="flex-1 min-w-0">
                                                    <div className="text-sm truncate">{displayText}</div>
                                                    <div className="text-xs text-muted-foreground">
                                                        {formatDate(conversation.created_at)}
                                                    </div>
                                                </div>
                                            )}
                                        </Link>
                                        {!collapsed && (
                                            <button
                                                onClick={(e) => handleDelete(e, conversation)}
                                                className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1.5 rounded-md hover:bg-destructive/10 hover:text-destructive transition-[opacity,background-color,color] duration-200 ease-out"
                                                title="Delete conversation"
                                                aria-label="Delete conversation"
                                            >
                                                <Trash2 className="w-3.5 h-3.5" />
                                            </button>
                                        )}
                                    </li>
                                )
                            })
                        )}
                    </ul>

                    {/* Loading indicator for infinite scroll */}
                    {isFetching && offset > 0 && !collapsed && (
                        <div className="px-3 py-2">
                            <div className="space-y-2">
                                <Skeleton className="h-4 w-3/4" />
                                <Skeleton className="h-3 w-1/2" />
                            </div>
                        </div>
                    )}
                </div>
            </nav>

            {/* Collapse toggle */}
            <div className="shrink-0 p-2 border-t">
                <button
                    onClick={() => setCollapsed(!collapsed)}
                    className={cn(
                        "w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md",
                        "text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors",
                        "focus:outline-none focus:ring-2 focus:ring-primary"
                    )}
                    aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                >
                    {collapsed ? (
                        <ChevronRight className="w-4 h-4" />
                    ) : (
                        <>
                            <ChevronLeft className="w-4 h-4" />
                            <span className="text-sm">Collapse</span>
                        </>
                    )}
                </button>
            </div>
        </aside>
    )
}
