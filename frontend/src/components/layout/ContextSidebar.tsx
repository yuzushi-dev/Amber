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

    ChevronLeft,
    ChevronRight,
    MessageSquarePlus,
    MessageCircle,
    Trash2,
    Key,
    Package,
    Server,
    Users
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/features/chat/store'
import { chatHistoryApi, ChatHistoryItem } from '@/lib/api-admin'
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
                { label: 'Statistics', icon: Database, to: '/admin/data/maintenance' },
                { label: 'Query Log', icon: Activity, to: '/admin/queries' },
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
            ]
        },
        {
            title: 'General',
            items: [
                { label: 'Optional Features', icon: Package, to: '/admin/settings/features' },
                { label: 'API Key', icon: Key, to: '/admin/settings/keys' },
                { label: 'Tenants', icon: Users, to: '/admin/settings/tenants' },
                { label: 'Connectors', icon: MessageCircle, to: '/admin/settings/connectors' },
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
    const [isUploadOpen, setIsUploadOpen] = useState(false)

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
    }, [activeSection, lastHistoryUpdate])

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
        <>
            <aside
                className={cn(
                    "context-sidebar flex flex-col bg-card border-r transition-all duration-200",
                    collapsed ? "w-14" : "w-60"
                )}
            >
                {/* Sidebar content */}
                {activeSection === 'data' ? (
                    <DatabaseSidebarContent
                        collapsed={collapsed}
                        onUploadClick={() => setIsUploadOpen(true)}
                    />
                ) : (
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

                                            const handleDelete = async (e: React.MouseEvent, id: string) => {
                                                e.preventDefault()
                                                e.stopPropagation()
                                                if (confirm('Delete this conversation?')) {
                                                    try {
                                                        await chatHistoryApi.delete(id)
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
                                                            className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1.5 rounded-md hover:bg-destructive/10 hover:text-destructive transition-all"
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
                            </div>
                        )}
                    </nav>
                )}

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

            {/* Upload Wizard Modal - for data section */}
            {
                isUploadOpen && (
                    <UploadWizard
                        onClose={() => setIsUploadOpen(false)}
                        onComplete={() => setIsUploadOpen(false)}
                    />
                )
            }
        </>
    )
}
