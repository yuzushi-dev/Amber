import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearch, useNavigate } from '@tanstack/react-router'
import { apiClient } from '@/lib/api-client'
import { maintenanceApi } from '@/lib/api-admin'
import {
    FileText,
    Plus,
    Search,
    Trash2,
    Box,
    Users,
    Share2,
    Calendar,
    CheckSquare,
    X,
    ChevronLeft,
    ChevronRight,
    ArrowUp,
    ArrowDown,
    Filter,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/lib/utils'
import EmptyState from '@/components/ui/EmptyState'
import { useUploadStore } from '@/features/documents/stores/useUploadStore'
import { useAuth } from '@/features/auth'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import LiveStatusBadge from './LiveStatusBadge'
import DocumentShareDialog from './DocumentShareDialog'
import BulkDocumentShareDialog from './BulkDocumentShareDialog'
import { PageSkeleton } from '@/features/admin/components/PageSkeleton'

interface Document {
    id: string
    filename: string
    title: string
    status: string
    created_at: string
    source_type?: string
    error_message?: string
    tenant_id: string
    is_shared?: boolean
    owner_tenant_id?: string | null
    visible_from_tenant_id?: string | null
    share_mode?: string | null
    folder_id?: string | null
}

interface PagedDocumentsResponse {
    items: Document[]
    total: number
}

type ConfirmAction =
    | { type: 'delete-single'; documentId: string; documentTitle: string }
    | null

const STATUS_OPTIONS = ['all', 'pending', 'processing', 'ingested', 'failed'] as const
const SOURCE_OPTIONS = ['all', 'upload', 'url', 'connector'] as const
const SORT_OPTIONS = [
    { value: 'created_at', label: 'Date' },
    { value: 'filename', label: 'Filename' },
    { value: 'status', label: 'Status' },
]
const PAGE_SIZE = 50

function BulkShareActionBar({
    count,
    onClear,
    onManage,
}: {
    count: number
    onClear: () => void
    onManage: () => void
}) {
    return (
        <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
        >
            <div className="rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 shadow-sm">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-3">
                        <div className="rounded-full bg-primary/10 p-2 text-primary">
                            <CheckSquare className="h-4 w-4" />
                        </div>
                        <div>
                            <p className="text-sm font-medium text-foreground">
                                {count} document{count === 1 ? '' : 's'} selected
                            </p>
                            <p className="text-xs text-muted-foreground">
                                Apply tenant access changes to the current selection.
                            </p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <Button variant="ghost" size="sm" onClick={onClear}>
                            <X className="mr-2 h-4 w-4" />
                            Clear
                        </Button>
                        <Button size="sm" onClick={onManage}>
                            <Share2 className="mr-2 h-4 w-4" />
                            Manage Access
                        </Button>
                    </div>
                </div>
            </div>
        </motion.div>
    )
}

export default function DocumentLibrary() {
    const setUploadOpen = useUploadStore((state) => state.setOpen)
    const navigate = useNavigate()
    const search = useSearch({ strict: false }) as Record<string, unknown>

    const folderFilter = (search.folder_id as string | undefined) || undefined
    const [page, setPage] = useState(1)
    const [searchQuery, setSearchQuery] = useState('')
    const [debouncedQuery, setDebouncedQuery] = useState('')
    const [statusFilter, setStatusFilter] = useState<string>('all')
    const [sourceFilter, setSourceFilter] = useState<string>('all')
    const [sortBy, setSortBy] = useState<string>('created_at')
    const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

    const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null)
    const [shareDialogDocument, setShareDialogDocument] = useState<{ id: string; title: string } | null>(null)
    const [bulkShareDialogOpen, setBulkShareDialogOpen] = useState(false)
    const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(new Set())
    const [deleteError, setDeleteError] = useState<string | null>(null)

    const queryClient = useQueryClient()

    // Debounce search input
    useEffect(() => {
        const handle = setTimeout(() => setDebouncedQuery(searchQuery), 300)
        return () => clearTimeout(handle)
    }, [searchQuery])

    // Reset page when filters change
    useEffect(() => {
        // Intentional state sync: reset pagination to page 1 whenever filters change.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setPage(1)
    }, [debouncedQuery, statusFilter, sourceFilter, sortBy, sortDir, folderFilter])

    const queryParams = useMemo(
        () => ({
            limit: PAGE_SIZE,
            offset: (page - 1) * PAGE_SIZE,
            search: debouncedQuery || undefined,
            status: statusFilter === 'all' ? undefined : statusFilter,
            source_type: sourceFilter === 'all' ? undefined : sourceFilter,
            folder_id: folderFilter,
            sort_by: sortBy,
            sort_dir: sortDir,
        }),
        [page, debouncedQuery, statusFilter, sourceFilter, folderFilter, sortBy, sortDir]
    )

    const { data, isLoading, refetch } = useQuery({
        queryKey: ['documents', queryParams],
        queryFn: async () => {
            const response = await apiClient.get<PagedDocumentsResponse>('/documents', {
                params: queryParams,
            })
            return response.data
        },
        placeholderData: (prev) => prev,
    })

    const { tenantId, permissions } = useAuth()
    const isSuperAdmin = permissions.includes('super_admin')
    const isAdmin = permissions.includes('admin')
    const canManageShares = isSuperAdmin || (tenantId === 'default' && isAdmin)

    const { data: stats } = useQuery({
        queryKey: ['maintenance-stats'],
        queryFn: () => maintenanceApi.getStats(),
        refetchInterval: 30000,
        enabled: isSuperAdmin,
    })

    const documents = useMemo(() => data?.items ?? [], [data?.items])
    const total = data?.total ?? 0
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

    useEffect(() => {
        const validDocumentIds = new Set(documents.map((d) => d.id))
        // Intentional state sync: prune selection against the current document set;
        // the functional update is a no-op when nothing changed, so it cannot loop.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setSelectedDocumentIds((current) => {
            const next = new Set([...current].filter((id) => validDocumentIds.has(id)))
            return next.size === current.size ? current : next
        })
    }, [documents])

    const shareableDocuments = documents.filter(
        (d) => (d.owner_tenant_id ?? d.tenant_id) === 'default'
    )
    const selectedDocuments = documents.filter((d) => selectedDocumentIds.has(d.id))
    const allVisibleShareableSelected =
        shareableDocuments.length > 0 &&
        shareableDocuments.every((d) => selectedDocumentIds.has(d.id))

    const toggleDocumentSelection = (id: string, checked: boolean) => {
        setSelectedDocumentIds((current) => {
            const next = new Set(current)
            if (checked) next.add(id)
            else next.delete(id)
            return next
        })
    }

    const toggleSelectAllVisible = (checked: boolean) => {
        setSelectedDocumentIds((current) => {
            const next = new Set(current)
            shareableDocuments.forEach((d) => {
                if (checked) next.add(d.id)
                else next.delete(d.id)
            })
            return next
        })
    }

    const clearSelectedDocuments = () => setSelectedDocumentIds(new Set())

    const getDeleteErrorMessage = (error: unknown, fallback: string) => {
        if (error && typeof error === 'object') {
            const responseDetail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
            if (responseDetail) return responseDetail
            const message = (error as { message?: string }).message
            if (message) return message
        }
        return fallback
    }

    const deleteDocumentMutation = useMutation({
        mutationFn: async (documentId: string) => {
            await apiClient.delete(`/documents/${documentId}`)
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['documents'] })
            queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] })
            setConfirmAction(null)
            setDeleteError(null)
        },
        onError: (error) => {
            console.error('Failed to delete document:', error)
            setConfirmAction(null)
            setDeleteError(getDeleteErrorMessage(error, 'Failed to delete document. Please try again.'))
        },
    })

    const handleConfirmDelete = () => {
        if (!confirmAction) return
        if (confirmAction.type === 'delete-single') {
            deleteDocumentMutation.mutate(confirmAction.documentId)
        }
    }

    const listGridClass = canManageShares
        ? 'grid-cols-[40px_2fr_120px_150px_60px]'
        : 'grid-cols-[2fr_120px_150px_60px]'

    const clearFolderFilter = () => {
        navigate({ to: '/admin/data/documents', search: {} as never })
    }

    const toggleSort = (column: string) => {
        if (sortBy === column) {
            setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
        } else {
            setSortBy(column)
            setSortDir('desc')
        }
    }

    const renderEmptyState = () => (
        <EmptyState
            icon={<FileText className="w-12 h-12 text-muted-foreground" />}
            title={
                debouncedQuery || statusFilter !== 'all' || sourceFilter !== 'all' || folderFilter
                    ? 'No documents match the filters'
                    : 'No documents yet'
            }
            description={
                debouncedQuery || statusFilter !== 'all' || sourceFilter !== 'all' || folderFilter
                    ? 'Try clearing filters or search.'
                    : "Upload your first document to explore Amber's capabilities."
            }
            actions={
                <>
                    <Button onClick={() => setUploadOpen(true)} className="gap-2" aria-label="Upload a document">
                        <Plus className="w-4 h-4" aria-hidden="true" />
                        <span>Upload Document</span>
                    </Button>
                </>
            }
        />
    )

    if (isLoading && !data) {
        return <PageSkeleton mode="list" />
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-6">
            <header className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-display font-bold tracking-tight">Document Library</h1>
                    <p className="text-muted-foreground mt-1">Manage your ingested knowledge sources.</p>
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        onClick={() => setUploadOpen(true)}
                        className="shadow-glow hover:shadow-glow-lg transition-[box-shadow] duration-300 ease-out"
                        aria-label="Upload new document"
                    >
                        <Plus className="w-4 h-4 mr-2" aria-hidden="true" />
                        Upload Files
                    </Button>
                </div>
            </header>

            {deleteError && (
                <Alert variant="destructive" dismissible onDismiss={() => setDeleteError(null)}>
                    <AlertTitle>Delete failed</AlertTitle>
                    <AlertDescription>{deleteError}</AlertDescription>
                </Alert>
            )}

            {canManageShares && (
                <AnimatePresence>
                    {selectedDocuments.length > 0 && (
                        <BulkShareActionBar
                            count={selectedDocuments.length}
                            onClear={clearSelectedDocuments}
                            onManage={() => setBulkShareDialogOpen(true)}
                        />
                    )}
                </AnimatePresence>
            )}

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {[
                    {
                        label: 'Documents',
                        value: stats?.database.documents_total ?? total,
                        icon: FileText,
                        color: 'text-chart-1',
                    },
                    { label: 'Chunks', value: stats?.database.chunks_total ?? 0, icon: Box, color: 'text-chart-2' },
                    { label: 'Entities', value: stats?.database.entities_total ?? 0, icon: Users, color: 'text-chart-3' },
                    { label: 'Relationships', value: stats?.database.relationships_total ?? 0, icon: Share2, color: 'text-chart-4' },
                ].map((card) => (
                    <div
                        key={card.label}
                        className="relative overflow-hidden p-5 rounded-xl border border-white/5 bg-background/40 backdrop-blur-md shadow-lg"
                    >
                        <div className="flex justify-between items-start mb-2">
                            <p className="text-sm font-medium text-muted-foreground/80">{card.label}</p>
                            <card.icon className={cn('w-5 h-5', card.color)} />
                        </div>
                        <h2 className="text-3xl font-display font-bold tracking-tight">
                            {card.value.toLocaleString()}
                        </h2>
                    </div>
                ))}
            </div>

            <div className="rounded-xl border border-white/5 bg-background/20 backdrop-blur-md shadow-inner p-3 flex flex-wrap items-center gap-3">
                <div className="relative flex-1 min-w-[220px] max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
                    <Input
                        type="text"
                        placeholder="Search filename…"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        autoComplete="off"
                        className="w-full pl-10 pr-4 bg-transparent border-transparent focus-visible:ring-0 focus-visible:bg-foreground/5 text-sm h-9"
                        aria-label="Search documents by filename"
                    />
                </div>

                <div className="flex items-center gap-2 text-xs">
                    <Filter className="w-3.5 h-3.5 text-muted-foreground" />
                    <Select value={statusFilter} onValueChange={setStatusFilter}>
                        <SelectTrigger className="h-9 w-[140px]">
                            <SelectValue placeholder="Status" />
                        </SelectTrigger>
                        <SelectContent>
                            {STATUS_OPTIONS.map((s) => (
                                <SelectItem key={s} value={s}>{s === 'all' ? 'Any status' : s}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <Select value={sourceFilter} onValueChange={setSourceFilter}>
                        <SelectTrigger className="h-9 w-[140px]">
                            <SelectValue placeholder="Source" />
                        </SelectTrigger>
                        <SelectContent>
                            {SOURCE_OPTIONS.map((s) => (
                                <SelectItem key={s} value={s}>{s === 'all' ? 'Any source' : s}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <Select value={sortBy} onValueChange={setSortBy}>
                        <SelectTrigger className="h-9 w-[120px]">
                            <SelectValue placeholder="Sort by" />
                        </SelectTrigger>
                        <SelectContent>
                            {SORT_OPTIONS.map((s) => (
                                <SelectItem key={s.value} value={s.value}>Sort: {s.label}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    <Button
                        variant="ghost"
                        size="sm"
                        className="h-9 px-2"
                        onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
                        aria-label={`Sort direction ${sortDir}`}
                    >
                        {sortDir === 'asc' ? <ArrowUp className="w-4 h-4" /> : <ArrowDown className="w-4 h-4" />}
                    </Button>
                </div>

                {folderFilter && (
                    <Button variant="outline" size="sm" onClick={clearFolderFilter} className="text-xs h-8">
                        Folder filter <X className="w-3 h-3 ml-2" />
                    </Button>
                )}

                <div className="ml-auto text-xs text-muted-foreground">
                    {total.toLocaleString()} document{total === 1 ? '' : 's'}
                </div>
            </div>

            {documents.length === 0 ? (
                renderEmptyState()
            ) : (
                <div className="space-y-2">
                    <div
                        className={cn(
                            'grid gap-4 px-6 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider opacity-60',
                            listGridClass
                        )}
                    >
                        {canManageShares && (
                            <div className="flex justify-center">
                                <Checkbox
                                    aria-label="Select all shareable on this page"
                                    checked={allVisibleShareableSelected}
                                    disabled={shareableDocuments.length === 0}
                                    onCheckedChange={toggleSelectAllVisible}
                                />
                            </div>
                        )}
                        <button
                            onClick={() => toggleSort('filename')}
                            className="text-left hover:text-foreground transition-colors"
                        >
                            Document {sortBy === 'filename' && (sortDir === 'asc' ? '↑' : '↓')}
                        </button>
                        <button
                            onClick={() => toggleSort('status')}
                            className="text-left hover:text-foreground transition-colors"
                        >
                            Status {sortBy === 'status' && (sortDir === 'asc' ? '↑' : '↓')}
                        </button>
                        <button
                            onClick={() => toggleSort('created_at')}
                            className="text-left hover:text-foreground transition-colors"
                        >
                            Uploaded {sortBy === 'created_at' && (sortDir === 'asc' ? '↑' : '↓')}
                        </button>
                        <div className="text-right">Action</div>
                    </div>

                    <ul className="space-y-2">
                        {documents.map((doc) => {
                            const isShareableDocument = (doc.owner_tenant_id ?? doc.tenant_id) === 'default'
                            return (
                                <li key={doc.id} className="group">
                                    <div
                                        className={cn(
                                            'grid gap-4 items-center p-4 rounded-lg bg-background/40 backdrop-blur-sm border border-white/5 hover:bg-background/60 hover:border-border/60 transition-colors',
                                            listGridClass
                                        )}
                                    >
                                        {canManageShares && (
                                            <div className="flex justify-center">
                                                {isShareableDocument ? (
                                                    <Checkbox
                                                        aria-label={`Select ${doc.title}`}
                                                        checked={selectedDocumentIds.has(doc.id)}
                                                        onCheckedChange={(checked) => toggleDocumentSelection(doc.id, !!checked)}
                                                    />
                                                ) : (
                                                    <div className="h-4 w-4" />
                                                )}
                                            </div>
                                        )}

                                        <div className="flex items-center gap-4 min-w-0">
                                            <div className="p-2.5 rounded-lg bg-primary/10 text-primary ring-1 ring-primary/20 shrink-0">
                                                <FileText className="w-5 h-5" />
                                            </div>
                                            <div className="min-w-0">
                                                <Link
                                                    to={isAdmin ? '/admin/data/documents/$documentId' : '/amber/data/documents/$documentId'}
                                                    params={{ documentId: doc.id }}
                                                    className="font-medium text-base hover:text-primary transition-colors block truncate"
                                                >
                                                    {doc.title}
                                                </Link>
                                                <div className="text-xs text-muted-foreground truncate opacity-70">
                                                    {doc.filename}
                                                </div>
                                            </div>
                                        </div>

                                        <div>
                                            <LiveStatusBadge
                                                documentId={doc.id}
                                                initialStatus={doc.status}
                                                errorMessage={doc.error_message}
                                                onComplete={() => {
                                                    refetch()
                                                    queryClient.invalidateQueries({ queryKey: ['documents'] })
                                                    queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] })
                                                }}
                                            />
                                        </div>

                                        <div className="flex items-center text-sm text-muted-foreground">
                                            <Calendar className="w-3.5 h-3.5 mr-2 opacity-50" />
                                            {new Date(doc.created_at).toLocaleDateString()}
                                        </div>

                                        <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                            {canManageShares && isShareableDocument && (
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => setShareDialogDocument({ id: doc.id, title: doc.title })}
                                                    className="w-8 h-8 text-muted-foreground hover:text-primary hover:bg-primary/10"
                                                    title="Manage access"
                                                >
                                                    <Share2 className="w-4 h-4" />
                                                </Button>
                                            )}
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() =>
                                                    setConfirmAction({
                                                        type: 'delete-single',
                                                        documentId: doc.id,
                                                        documentTitle: doc.title,
                                                    })
                                                }
                                                className="w-8 h-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                                title="Delete document"
                                            >
                                                <Trash2 className="w-4 h-4" />
                                            </Button>
                                        </div>
                                    </div>
                                </li>
                            )
                        })}
                    </ul>

                    <div className="flex items-center justify-between pt-4">
                        <div className="text-xs text-muted-foreground">
                            Page {page} of {totalPages} · showing {documents.length} of {total.toLocaleString()}
                        </div>
                        <div className="flex items-center gap-2">
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setPage((p) => Math.max(1, p - 1))}
                                disabled={page <= 1}
                            >
                                <ChevronLeft className="w-4 h-4 mr-1" /> Prev
                            </Button>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                                disabled={page >= totalPages}
                            >
                                Next <ChevronRight className="w-4 h-4 ml-1" />
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            <ConfirmDialog
                open={confirmAction !== null}
                onOpenChange={(open) => !open && setConfirmAction(null)}
                title="Delete Document?"
                description={
                    confirmAction?.type === 'delete-single'
                        ? `Are you sure you want to delete "${confirmAction.documentTitle}"? This action cannot be undone.`
                        : ''
                }
                onConfirm={handleConfirmDelete}
                confirmText="Delete"
                variant="destructive"
                loading={deleteDocumentMutation.isPending}
            />

            {shareDialogDocument && (
                <DocumentShareDialog
                    open={shareDialogDocument !== null}
                    onOpenChange={(open) => !open && setShareDialogDocument(null)}
                    documentId={shareDialogDocument.id}
                    documentTitle={shareDialogDocument.title}
                    onSaved={() => {
                        queryClient.invalidateQueries({ queryKey: ['documents'] })
                    }}
                />
            )}

            {selectedDocuments.length > 0 && (
                <BulkDocumentShareDialog
                    open={bulkShareDialogOpen}
                    onOpenChange={setBulkShareDialogOpen}
                    documentIds={selectedDocuments.map((d) => d.id)}
                    documentTitles={selectedDocuments.map((d) => d.title)}
                    onSaved={() => {
                        queryClient.invalidateQueries({ queryKey: ['documents'] })
                        clearSelectedDocuments()
                    }}
                />
            )}
        </div>
    )
}
