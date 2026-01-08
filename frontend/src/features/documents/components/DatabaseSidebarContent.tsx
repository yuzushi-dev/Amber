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
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useRouterState, useNavigate } from '@tanstack/react-router'
import {
    DndContext,
    useDraggable,
    useDroppable,
    type DragEndEvent
} from '@dnd-kit/core'
import { apiClient, folderApi } from '@/lib/api-client'
import {
    FileText,
    Plus,
    Search,
    Folder,
    Trash2
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
    folder_id?: string | null
}

// --- Drag & Drop Components ---

function DraggableDocument({ doc, isActive }: {
    doc: Document,
    isActive: boolean
}) {
    const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
        id: `doc-${doc.id}`,
        data: { type: 'document', doc }
    })

    const style = transform ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
        opacity: isDragging ? 0.5 : 1,
        zIndex: isDragging ? 50 : undefined,
    } : undefined

    return (
        <li
            ref={setNodeRef}
            style={style}
            {...listeners}
            {...attributes}
            className="group relative touch-none"
        >
            <Link
                to="/admin/data/documents/$documentId"
                params={{ documentId: doc.id }}
                className={cn(
                    "flex items-center justify-between px-2 py-1.5 rounded-md text-sm transition-colors",
                    isActive
                        ? "bg-accent text-accent-foreground font-medium"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
            // Prevent link navigation when dragging if needed, but usually fine
            >
                <div className="flex items-center gap-2 overflow-hidden flex-1 pr-2">
                    <FileText className="w-3.5 h-3.5 shrink-0" />
                    <span className="truncate">{doc.title || doc.filename}</span>
                </div>
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
}

function DroppableFolder({ folder, isActiveFolder, onClick, onDelete }: {
    folder: { id: string, name: string, count: number, isReal?: boolean },
    isActiveFolder: boolean,
    onClick: (id: string) => void,
    onDelete: (id: string) => void
}) {
    const { setNodeRef, isOver } = useDroppable({
        id: `folder-${folder.id}`,
        data: { type: 'folder', folderId: folder.id }
    })

    // visual cue when dragging over
    const isOverStyles = isOver ? "bg-primary/20 ring-2 ring-primary ring-inset" : ""

    return (
        <div
            ref={setNodeRef}
            className={cn(
                "group flex items-center justify-between px-2 py-1.5 rounded-md text-sm cursor-pointer transition-colors",
                isActiveFolder
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted",
                isOverStyles
            )}
            onClick={() => onClick(folder.id)}
        >
            <div className="flex items-center gap-2 overflow-hidden">
                <Folder className={cn(
                    "w-4 h-4 shrink-0 transition-colors",
                    isActiveFolder ? "fill-muted-foreground/20" : "",
                    isOver ? "fill-primary text-primary" : ""
                )} />
                <span className="truncate">{folder.name}</span>
            </div>
            <div className="flex items-center gap-1">
                <span className="text-xs opacity-60 group-hover:opacity-100 transition-opacity">{folder.count}</span>
                {folder.isReal && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-5 w-5 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-destructive/10 hover:text-destructive"
                        onClick={(e) => {
                            e.stopPropagation()
                            if (confirm(`Delete folder "${folder.name}"? Documents will be unfiled.`)) {
                                onDelete(folder.id)
                            }
                        }}
                    >
                        <Trash2 className="w-3 h-3" />
                    </Button>
                )}
            </div>
        </div>
    )
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
    const [activeFolderId, setActiveFolderId] = useState<string>('all')
    const [isCreatingFolder, setIsCreatingFolder] = useState(false)
    const [newFolderName, setNewFolderName] = useState('')

    const routerState = useRouterState()
    const navigate = useNavigate()
    const currentPath = routerState.location.pathname
    const queryClient = useQueryClient()

    // Fetch documents
    const { data: documents, isLoading: isLoadingDocs } = useQuery({
        queryKey: ['documents'],
        queryFn: async () => {
            const response = await apiClient.get<Document[]>('/documents')
            return response.data
        }
    })

    // Fetch folders
    const { data: apiFolders } = useQuery({
        queryKey: ['folders'],
        queryFn: folderApi.list
    })

    // Mutations
    const createFolderMutation = useMutation({
        mutationFn: folderApi.create,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['folders'] })
            setIsCreatingFolder(false)
            setNewFolderName('')
        }
    })

    const deleteFolderMutation = useMutation({
        mutationFn: folderApi.delete,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['folders'] })
            queryClient.invalidateQueries({ queryKey: ['documents'] }) // Docs get unfiled
            if (activeFolderId !== 'all' && activeFolderId !== 'unfiled') {
                setActiveFolderId('all')
            }
        }
    })

    const moveDocMutation = useMutation({
        mutationFn: ({ docId, folderId }: { docId: string, folderId: string | null }) =>
            folderApi.updateDocumentFolder(docId, folderId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['documents'] })
            queryClient.invalidateQueries({ queryKey: ['folders'] }) // Counts might change if we tracked them
        }
    })

    // Filter documents
    const filteredDocuments = useMemo(() => {
        if (!documents) return []

        let filtered = documents

        // 1. Filter by Search
        if (searchQuery.trim()) {
            const query = searchQuery.toLowerCase()
            filtered = filtered.filter(doc =>
                doc.filename?.toLowerCase().includes(query) ||
                doc.title?.toLowerCase().includes(query)
            )
        }

        // 2. Filter by Folder
        if (activeFolderId === 'unfiled') {
            filtered = filtered.filter(doc => !doc.folder_id)
        } else if (activeFolderId !== 'all') {
            filtered = filtered.filter(doc => doc.folder_id === activeFolderId)
        }

        return filtered
    }, [documents, searchQuery, activeFolderId])



    // Computed folder list for UI
    const uiFolders = useMemo(() => {
        const allCount = documents?.length || 0
        const unfiledCount = documents?.filter(d => !d.folder_id).length || 0

        const base = [
            { id: 'all', name: 'All documents', count: allCount },
            { id: 'unfiled', name: 'Unfiled', count: unfiledCount },
        ]

        if (!apiFolders) return base

        const folderItems = apiFolders.map(f => ({
            id: f.id,
            name: f.name,
            count: documents?.filter(d => d.folder_id === f.id).length || 0,
            isReal: true
        }))

        return [...base, ...folderItems]
    }, [apiFolders, documents])

    const handleDragEnd = (event: DragEndEvent) => {
        const { active, over } = event

        if (!over) return

        const docId = active.id.toString().replace('doc-', '')
        const overId = over.id.toString().replace('folder-', '')

        // Logic to determine folderId
        let targetFolderId: string | null = null // default to unfiled (or safely null)

        if (overId === 'unfiled') {
            targetFolderId = null
        } else if (overId === 'all') {
            targetFolderId = null
        } else {
            targetFolderId = overId
        }

        moveDocMutation.mutate({ docId, folderId: targetFolderId })
    }

    return (
        <div className="flex flex-col h-full bg-muted/10 border-r">
            {/* Header: Navigation & Actions */}
            <div className="p-3 space-y-3">
                {/* Back to Dashboard / Overview Link */}
                {!collapsed && (
                    <h3 className="px-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                        Database
                    </h3>
                )}

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
                <>
                    <DndContext onDragEnd={handleDragEnd}>
                        <ScrollArea className="flex-1 px-3">
                            <div className="space-y-6">

                                {/* Folders Section */}
                                <div>
                                    <div className="flex items-center justify-between px-2 mb-2">
                                        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                                            Folders
                                        </h3>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-5 w-5 hover:bg-muted"
                                            onClick={() => setIsCreatingFolder(true)}
                                            title="New Folder"
                                        >
                                            <Plus className="w-3 h-3" />
                                        </Button>
                                    </div>

                                    {/* New Folder Input */}
                                    {isCreatingFolder && (
                                        <div className="px-2 mb-2">
                                            <div className="flex items-center gap-1">
                                                <Folder className="w-4 h-4 text-primary shrink-0" />
                                                <Input
                                                    autoFocus
                                                    value={newFolderName}
                                                    onChange={(e) => setNewFolderName(e.target.value)}
                                                    onBlur={() => !newFolderName && setIsCreatingFolder(false)}
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter') {
                                                            e.preventDefault()
                                                            if (newFolderName.trim()) {
                                                                createFolderMutation.mutate(newFolderName.trim())
                                                            }
                                                        } else if (e.key === 'Escape') {
                                                            setIsCreatingFolder(false)
                                                            setNewFolderName('')
                                                        }
                                                    }}
                                                    className="h-7 text-sm px-1.5 py-0"
                                                    placeholder="Folder name..."
                                                />
                                            </div>
                                        </div>
                                    )}

                                    <div className="space-y-0.5">
                                        {uiFolders.map(folder => (
                                            <DroppableFolder
                                                key={folder.id}
                                                folder={folder}
                                                isActiveFolder={activeFolderId === folder.id}
                                                onClick={setActiveFolderId}
                                                onDelete={(id) => deleteFolderMutation.mutate(id)}
                                            />
                                        ))}
                                    </div>
                                </div>

                                {/* Documents List Section */}
                                <div>
                                    <div className="flex items-center justify-between px-2 mb-2">
                                        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
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
                                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(e.target.value)}
                                        />
                                    </div>

                                    <ul className="space-y-0.5">
                                        {isLoadingDocs ? (
                                            <div className="px-2 py-2 text-xs text-muted-foreground">Loading...</div>
                                        ) : filteredDocuments.length === 0 ? (
                                            <div className="px-2 py-2 text-xs text-muted-foreground">
                                                {searchQuery ? "No matching documents" : "No documents in this view"}
                                            </div>
                                        ) : (
                                            filteredDocuments.map(doc => (
                                                <DraggableDocument
                                                    key={doc.id}
                                                    doc={doc}
                                                    isActive={currentPath.includes(doc.id)}
                                                />
                                            ))
                                        )}
                                    </ul>
                                </div>
                            </div>
                        </ScrollArea>
                    </DndContext>


                </>
            )}

            {/* Collapsed View Fallbacks - Minimal Icons */}
            {collapsed && (
                <div className="flex flex-col items-center gap-2 mt-4 px-2">
                    <Button variant="ghost" size="icon" title="Folders" onClick={() => navigate({ to: '/admin/data/documents' })}>
                        <Folder className="w-4 h-4" />
                    </Button>
                </div>
            )}
        </div>
    )
}
