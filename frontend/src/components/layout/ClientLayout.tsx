/**
 * ClientLayout.tsx
 * ================
 *
 * A focused, distraction-free layout for the Client persona.
 * Used for /amber/chat – full-screen chat with history panel toggle.
 */

import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { History } from 'lucide-react'
import { ChatHistoryPanel } from '@/features/chat/components/ChatHistoryPanel'

interface ClientLayoutProps {
    children: React.ReactNode
}

export default function ClientLayout({ children }: ClientLayoutProps) {
    const [historyOpen, setHistoryOpen] = useState(false)

    return (
        <div className="flex flex-col h-screen bg-background">
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground shadow-lg"
            >
                Skip to content
            </a>

            {/* Header */}
            <header className="h-14 border-b bg-card flex items-center px-4 shrink-0 gap-3">
                <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-foreground"
                    onClick={() => setHistoryOpen(true)}
                    title="Conversation history"
                >
                    <History className="h-4 w-4" />
                </Button>
                <h1 className="text-lg font-bold tracking-tight text-primary">Amber</h1>
            </header>

            {/* History slide-in panel */}
            <ChatHistoryPanel open={historyOpen} onClose={() => setHistoryOpen(false)} />

            {/* Full-height main content */}
            <main id="main-content" className="flex-1 overflow-hidden">
                {children}
            </main>
        </div>
    )
}
