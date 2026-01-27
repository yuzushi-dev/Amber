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
    type DragEndEvent,
    useSensor,
    useSensors,
    PointerSensor,
    KeyboardSensor
} from '@dnd-kit/core'
import { apiClient, folderApi } from '@/lib/api-client'
import {
    FileText,
    Plus,
    Search,
    Folder,
    Trash2,
    Layers,
    Network,
    X
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'

import { AnimatePresence, motion } from 'framer-motion'
import { Checkbox } from "@/components/ui/checkbox"
import { BulkDeleteModal, type BulkDeleteItem } from './BulkDeleteModal'

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

function DraggableDocument({ doc, isActive, isSelected, selectionMode, onSelect, onNavigate }: {
    doc: Document,
    isActive: boolean
    isSelected: boolean
    selectionMode: boolean
    onSelect: (id: string, multi: boolean, range: boolean) => void
    onNavigate: () => void
}) {
    // const navigate = useNavigate() // moved to parent for better control
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
            className={cn(
                "group/item relative touch-none",
                isSelected && "z-10"
            )}
            onClick={(e) => {
                if (e.metaKey || e.ctrlKey) {
                    onSelect(doc.id, true, false)
                    return
                }
                if (e.shiftKey) {
                    onSelect(doc.id, true, true)
                    return
                }
                onNavigate()
            }}
        >
            <div
                className={cn(
                    "flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-colors cursor-pointer border-l-2 border-transparent",
                    isActive && !isSelected
                        ? "bg-accent text-accent-foreground font-medium"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    isSelected && "bg-primary/5 border-primary text-foreground"
                )}
            >
                {/* Checkbox - Reveal on hover or if selected or if in selection mode */}
                <div
                    className={cn(
                        "transition-[width,opacity,margin-right] duration-200 overflow-hidden w-0 opacity-0 mr-0",
                        (isSelected || selectionMode) ? "w-5 opacity-100 mr-2" : "group-hover/item:w-5 group-hover/item:opacity-100 group-hover/item:mr-2"
                    )}
                    onClick={(e) => e.stopPropagation()} // Prevent row click
                >
                    <Checkbox
                        checked={isSelected}
                        onCheckedChange={() => onSelect(doc.id, true, false)}
                        className="data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                    />
                </div>

                <div className="flex items-center gap-2 overflow-hidden flex-1">
                    <FileText className={cn("w-3.5 h-3.5 shrink-0 transition-colors", isSelected && "text-primary")} />
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
            </div>
        </li>
    )
}

function DroppableFolder({ folder, isActiveFolder, isSelected, selectionMode, onClick, onSelect }: {
    folder: { id: string, name: string, count: number, isReal?: boolean },
    isActiveFolder: boolean,
    isSelected: boolean,
    selectionMode: boolean,
    onClick: (id: string) => void,
    onSelect: (id: string, multi: boolean, range: boolean) => void
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
                "group/item flex items-center justify-between px-2 py-1.5 rounded-md text-sm cursor-pointer transition-colors border-l-2 border-transparent",
                isActiveFolder && !isSelected
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted",
                isSelected && "bg-primary/5 border-primary text-foreground",
                isOverStyles
            )}
            onClick={(e) => {
                if (e.metaKey || e.ctrlKey) {
                    onSelect(folder.id, true, false)
                    return
                }
                if (e.shiftKey) {
                    onSelect(folder.id, true, true)
                    return
                }
                onClick(folder.id)
            }}
        >
            <div className="flex items-center gap-2 overflow-hidden flex-1">
                {/* Checkbox - Reveal on hover or if selected or if in selection mode */}
                {/* Only show checkbox for real folders (or all if we support deleting special ones? No, only real) */}
                {folder.isReal && (
                    <div
                        className={cn(
                            "transition-[width,opacity,margin-right] duration-200 overflow-hidden w-0 opacity-0 mr-0",
                            (isSelected || selectionMode) ? "w-5 opacity-100 mr-2" : "group-hover/item:w-5 group-hover/item:opacity-100 group-hover/item:mr-2"
                        )}
                        onClick={(e) => e.stopPropagation()} // Prevent row click
                    >
                        <Checkbox
                            checked={isSelected}
                            onCheckedChange={() => onSelect(folder.id, true, false)}
                            className="data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                        />
                    </div>
                )}

                <Folder className={cn(
                    "w-4 h-4 shrink-0 transition-colors",
                    isActiveFolder ? "fill-muted-foreground/20" : "",
                    isOver ? "fill-primary text-primary" : "",
                    isSelected && "fill-primary/20 text-primary"
                )} />
                <span className="truncate">{folder.name}</span>
            </div>

            <div className="flex items-center gap-1">
                <span className="text-xs opacity-60 group-hover/item:opacity-100 transition-opacity">{folder.count}</span>
            </div>
        </div>
    )
}

// import { DeleteFolderModal } from './DeleteFolderModal'

interface DatabaseSidebarContentProps {
    collapsed?: boolean
    onUploadClick?: () => void
}

// Helper Component for Contextual Actions
function BulkActionBar({ count, onClear, onDelete }: { count: number, onClear: () => void, onDelete: () => void }) {
    return (
        <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
        >
            <div className="mx-2 mb-2 p-1.5 rounded-md bg-primary/10 border border-primary/20 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-primary ml-1">{count} Selected</span>
                </div>
                <div className="flex items-center gap-1">
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 hover:bg-primary/20 text-primary"
                        onClick={onClear}
                        title="Clear Selection"
                    >
                        <X className="w-3.5 h-3.5" />
                    </Button>
                    <Button
                        variant="destructive"
                        size="sm"
                        className="h-6 text-[10px] px-2 gap-1.5 shadow-none"
                        onClick={onDelete}
                    >
                        <Trash2 className="w-3 h-3" />
                        Delete
                    </Button>
                </div>
            </div>
        </motion.div>
    )
}

export default function DatabaseSidebarContent({
    collapsed = false,
    onUploadClick
}: DatabaseSidebarContentProps) {
    const [selectedFolderIds, setSelectedFolderIds] = useState<Set<string>>(new Set())
    const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(new Set())
    const [bulkDeleteItems, setBulkDeleteItems] = useState<BulkDeleteItem[] | null>(null)

    const [searchQuery, setSearchQuery] = useState('')
    const [activeFolderId, setActiveFolderId] = useState<string>('all')
    const [isCreatingFolder, setIsCreatingFolder] = useState(false)
    const [newFolderName, setNewFolderName] = useState('')

    // Derived state for selection mode and last item for range select
    const isSelectionMode = selectedFolderIds.size > 0 || selectedDocumentIds.size > 0
    const [lastSelectedId, setLastSelectedId] = useState<string | null>(null)

    const routerState = useRouterState()
    const navigate = useNavigate()
    const currentPath = routerState.location.pathname
    const queryClient = useQueryClient()

    // Sensors for drag and drop
    const sensors = useSensors(
        useSensor(PointerSensor, {
            activationConstraint: {
                distance: 8,
            },
        }),
        useSensor(KeyboardSensor)
    )

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

    // const deleteFolderMutation = useMutation({
    //     mutationFn: ({ id, deleteContents }: { id: string, deleteContents: boolean }) =>
    //         folderApi.delete(id, deleteContents),
    //     onSuccess: () => {
    //         queryClient.invalidateQueries({ queryKey: ['folders'] })
    //         queryClient.invalidateQueries({ queryKey: ['documents'] })
    //         queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] })
    //         if (activeFolderId !== 'all' && activeFolderId !== 'unfiled') {
    //             setActiveFolderId('all')
    //         }
    //     }
    // })

    const moveDocMutation = useMutation({
        mutationFn: ({ docId, folderId }: { docId: string, folderId: string | null }) =>
            folderApi.updateDocumentFolder(docId, folderId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['documents'] })
            queryClient.invalidateQueries({ queryKey: ['folders'] }) // Counts might change if we tracked them
        }
    })

    // --- Selection Logic ---

    // Toggle Folder Selection
    const toggleFolderSelect = (id: string, _multi: boolean, range: boolean) => {
        // Enforce exclusivity: Clear docs if selecting folder
        if (selectedDocumentIds.size > 0) {
            setSelectedDocumentIds(new Set())
        }

        const newSet = new Set(selectedFolderIds)

        // Simple toggle if not range or range not possible
        if (!range || !lastSelectedId || !uiFolders.find(f => f.id === lastSelectedId)) {
            if (newSet.has(id)) {
                newSet.delete(id)
            } else {
                newSet.add(id)
            }
            setLastSelectedId(id)
            setSelectedFolderIds(newSet)
            return
        }

        // Handle Range Selection (Shift+Click)
        // Find index of last selected and current
        const allItems = uiFolders.filter(f => f.isReal) // only real folders selectable?
        const lastIdx = allItems.findIndex(f => f.id === lastSelectedId)
        const currentIdx = allItems.findIndex(f => f.id === id)

        if (lastIdx !== -1 && currentIdx !== -1) {
            const start = Math.min(lastIdx, currentIdx)
            const end = Math.max(lastIdx, currentIdx)
            const rangeIds = allItems.slice(start, end + 1).map(f => f.id)

            // Add all in range
            rangeIds.forEach(rid => newSet.add(rid))
        }

        setLastSelectedId(id)
        setSelectedFolderIds(newSet)
    }

    // Toggle Document Selection
    const toggleDocumentSelect = (id: string, _multi: boolean, _range: boolean) => {
        // Enforce exclusivity: Clear folders if selecting doc
        if (selectedFolderIds.size > 0) {
            setSelectedFolderIds(new Set())
        }

        const newSet = new Set(selectedDocumentIds)

        // Simple toggle logic for now (Range selection usually needs flattened list index)
        if (newSet.has(id)) {
            newSet.delete(id)
        } else {
            newSet.add(id)
        }

        // Basic range logic if needed, but let's stick to simple first
        setLastSelectedId(id)
        setSelectedDocumentIds(newSet)
    }

    const clearSelection = () => {
        setSelectedFolderIds(new Set())
        setSelectedDocumentIds(new Set())
        setLastSelectedId(null)
    }

    const initiateBulkDelete = () => {
        const items: BulkDeleteItem[] = []

        if (selectedFolderIds.size > 0) {
            uiFolders.forEach(f => {
                if (selectedFolderIds.has(f.id)) {
                    items.push({ id: f.id, title: f.name, type: 'folder' })
                }
            })
        }

        if (selectedDocumentIds.size > 0) {
            filteredDocuments.forEach(d => {
                if (selectedDocumentIds.has(d.id)) {
                    items.push({ id: d.id, title: d.title || d.filename, type: 'document' })
                }
            })
        }

        setBulkDeleteItems(items)
    }

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
            { id: 'all', name: 'All documents', count: allCount, isReal: false },
            { id: 'unfiled', name: 'Unfiled', count: unfiledCount, isReal: false },
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
            <div className="p-3 space-y-3 relative overflow-hidden min-h-[85px]">
                <AnimatePresence mode="popLayout" initial={false}>
                    {/* Default Actions - Always visible now, as bulk actions are local */}
                    <div className="w-full">
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
                </AnimatePresence>
            </div>

            {/* System Navigation */}
            {!collapsed && (
                <div className="px-3 pb-3 space-y-0.5">
                    <Link
                        to="/admin/data/documents"
                        className={cn(
                            "flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-colors",
                            currentPath === '/admin/data/documents' || currentPath.startsWith('/admin/data/documents/')
                                ? "bg-muted text-foreground font-medium"
                                : "text-muted-foreground hover:bg-muted hover:text-foreground"
                        )}
                    >
                        <FileText className="w-4 h-4 shrink-0" />
                        <span>Documents</span>
                    </Link>

                    <Link
                        to="/admin/data/vectors"
                        className={cn(
                            "flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-colors",
                            currentPath.startsWith('/admin/data/vectors')
                                ? "bg-muted text-foreground font-medium"
                                : "text-muted-foreground hover:bg-muted hover:text-foreground"
                        )}
                    >
                        <Layers className="w-4 h-4 shrink-0" />
                        <span>Vector Store</span>
                    </Link>
                    <Link
                        to="/admin/data/graph"
                        className={cn(
                            "flex items-center gap-2 px-2 py-1.5 rounded-md text-sm transition-colors",
                            currentPath.startsWith('/admin/data/graph')
                                ? "bg-muted text-foreground font-medium"
                                : "text-muted-foreground hover:bg-muted hover:text-foreground"
                        )}
                    >
                        <Network className="w-4 h-4 shrink-0" />
                        <span>Global Graph</span>
                    </Link>
                </div>
            )}

            {/* Content: Folders & Files */}
            {!collapsed && (
                <>
                    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
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

                                    {/* Contextual Bulk Actions: Folders */}
                                    <AnimatePresence>
                                        {selectedFolderIds.size > 0 && (
                                            <BulkActionBar
                                                count={selectedFolderIds.size}
                                                onClear={clearSelection}
                                                onDelete={initiateBulkDelete}
                                            />
                                        )}
                                    </AnimatePresence>

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
                                                isSelected={selectedFolderIds.has(folder.id)}
                                                selectionMode={isSelectionMode && selectedFolderIds.size > 0}
                                                onClick={setActiveFolderId}
                                                onSelect={toggleFolderSelect}
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

                                    {/* Contextual Bulk Actions: Documents */}
                                    <AnimatePresence>
                                        {selectedDocumentIds.size > 0 && (
                                            <BulkActionBar
                                                count={selectedDocumentIds.size}
                                                onClear={clearSelection}
                                                onDelete={initiateBulkDelete}
                                            />
                                        )}
                                    </AnimatePresence>

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
                                                    isSelected={selectedDocumentIds.has(doc.id)}
                                                    selectionMode={isSelectionMode && selectedDocumentIds.size > 0}
                                                    onSelect={toggleDocumentSelect}
                                                    onNavigate={() => navigate({ to: '/admin/data/documents/$documentId', params: { documentId: doc.id } })}
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

            {bulkDeleteItems && (
                <BulkDeleteModal
                    open={!!bulkDeleteItems}
                    onOpenChange={(open) => !open && setBulkDeleteItems(null)}
                    items={bulkDeleteItems}
                    onComplete={() => {
                        setBulkDeleteItems(null)
                        clearSelection()
                        // refresh logichandled in modal on success
                        queryClient.invalidateQueries({ queryKey: ['folders'] })
                        queryClient.invalidateQueries({ queryKey: ['documents'] })
                    }}
                />
            )}
        </div>
    )
}
