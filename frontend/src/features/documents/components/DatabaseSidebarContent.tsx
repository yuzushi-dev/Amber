/**
 * DatabaseSidebarContent.tsx
 * ==========================
 * 
 * A robust sidebar for document management.
 * Includes:
 * - Navigation to Overview
 * - Upload Action
 * - Folder Organization (Mock/Visual)
 * - Document List
 */

import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState, useNavigate } from '@tanstack/react-router'
import { apiClient } from '@/lib/api-client'
import {
    FileText,
    Plus,
    Search,
    ChevronLeft,
    Folder,
    MoreHorizontal,
    Trash2,
    Database
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import LiveStatusBadge from './LiveStatusBadge'

interface Document {
    id: string
    filename: string
    title: string
    status: string
    created_at: string
    source_type?: string
}

interface DatabaseSidebarContentProps {
    collapsed?: boolean
    onUploadClick?: () => void
}

export default function DatabaseSidebarContent({
    collapsed = false,
    onUploadClick
}: DatabaseSidebarContentProps) {
    const [searchQuery, setSearchQuery] = useState('')
    const routerState = useRouterState()
    const navigate = useNavigate()
    const currentPath = routerState.location.pathname

    // Fetch documents
    const { data: documents, isLoading } = useQuery({
        queryKey: ['documents'],
        queryFn: async () => {
            const response = await apiClient.get<Document[]>('/documents')
            return response.data
        }
    })

    // Filter documents
    const filteredDocuments = useMemo(() => {
        if (!documents) return []
        if (!searchQuery.trim()) return documents

        const query = searchQuery.toLowerCase()
        return documents.filter(doc =>
            doc.filename?.toLowerCase().includes(query) ||
            doc.title?.toLowerCase().includes(query)
        )
    }, [documents, searchQuery])

    // Grouping logic (visual only for now, can be expanded)
    const folders = [
        { id: 'all', name: 'All documents', count: documents?.length || 0 },
        { id: 'unfiled', name: 'Unfiled', count: 0 },
    ]

    return (
        <div className="flex flex-col h-full bg-muted/10 border-r">
            {/* Header: Navigation & Actions */}
            <div className="p-3 space-y-3">
                {/* Back to Dashboard / Overview Link */}
                <Button
                    variant="ghost"
                    size="sm"
                    className={cn(
                        "w-full justify-start text-muted-foreground gap-2",
                        collapsed && "px-0 justify-center"
                    )}
                    onClick={() => navigate({ to: '/admin/data/overview' })}
                    title="Database Overview"
                >
                    <Database className="w-4 h-4" />
                    {!collapsed && <span>Overview</span>}
                </Button>

                {/* Main Upload Button */}
                <Button
                    variant="default" // Uses primary color (likely orange in Amber 2.0 theme)
                    className={cn(
                        "w-full gap-2 shadow-sm font-medium",
                        collapsed && "px-0 justify-center"
                    )}
                    onClick={onUploadClick}
                    title="Upload Files"
                >
                    <Plus className="w-4 h-4" />
                    {!collapsed && <span>Upload Files</span>}
                </Button>
            </div>

            {/* Content: Folders & Files */}
            {!collapsed && (
                <ScrollArea className="flex-1 px-3">
                    <div className="space-y-6">

                        {/* Folders Section */}
                        <div>
                            <div className="flex items-center justify-between px-2 mb-2">
                                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                                    Folders
                                </h3>
                                <Button variant="ghost" size="icon" className="h-5 w-5">
                                    <Plus className="w-3 h-3" />
                                </Button>
                            </div>
                            <div className="space-y-0.5">
                                {folders.map(folder => (
                                    <div
                                        key={folder.id}
                                        className={cn(
                                            "flex items-center justify-between px-2 py-1.5 rounded-md text-sm cursor-pointer hover:bg-muted transition-colors",
                                            // Highlight 'All documents' if on list page or root
                                            (folder.id === 'all' && (currentPath === '/admin/data/documents' || currentPath === '/admin/data/overview'))
                                                ? "bg-muted font-medium text-foreground"
                                                : "text-muted-foreground"
                                        )}
                                        onClick={() => navigate({ to: '/admin/data/documents' })} // For now just list all
                                    >
                                        <div className="flex items-center gap-2">
                                            <Folder className="w-4 h-4" />
                                            <span>{folder.name}</span>
                                        </div>
                                        <span className="text-xs">{folder.count}</span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Documents List Section */}
                        <div>
                            <div className="flex items-center justify-between px-2 mb-2">
                                <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                                    Documents
                                </h3>
                            </div>

                            {/* Simple Search */}
                            <div className="relative mb-2">
                                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground" />
                                <Input
                                    className="h-7 text-xs pl-7 bg-background"
                                    placeholder="Search..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                />
                            </div>

                            <ul className="space-y-0.5">
                                {isLoading ? (
                                    <div className="px-2 py-2 text-xs text-muted-foreground">Loading...</div>
                                ) : filteredDocuments.length === 0 ? (
                                    <div className="px-2 py-2 text-xs text-muted-foreground">No documents found</div>
                                ) : (
                                    filteredDocuments.map(doc => {
                                        const isActive = currentPath.includes(doc.id)
                                        return (
                                            <li key={doc.id}>
                                                <Link
                                                    to="/admin/data/documents/$documentId"
                                                    params={{ documentId: doc.id }}
                                                    className={cn(
                                                        "group flex items-center justify-between px-2 py-1.5 rounded-md text-sm transition-colors",
                                                        isActive
                                                            ? "bg-accent text-accent-foreground font-medium"
                                                            : "text-muted-foreground hover:bg-muted hover:text-foreground"
                                                    )}
                                                >
                                                    <div className="flex items-center gap-2 overflow-hidden">
                                                        <FileText className="w-3.5 h-3.5 shrink-0" />
                                                        <span className="truncate">{doc.title || doc.filename}</span>
                                                    </div>
                                                    {/* Hover actions could go here, for now just status */}
                                                    {isActive && (
                                                        <LiveStatusBadge
                                                            documentId={doc.id}
                                                            initialStatus={doc.status}
                                                            compact
                                                            className="h-1.5 w-1.5 p-0"
                                                        />
                                                    )}
                                                </Link>
                                            </li>
                                        )
                                    })
                                )}
                            </ul>
                        </div>
                    </div>
                </ScrollArea>
            )}

            {/* Collapsed View Fallbacks - Minimal Icons */}
            {collapsed && (
                <div className="flex flex-col items-center gap-2 mt-4 px-2">
                    <Button variant="ghost" size="icon" title="Functions">
                        <Folder className="w-4 h-4" />
                    </Button>
                </div>
            )}
        </div>
    )
}
