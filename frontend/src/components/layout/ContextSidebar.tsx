/**
 * ContextSidebar.tsx
 * ==================
 *
 * A contextual sidebar that adapts based on the current dock section.
 * Shows relevant subsections for quick in-context navigation.
 */

import { Link, useRouterState } from '@tanstack/react-router'
import { useState, useEffect } from 'react'
import {
    Files,
    Database,
    Layers,
    Activity,
    Gauge,
    Sliders,
    Flag,
    ChevronLeft,
    ChevronRight,
    FolderOpen,
    Trash2,
    MessageSquarePlus,
    MessageCircle,

} from 'lucide-react'
import { cn } from '@/lib/utils'
import { chatHistoryApi, ChatHistoryItem } from '@/lib/api-admin'

interface SidebarSection {
    title: string
    items: SidebarItem[]
}

interface SidebarItem {
    label: string
    icon: React.ComponentType<{ className?: string }>
    to: string
}

// Sidebar configuration for each dock section
const sidebarConfig: Record<string, SidebarSection[]> = {
    chat: [
        {
            title: 'Conversations',
            items: [
                { label: 'New Chat', icon: MessageSquarePlus, to: '/admin/chat' },
            ]
        },
        // Recent conversations will be loaded dynamically
    ],
    data: [
        {
            title: 'Documents',
            items: [
                { label: 'All Documents', icon: Files, to: '/admin/data/documents' },
                { label: 'Upload New', icon: FolderOpen, to: '/admin/data/documents?upload=true' },
            ]
        },
        {
            title: 'Database',
            items: [
                { label: 'Statistics', icon: Database, to: '/admin/data/database' },
                { label: 'Vector Store', icon: Layers, to: '/admin/data/vectors' },
            ]
        },
        {
            title: 'Maintenance',
            items: [
                { label: 'Cache & Cleanup', icon: Trash2, to: '/admin/data/maintenance' },
            ]
        }
    ],
    ops: [
        {
            title: 'Jobs',
            items: [
                { label: 'Active Jobs', icon: Activity, to: '/admin/ops/jobs' },
            ]
        },
        {
            title: 'Queues',
            items: [
                { label: 'Queue Status', icon: Gauge, to: '/admin/ops/queues' },
            ]
        },
        {
            title: 'Configuration',
            items: [
                { label: 'RAG Tuning', icon: Sliders, to: '/admin/ops/tuning' },
                { label: 'Curation', icon: Flag, to: '/admin/ops/curation' },
            ]
        },
        {
            title: 'Analytics',
            items: [
                { label: 'Token Metrics', icon: Activity, to: '/admin/ops/metrics' },
                { label: 'RAGAS Evaluation', icon: Gauge, to: '/admin/ops/ragas' },
            ]
        }

    ]
}

export default function ContextSidebar() {
    const routerState = useRouterState()
    const currentPath = routerState.location.pathname
    const [collapsed, setCollapsed] = useState(false)
    const [recentConversations, setRecentConversations] = useState<ChatHistoryItem[]>([])
    const [loadingHistory, setLoadingHistory] = useState(false)

    // Determine which section we're in
    const getActiveSection = (): string | null => {
        if (currentPath.startsWith('/admin/chat')) return 'chat'
        if (currentPath.startsWith('/admin/data')) return 'data'
        if (currentPath.startsWith('/admin/ops')) return 'ops'
        return null
    }

    const activeSection = getActiveSection()

    // Fetch recent conversations for chat section
    useEffect(() => {
        if (activeSection === 'chat') {
            const fetchHistory = async () => {
                try {
                    setLoadingHistory(true)
                    const data = await chatHistoryApi.list({ limit: 10 })
                    setRecentConversations(data.conversations)
                } catch (err) {
                    console.error('Failed to load chat history:', err)
                } finally {
                    setLoadingHistory(false)
                }
            }
            fetchHistory()
        }
    }, [activeSection])

    const sections = activeSection ? sidebarConfig[activeSection] : null

    // Don't render sidebar for Dashboard or Chat
    if (!sections) {
        return null
    }

    // Format date for grouping
    const formatDate = (dateString: string): string => {
        const date = new Date(dateString)
        const now = new Date()
        const diffMs = now.getTime() - date.getTime()
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

        if (diffDays === 0) return 'Today'
        if (diffDays === 1) return 'Yesterday'
        if (diffDays < 7) return 'This Week'
        return 'Older'
    }

    return (
        <aside
            className={cn(
                "context-sidebar flex flex-col bg-card border-r transition-all duration-200",
                collapsed ? "w-14" : "w-60"
            )}
        >
            {/* Sidebar content */}
            <nav className="flex-1 overflow-y-auto py-4" aria-label="Section navigation">
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
                                const isActive = currentPath === item.to ||
                                    currentPath.startsWith(item.to.split('?')[0])
                                const Icon = item.icon

                                return (
                                    <li key={item.to}>
                                        <Link
                                            to={item.to}
                                            className={cn(
                                                "flex items-center gap-3 px-3 py-2 rounded-md transition-colors",
                                                "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1",
                                                isActive
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
                                    <li className="px-3 py-2 text-sm text-muted-foreground">
                                        Loading...
                                    </li>
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

                                    return (
                                        <li key={conversation.request_id}>
                                            <Link
                                                to="/admin/chat"
                                                search={{ request_id: conversation.request_id }}
                                                className={cn(
                                                    "flex items-start gap-3 px-3 py-2 rounded-md transition-colors",
                                                    "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1",
                                                    "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                                                    collapsed && "justify-center px-2"
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
                                        </li>
                                    )
                                })
                            )}
                        </ul>
                    </div>
                )}
            </nav>

            {/* Collapse toggle */}
            <div className="p-2 border-t">
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
