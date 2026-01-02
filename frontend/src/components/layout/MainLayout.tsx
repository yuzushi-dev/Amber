/**
 * MainLayout.tsx
 * ==============
 * 
 * Main layout for the Admin/Analyst experience.
 * Uses a hybrid navigation system:
 * - CommandDock: Bottom dock for primary navigation
 * - ContextSidebar: Left sidebar for section-specific subsections
 */

import React from 'react'
import CommandDock from './CommandDock'
import ContextSidebar from './ContextSidebar'

import EvidenceBoard from '../../features/evidence/components/EvidenceBoard'

interface MainLayoutProps {
    children: React.ReactNode
}

export default function MainLayout({ children }: MainLayoutProps) {
    return (
        <div className="flex flex-col h-screen bg-background overflow-hidden">
            {/* Main content area */}
            <div className="flex flex-1 overflow-hidden">
                {/* Contextual sidebar (only shows for Data/Operations sections) */}
                <ContextSidebar />

                {/* Page content */}
                <main className="flex-1 overflow-y-auto relative flex">
                    <div className="flex-1 h-full overflow-y-auto">
                        {children}
                    </div>
                    <EvidenceBoard />
                </main>
            </div>

            {/* Bottom dock navigation */}
            <CommandDock />
        </div>
    )
}
