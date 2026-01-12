/**
 * Admin Layout
 * ============
 * 
 * Layout for admin pages with simplified sidebar (no Evidence Board).
 */

import React from 'react'
import { Link } from '@tanstack/react-router'
import {
    Activity,
    Settings2,
    Database,
    Flag,
    ChevronLeft,
    Gauge,
    Users
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface AdminLayoutProps {
    children: React.ReactNode
}

const adminNavItems = [
    { label: 'Jobs', icon: Activity, to: '/admin/jobs' },
    { label: 'Queues', icon: Gauge, to: '/admin/queues' },
    { label: 'API Keys', icon: Settings2, to: '/admin/settings/apikeys' },
    { label: 'Tenants', icon: Users, to: '/admin/settings/tenants' },
    { label: 'Curation', icon: Flag, to: '/admin/curation' },
    { label: 'Database', icon: Database, to: '/admin/database' },
]

export default function AdminLayout({ children }: AdminLayoutProps) {
    return (
        <div className="flex h-screen bg-background overflow-hidden">
            <aside className="w-64 border-r bg-card flex flex-col">
                <div className="p-6">
                    <h1 className="text-xl font-bold tracking-tight text-primary">Amber</h1>
                    <p className="text-xs text-muted-foreground">Admin Console</p>
                </div>

                <nav className="flex-1 px-4 space-y-1" aria-label="Admin navigation">
                    {adminNavItems.map((item) => (
                        <Link
                            key={item.to}
                            to={item.to}
                            className={cn(
                                "flex items-center space-x-3 px-3 py-2 rounded-md transition-colors",
                                "text-muted-foreground hover:bg-secondary hover:text-secondary-foreground"
                            )}
                            activeProps={{
                                className: "bg-secondary text-secondary-foreground font-medium",
                            }}
                        >
                            <item.icon className="w-5 h-5" />
                            <span>{item.label}</span>
                        </Link>
                    ))}
                </nav>

                <div className="p-4 border-t">
                    <Link
                        to="/"
                        className="flex items-center space-x-3 px-3 py-2 w-full text-muted-foreground hover:bg-secondary hover:text-secondary-foreground rounded-md transition-colors"
                    >
                        <ChevronLeft className="w-5 h-5" />
                        <span>Back to Analyst</span>
                    </Link>
                </div>
            </aside>

            <main className="flex-1 overflow-y-auto">
                {children}
            </main>
        </div>
    )
}
