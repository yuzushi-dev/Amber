/**
 * DatabaseOverviewPage.tsx
 * ========================
 * 
 * The main dashboard for the Data section.
 * Displays high-level statistics about the Knowledge Base.
 */

import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { maintenanceApi } from '@/lib/api-admin'
import {
    FileText,
    Box,
    Users,
    Share2,
    Network,
    GitMerge
} from 'lucide-react'
import { cn } from '@/lib/utils'

export default function DatabaseOverviewPage() {
    const { data: stats, isLoading, error } = useQuery({
        queryKey: ['maintenance-stats'],
        queryFn: () => maintenanceApi.getStats(),
        refetchInterval: 30000,
    })

    if (isLoading && !stats) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
        )
    }

    if (error) {
        return (
            <div className="p-6">
                <div className="bg-destructive/10 text-destructive p-4 rounded-md">
                    Failed to load statistics.
                </div>
            </div>
        )
    }

    const cards = [
        {
            label: 'Documents',
            value: stats?.database.documents_total ?? 0,
            icon: FileText,
            color: 'text-blue-500',
            bg: 'bg-blue-500/10'
        },
        {
            label: 'Chunks',
            value: stats?.database.chunks_total ?? 0,
            icon: Box,
            color: 'text-purple-500',
            bg: 'bg-purple-500/10'
        },
        {
            label: 'Entities',
            value: stats?.database.entities_total ?? 0,
            icon: Users,
            color: 'text-green-500',
            bg: 'bg-green-500/10'
        },
        {
            label: 'Relationships',
            value: stats?.database.relationships_total ?? 0,
            icon: Share2,
            color: 'text-orange-500',
            bg: 'bg-orange-500/10'
        },
        {
            label: 'Communities',
            value: 0, // Not yet in backend stats, placeholder
            icon: Network,
            color: 'text-pink-500',
            bg: 'bg-pink-500/10'
        },
        {
            label: 'Similarities',
            value: 0, // Not yet in backend stats, placeholder
            icon: GitMerge,
            color: 'text-yellow-500',
            bg: 'bg-yellow-500/10'
        }
    ]

    return (
        <div className="p-8 max-w-7xl mx-auto">
            <header className="mb-8">
                <h1 className="text-3xl font-bold tracking-tight">Knowledge Base Overview</h1>
                <p className="text-muted-foreground mt-1">
                    Real-time statistics and health metrics for your vector store and Knowledge Graph.
                </p>
            </header>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {cards.map((card) => (
                    <div
                        key={card.label}
                        className="p-6 rounded-xl border bg-card text-card-foreground shadow-sm flex items-center gap-4 transition-all hover:shadow-md"
                    >
                        <div className={cn("p-4 rounded-full", card.bg, card.color)}>
                            <card.icon className="w-6 h-6" />
                        </div>
                        <div>
                            <p className="text-sm font-medium text-muted-foreground">{card.label}</p>
                            <h2 className="text-3xl font-bold">{card.value.toLocaleString()}</h2>
                        </div>
                    </div>
                ))}
            </div>

            {/* Additional info or charts could go here */}
        </div>
    )
}
