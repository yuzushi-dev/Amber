import React from 'react'
import Sidebar from './Sidebar'
import EvidenceBoard from '../../features/evidence/components/EvidenceBoard'

interface MainLayoutProps {
    children: React.ReactNode
}

export default function MainLayout({ children }: MainLayoutProps) {
    return (
        <div className="flex h-screen bg-background overflow-hidden">
            <Sidebar />
            <main className="flex-1 overflow-y-auto relative flex">
                <div className="flex-1 h-full overflow-y-auto">
                    {children}
                </div>
                <EvidenceBoard />
            </main>
        </div>
    )
}
