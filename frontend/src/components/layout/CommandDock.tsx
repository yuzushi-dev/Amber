/**
 * CommandDock.tsx
 * ===============
 * 
 * A floating bottom dock for primary navigation between major sections.
 * Inspired by macOS dock with subtle magnification and Amber styling.
 */

import { Link, useRouterState } from '@tanstack/react-router'
import { useState, useEffect } from 'react'
import {
    MessageSquare,
    Database,
    Settings2,
    MessageCircle,
    Menu,
    X,
    Activity
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface DockItem {
    label: string
    icon: React.ComponentType<{ className?: string }>
    to: string
    matchPrefix?: string
    external?: boolean
}

const dockItems: DockItem[] = [
    { label: 'Chat', icon: MessageSquare, to: '/admin/chat', matchPrefix: '/admin/chat' },
    { label: 'Data', icon: Database, to: '/admin/data', matchPrefix: '/admin/data' },
    { label: 'Metrics', icon: Activity, to: '/admin/metrics', matchPrefix: '/admin/metrics' },
    { label: 'Settings', icon: Settings2, to: '/admin/settings', matchPrefix: '/admin/settings' },
]

const clientChatItem: DockItem = {
    label: 'Client Chat',
    icon: MessageCircle,
    to: '/amber/chat',
    external: true
}

export default function CommandDock() {
    const routerState = useRouterState()
    const currentPath = routerState.location.pathname
    const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
    const [isMobile, setIsMobile] = useState(false)
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

    useEffect(() => {
        const checkMobile = () => setIsMobile(window.innerWidth < 768)
        checkMobile()
        window.addEventListener('resize', checkMobile)
        return () => window.removeEventListener('resize', checkMobile)
    }, [])

    // Keyboard shortcuts: Cmd/Ctrl + 1-4
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key >= '1' && e.key <= '5') {
                e.preventDefault()
                const index = parseInt(e.key) - 1
                const allItems = [...dockItems, clientChatItem]
                if (index < allItems.length) {
                    window.location.href = allItems[index].to
                }
            }
        }
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    }, [])

    const isActive = (item: DockItem) => {
        // Check if current path starts with their prefix
        return currentPath.startsWith(item.matchPrefix || item.to)
    }

    const getScale = (index: number) => {
        if (hoveredIndex === null) return 1
        const distance = Math.abs(index - hoveredIndex)
        if (distance === 0) return 1.15
        if (distance === 1) return 1.05
        return 1
    }

    // Mobile bottom tab bar
    if (isMobile) {
        return (
            <>
                {/* Mobile Menu Toggle */}
                <button
                    onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                    className={cn(
                        "fixed bottom-4 right-4 z-50 w-12 h-12 rounded-full",
                        "bg-primary text-primary-foreground shadow-lg",
                        "flex items-center justify-center transition-transform",
                        "active:scale-95 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
                    )}
                    aria-label={mobileMenuOpen ? "Close menu" : "Open menu"}
                    aria-expanded={mobileMenuOpen}
                >
                    {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
                </button>

                {/* Bottom Sheet Overlay */}
                {mobileMenuOpen && (
                    <div
                        className="fixed inset-0 bg-black/50 z-40 animate-in fade-in duration-200"
                        onClick={() => setMobileMenuOpen(false)}
                    />
                )}

                {/* Bottom Sheet */}
                <div
                    className={cn(
                        "fixed bottom-0 left-0 right-0 z-50 rounded-t-2xl",
                        "bg-card border-t border-border shadow-2xl backdrop-blur-xl",
                        "transition-transform duration-300",
                        mobileMenuOpen ? "translate-y-0" : "translate-y-full"
                    )}
                >
                    <div className="p-6 pb-8">
                        {/* Handle bar */}
                        <div className="w-12 h-1 rounded-full bg-muted mx-auto mb-6" />

                        {/* Grid of navigation items */}
                        <div className="grid grid-cols-3 gap-4">
                            {[...dockItems, clientChatItem].map((item) => {
                                const active = isActive(item)
                                const Icon = item.icon
                                return (
                                    <Link
                                        key={item.to}
                                        to={item.to}
                                        onClick={() => setMobileMenuOpen(false)}
                                        className={cn(
                                            "flex flex-col items-center justify-center p-4 rounded-xl transition-all",
                                            "active:scale-95 focus:outline-none focus:ring-2 focus:ring-primary",
                                            active
                                                ? "bg-primary/10 text-primary"
                                                : "bg-muted text-muted-foreground hover:text-foreground"
                                        )}
                                        activeProps={{ className: '' }}
                                        inactiveProps={{ className: '' }}
                                    >
                                        <Icon className="w-6 h-6 mb-2" />
                                        <span className="text-xs font-medium">{item.label}</span>
                                    </Link>
                                )
                            })}
                        </div>
                    </div>
                </div>
            </>
        )
    }

    // Desktop Dock
    return (
        <div
            className="fixed bottom-0 left-1/2 -translate-x-1/2 z-50 flex flex-col items-center justify-end"
            onMouseEnter={() => setHoveredIndex(null)} // Reset item hover when entering container
            onMouseLeave={() => setHoveredIndex(null)}
        >
            {/* Hover Trigger Area - Invisible but larger to catch hover easily */}
            <div className="absolute bottom-0 w-64 h-24 z-[-1]" />

            <div
                className="group flex flex-col items-center"
            >
                {/* actual nav content */}
                <nav
                    className={cn(
                        "transition-all duration-300 ease-out origin-bottom",
                        // Base styles from .dock but applied conditionally
                        "bg-black/80 backdrop-blur-2xl",
                        "border border-white/10 rounded-2xl", // Premium stroke
                        "px-2 py-1.5",
                        "shadow-[0_0_40px_rgba(0,0,0,0.5)]",
                        "flex items-center gap-1",
                        // Visibility states
                        "opacity-0 translate-y-4 scale-95 pointer-events-none", // Default hidden state
                        "group-hover:opacity-100 group-hover:-translate-y-6 group-hover:scale-100 group-hover:pointer-events-auto" // Hover state
                    )}
                    role="navigation"
                    aria-label="Main navigation"
                >
                    {dockItems.map((item, index) => {
                        const active = isActive(item)
                        const Icon = item.icon
                        const scale = getScale(index)

                        return (
                            <Link
                                key={item.to}
                                to={item.to}
                                onMouseEnter={() => setHoveredIndex(index)}
                                className={cn(
                                    "dock-item group/item relative flex items-center justify-center",
                                    active && "active"
                                )}
                                style={{ transform: `scale(${scale})` }}
                                aria-current={active ? 'page' : undefined}
                                activeProps={{ className: '' }}
                                inactiveProps={{ className: '' }}
                            >
                                {/* Tooltip */}
                                <span className={cn(
                                    "absolute -top-10 left-1/2 -translate-x-1/2",
                                    "px-2 py-1 rounded-md text-xs font-medium whitespace-nowrap",
                                    "bg-popover text-popover-foreground border shadow-md",
                                    "opacity-0 group-hover/item:opacity-100 transition-opacity duration-150",
                                    "pointer-events-none"
                                )}>
                                    {item.label}
                                    <span className="ml-1.5 text-muted-foreground">⌘{index + 1}</span>
                                </span>

                                <Icon className="w-6 h-6" />
                            </Link>
                        )
                    })}

                    {/* Divider */}
                    <div className="w-px h-6 bg-border mx-1" />

                    {/* Client Chat (special accent) */}
                    <Link
                        to={clientChatItem.to}
                        onMouseEnter={() => setHoveredIndex(dockItems.length)}
                        className={cn(
                            "dock-item group/item relative flex items-center justify-center",
                            "text-primary hover:text-primary"
                        )}
                        style={{ transform: `scale(${getScale(dockItems.length)})` }}
                        activeProps={{ className: '' }}
                        inactiveProps={{ className: '' }}
                    >
                        {/* Tooltip */}
                        <span className={cn(
                            "absolute -top-10 left-1/2 -translate-x-1/2",
                            "px-2 py-1 rounded-md text-xs font-medium whitespace-nowrap",
                            "bg-popover text-popover-foreground border shadow-md",
                            "opacity-0 group-hover/item:opacity-100 transition-opacity duration-150",
                            "pointer-events-none"
                        )}>
                            {clientChatItem.label}
                            <span className="ml-1.5 text-muted-foreground">⌘5</span>
                        </span>

                        <clientChatItem.icon className="w-6 h-6" />
                    </Link>
                </nav>

                {/* Collapsed Indicator (Primary Stroke) */}
                <div className={cn(
                    "absolute bottom-0 w-32 h-1.5 bg-primary rounded-t-full shadow-[0_0_15px_hsl(var(--primary)/0.6)] backdrop-blur-sm transition-all duration-300 delay-100",
                    "group-hover:opacity-0 group-hover:translate-y-2 group-hover:scale-50"
                )} />
            </div>
        </div>
    )
}
