/**
 * ClientLayout.tsx
 * ================
 * 
 * A focused, distraction-free layout for the Client persona.
 * Used for /amber/chat – full-screen chat with no sidebar.
 * Maintains visual consistency with the main app theme.
 */

import React from 'react'

interface ClientLayoutProps {
    children: React.ReactNode
}

export default function ClientLayout({ children }: ClientLayoutProps) {
    return (
        <div className="flex flex-col h-screen bg-background">
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground shadow-lg"
            >
                Skip to content
            </a>
            {/* Minimal header for branding consistency */}
            <header className="h-14 border-b bg-card flex items-center px-6 shrink-0">
                <h1 className="text-lg font-bold tracking-tight text-primary">Amber</h1>
            </header>

            {/* Full-height main content */}
            <main id="main-content" className="flex-1 overflow-hidden">
                {children}
            </main>
        </div>
    )
}
