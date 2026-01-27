/**
 * ContextSidebar.tsx
 * ==================
 *
 * A contextual sidebar that adapts based on the current dock section.
 * Shows relevant subsections for quick in-context navigation.
 */

import { Link, useRouterState } from '@tanstack/react-router'
import { useState, useEffect, useRef, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
    Files,
    Layers,
    Activity,
    Gauge,
    Sliders,
    BookOpen,
    Sparkles,

    ChevronLeft,
    ChevronRight,
    MessageSquarePlus,
    MessageCircle,
    Trash2,
    Key,
    Package,
    Server,
    Users,
    Archive
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'
import { useChatStore } from '@/features/chat/store'
import { chatApi, ChatHistoryItem } from '@/lib/api-client'
import DatabaseSidebarContent from '@/features/documents/components/DatabaseSidebarContent'
import UploadWizard from '@/features/documents/components/UploadWizard'

interface SidebarSection {
    title: string
    items: SidebarItem[]
}

interface SidebarItem {
    label: string
    icon: React.ComponentType<{ className?: string }>
    to: string
    variant?: 'default' | 'primary'
}

// Sidebar configuration for each dock section
const sidebarConfig: Record<string, SidebarSection[]> = {
    chat: [
        {
            title: 'Conversations',
            items: [
                {
                    label: 'New Chat',
                    icon: MessageSquarePlus,
                    to: '/admin/chat',
                    variant: 'primary'
                },
            ]
        },
        // Recent conversations will be loaded dynamically
    ],
    data: [
        {
            title: 'Documents',
            items: [
                { label: 'All Documents', icon: Files, to: '/admin/data/documents' },
            ]
        },
        {
            title: 'Database',
            items: [
                { label: 'Vector Store', icon: Layers, to: '/admin/data/vectors' },
            ]
        }
    ],
    metrics: [
        {
            title: 'Evaluation',
            items: [
                { label: 'Token Metrics', icon: Activity, to: '/admin/metrics/tokens' },
                { label: 'RAGAS Evaluation', icon: Gauge, to: '/admin/metrics/ragas' },
                { label: 'Feedback', icon: MessageSquarePlus, to: '/admin/metrics/feedback' },
            ]
        },
        {
            title: 'System',
            items: [
                { label: 'System Status', icon: Server, to: '/admin/metrics/system' },
            ]
        }
    ],
    settings: [
        {
            title: 'Model',
            items: [
                { label: 'RAG Tuning', icon: Sliders, to: '/admin/settings/tuning' },
                { label: 'LLMs', icon: Sparkles, to: '/admin/settings/llms' },
                { label: 'Global Rules', icon: BookOpen, to: '/admin/settings/rules' },
            ]
        },
        {
            title: 'General',
            items: [
                { label: 'Optional Features', icon: Package, to: '/admin/settings/features' },
                { label: 'API Key', icon: Key, to: '/admin/settings/keys' },
                { label: 'Tenants', icon: Users, to: '/admin/settings/tenants' },
                { label: 'Connectors', icon: MessageCircle, to: '/admin/settings/connectors' },
                { label: 'Data Retention', icon: Archive, to: '/admin/settings/data-retention' },
            ]
        }
    ]
}

export default function ContextSidebar() {
    const routerState = useRouterState()
    const currentPath = routerState.location.pathname
    const queryClient = useQueryClient()
    const [collapsed, setCollapsed] = useState(false)
    const [recentConversations, setRecentConversations] = useState<ChatHistoryItem[]>([])
    const [loadingHistory, setLoadingHistory] = useState(false)
    const [loadingMore, setLoadingMore] = useState(false)
    const [hasMore, setHasMore] = useState(true)

    const [isUploadOpen, setIsUploadOpen] = useState(false)
    const scrollContainerRef = useRef<HTMLElement>(null)
    const CONVERSATIONS_PER_PAGE = 20

    // Determine which section we're in
    const getActiveSection = (): string | null => {
        if (currentPath.startsWith('/admin/chat')) return 'chat'
        if (currentPath.startsWith('/admin/data')) return 'data'
        if (currentPath.startsWith('/admin/metrics')) return 'metrics'
        if (currentPath.startsWith('/admin/settings')) return 'settings'
        return null
    }

    const activeSection = getActiveSection()

    const { lastHistoryUpdate } = useChatStore()

    // Fetch recent conversations for chat section
    useEffect(() => {
        if (activeSection === 'chat') {
            const fetchHistory = async () => {
                try {
                    setLoadingHistory(true)

                    setHasMore(true)
                    const data = await chatApi.list({ limit: CONVERSATIONS_PER_PAGE })
                    setRecentConversations(data.conversations)
                    setHasMore(data.conversations.length >= CONVERSATIONS_PER_PAGE)
                } catch (err) {
                    console.error('Failed to load chat history:', err)
                } finally {
                    setLoadingHistory(false)
                }
            }
            fetchHistory()
        }
    }, [activeSection, lastHistoryUpdate])

    // Load more conversations when scrolling to bottom
    const loadMore = useCallback(async () => {
        if (loadingMore || !hasMore || activeSection !== 'chat') return

        try {
            setLoadingMore(true)
            const newOffset = recentConversations.length
            const data = await chatApi.list({
                limit: CONVERSATIONS_PER_PAGE,
                offset: newOffset
            })

            if (data.conversations.length > 0) {
                setRecentConversations(prev => [...prev, ...data.conversations])

                setHasMore(data.conversations.length >= CONVERSATIONS_PER_PAGE)
            } else {
                setHasMore(false)
            }
        } catch (err) {
            console.error('Failed to load more conversations:', err)
        } finally {
            setLoadingMore(false)
        }
    }, [loadingMore, hasMore, activeSection, recentConversations.length])

    // Scroll handler for infinite scroll
    useEffect(() => {
        const container = scrollContainerRef.current
        if (!container || activeSection !== 'chat') return

        const handleScroll = () => {
            const { scrollTop, scrollHeight, clientHeight } = container
            // Load more when within 100px of bottom
            if (scrollHeight - scrollTop - clientHeight < 100) {
                loadMore()
            }
        }

        container.addEventListener('scroll', handleScroll)
        return () => container.removeEventListener('scroll', handleScroll)
    }, [activeSection, loadMore])

    const sections = activeSection ? sidebarConfig[activeSection] : null

    // Don't render sidebar for Dashboard or Chat
    if (!sections) {
        return null
    }

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

    // Handle upload complete - refresh document queries
    const handleUploadComplete = () => {
        setIsUploadOpen(false)
        // Invalidate all document-related queries to refresh the list
        queryClient.invalidateQueries({ queryKey: ['documents'] })
        queryClient.invalidateQueries({ queryKey: ['stats'] })
    }

    return (
        <>
            <aside
                className={cn(
                    "context-sidebar h-full flex flex-col border-r transition-[width,background-color,box-shadow] duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)]",
                    // Glass material
                    "bg-background/80 backdrop-blur-xl border-white/5 shadow-xl supports-[backdrop-filter]:bg-background/60",
                    collapsed ? "w-16 items-center" : "w-64"
                )}
            >
                {/* Sidebar content */}
                {activeSection === 'data' ? (
                    <DatabaseSidebarContent
                        collapsed={collapsed}
                        onUploadClick={() => setIsUploadOpen(true)}
                    />
                ) : (
                    <nav ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto py-4" aria-label="Section navigation">
                        {sections.map((section, sectionIndex) => (
                            <div key={section.title} className={cn(sectionIndex > 0 && "mt-4")}>
                                {/* Section title */}
                                {!collapsed && (
                                    <h3 className="px-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                                        {section.title}
                                    </h3>
                                )}

                                {/* Section items */}
                                <ul className="space-y-1 px-2">
                                    {section.items.map((item) => {
                                        // Exact match for links, or prefix match only for sub-pages
                                        const linkPath = item.to.split('?')[0]
                                        const isActive = currentPath === linkPath ||
                                            (linkPath !== '/admin/settings' && currentPath.startsWith(linkPath + '/'))
                                        const Icon = item.icon
                                        const isPrimary = item.variant === 'primary'

                                        return (
                                            <li key={item.to}>
                                                <Link
                                                    to={item.to}
                                                    className={cn(
                                                        "flex items-center gap-3 px-3 py-2 rounded-md transition-colors",
                                                        "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1",
                                                        isPrimary
                                                            ? "bg-primary text-primary-foreground hover:bg-primary/90 font-medium shadow-sm"
                                                            : isActive
                                                                ? "bg-secondary text-secondary-foreground font-medium"
                                                                : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                                                        collapsed && "justify-center px-2"
                                                    )}
                                                    title={collapsed ? item.label : undefined}
                                                >
                                                    <Icon className="w-4 h-4 shrink-0" />
                                                    {!collapsed && (
                                                        <span className="text-sm">{item.label}</span>
                                                    )}
                                                </Link>
                                            </li>
                                        )
                                    })}
                                </ul>
                            </div>
                        ))}

                        {/* Recent Conversations (Chat section only) */}
                        {activeSection === 'chat' && (
                            <div className="mt-4">
                                {!collapsed && (
                                    <h3 className="px-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                                        Recent
                                    </h3>
                                )}

                                <ul className="space-y-1 px-2">
                                    {loadingHistory ? (
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
                                    ) : recentConversations.length === 0 ? (
                                        !collapsed && (
                                            <li className="px-3 py-2 text-sm text-muted-foreground">
                                                No recent conversations
                                            </li>
                                        )
                                    ) : (
                                        recentConversations.map((conversation) => {
                                            const preview = conversation.query_text || 'Untitled conversation'
                                            const displayText = preview.length > 30 ? preview.substring(0, 30) + '...' : preview

                                            const handleDelete = async (e: React.MouseEvent, id: string) => {
                                                e.preventDefault()
                                                e.stopPropagation()
                                                if (confirm('Delete this conversation?')) {
                                                    try {
                                                        await chatApi.delete(id)
                                                        setRecentConversations(prev => prev.filter(c => c.request_id !== id))
                                                    } catch (err) {
                                                        console.error('Failed to delete conversation:', err)
                                                    }
                                                }
                                            }

                                            return (
                                                <li key={conversation.request_id} className="group relative">
                                                    <Link
                                                        to="/admin/chat"
                                                        search={{ request_id: conversation.request_id }}
                                                        className={cn(
                                                            "flex items-start gap-3 px-3 py-2 rounded-md transition-colors",
                                                            "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1",
                                                            "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
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
                                                            onClick={(e) => handleDelete(e, conversation.request_id)}
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
                                {loadingMore && !collapsed && (
                                    <div className="px-3 py-2">
                                        <div className="space-y-2">
                                            <Skeleton className="h-4 w-3/4" />
                                            <Skeleton className="h-3 w-1/2" />
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </nav>
                )}

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

            {/* Upload Wizard Modal - for data section */}
            {
                isUploadOpen && (
                    <UploadWizard
                        onClose={() => setIsUploadOpen(false)}
                        onComplete={handleUploadComplete}
                    />
                )
            }
        </>
    )
}
