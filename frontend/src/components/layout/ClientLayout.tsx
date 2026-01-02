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
            {/* Minimal header for branding consistency */}
            <header className="h-14 border-b bg-card flex items-center px-6 shrink-0">
                <h1 className="text-lg font-bold tracking-tight text-primary">Amber</h1>
            </header>

            {/* Full-height main content */}
            <main className="flex-1 overflow-hidden">
                {children}
            </main>
        </div>
    )
}
