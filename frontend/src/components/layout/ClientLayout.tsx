/**
 * ClientLayout.tsx
 * ================
 *
 * A focused, distraction-free layout for the Client persona.
 * Used for /amber/chat – full-screen chat with inline history sidebar.
 */

import React from 'react'
import { ChatHistoryPanel } from '@/features/chat/components/ChatHistoryPanel'

interface ClientLayoutProps {
    children: React.ReactNode
}

export default function ClientLayout({ children }: ClientLayoutProps) {
    return (
        <div className="flex flex-col h-screen bg-background overflow-hidden">
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground shadow-lg"
            >
                Skip to content
            </a>

            {/* Main content area */}
            <div className="flex flex-1 overflow-hidden">
                {/* Inline contextual sidebar */}
                <ChatHistoryPanel />

                {/* Page content */}
                <main id="main-content" className="flex-1 overflow-y-auto relative flex">
                    <div className="flex-1 h-full overflow-y-auto">
                        {children}
                    </div>
                </main>
            </div>
        </div>
    )
}
