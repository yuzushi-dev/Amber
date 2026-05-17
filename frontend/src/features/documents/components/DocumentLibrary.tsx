import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
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
import { useFuzzySearch } from '@/hooks/useFuzzySearch'
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
}

type ConfirmAction =
    | { type: 'delete-single'; documentId: string; documentTitle: string }
    | { type: 'delete-all' }
    | null

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
                            <p className="text-sm font-medium text-foreground">{count} document{count === 1 ? '' : 's'} selected</p>
                            <p className="text-xs text-muted-foreground">Apply tenant access changes to the current selection.</p>
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
    const setUploadOpen = useUploadStore(state => state.setOpen)
    const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null)
    const [shareDialogDocument, setShareDialogDocument] = useState<{ id: string; title: string } | null>(null)
    const [bulkShareDialogOpen, setBulkShareDialogOpen] = useState(false)
    const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(new Set())
    const [searchQuery, setSearchQuery] = useState('')
    const [deleteError, setDeleteError] = useState<string | null>(null)

    const queryClient = useQueryClient()

    const { data: documents, isLoading, refetch } = useQuery({
        queryKey: ['documents'],
        queryFn: async () => {
            const response = await apiClient.get<Document[]>('/documents', { params: { limit: 10000 } })
            return response.data
        }
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

    const fuseKeys = useMemo(() => ['title', 'filename', 'source_type'] as const, [])
    const filteredDocuments = useFuzzySearch(documents || [], searchQuery, {
        keys: fuseKeys,
        threshold: 0.4,
    })

    useEffect(() => {
        if (!documents) return

        const validDocumentIds = new Set(documents.map((document) => document.id))

        setSelectedDocumentIds((current) => {
            const next = new Set([...current].filter((documentId) => validDocumentIds.has(documentId)))
            return next.size === current.size ? current : next
        })
    }, [documents])

    const allDocuments = documents || []
    const shareableDocuments = filteredDocuments.filter(
        (document) => (document.owner_tenant_id ?? document.tenant_id) === 'default'
    )
    const selectedDocuments = allDocuments.filter((document) => selectedDocumentIds.has(document.id))
    const allVisibleShareableSelected =
        shareableDocuments.length > 0 &&
        shareableDocuments.every((document) => selectedDocumentIds.has(document.id))

    const toggleDocumentSelection = (documentId: string, checked: boolean) => {
        setSelectedDocumentIds((current) => {
            const next = new Set(current)
            if (checked) {
                next.add(documentId)
            } else {
                next.delete(documentId)
            }
            return next
        })
    }

    const toggleSelectAllVisible = (checked: boolean) => {
        setSelectedDocumentIds((current) => {
            const next = new Set(current)
            if (checked) {
                shareableDocuments.forEach((document) => next.add(document.id))
            } else {
                shareableDocuments.forEach((document) => next.delete(document.id))
            }
            return next
        })
    }

    const clearSelectedDocuments = () => {
        setSelectedDocumentIds(new Set())
    }

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
        }
    })

    const deleteAllDocumentsMutation = useMutation({
        mutationFn: async () => {
            if (!documents) return
            const deletePromises = documents.map(doc =>
                apiClient.delete(`/documents/${doc.id}`)
            )

            const results = await Promise.allSettled(deletePromises)
            const failed = results.filter(result => result.status === 'rejected')

            if (failed.length > 0) {
                throw new Error(`Failed to delete ${failed.length} of ${documents.length} documents.`)
            }
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['documents'] })
            queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] })
            setConfirmAction(null)
            setDeleteError(null)
        },
        onError: (error) => {
            console.error('Failed to delete all documents:', error)
            setConfirmAction(null)
            setDeleteError(getDeleteErrorMessage(error, 'Failed to delete all documents. Please try again.'))
        }
    })

    const handleConfirmDelete = () => {
        if (!confirmAction) return

        if (confirmAction.type === 'delete-single') {
            deleteDocumentMutation.mutate(confirmAction.documentId)
        } else if (confirmAction.type === 'delete-all') {
            deleteAllDocumentsMutation.mutate()
        }
    }

    const isDeleting = deleteDocumentMutation.isPending || deleteAllDocumentsMutation.isPending
    const listGridClass = canManageShares
        ? 'grid-cols-[40px_2fr_120px_150px_60px]'
        : 'grid-cols-[2fr_120px_150px_60px]'

    const renderEmptyState = () => (
        <EmptyState
            icon={<FileText className="w-12 h-12 text-muted-foreground" />}
            title="No documents yet"
            description="Upload your first document or try our sample datasets to explore Amber's capabilities."
            actions={
                <>
                    <Button
                        onClick={() => setUploadOpen(true)}
                        className="gap-2"
                        aria-label="Upload a document"
                    >
                        <Plus className="w-4 h-4" aria-hidden="true" />
                        <span>Upload Document</span>
                    </Button>
                </>
            }
        />
    )

    if (isLoading) {
        return <PageSkeleton mode="list" />
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
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
                <Alert
                    variant="destructive"
                    dismissible
                    onDismiss={() => setDeleteError(null)}
                >
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
                        value: stats?.database.documents_total ?? 0,
                        icon: FileText,
                        color: 'text-chart-1',
                        gradient: 'from-chart-1/20 to-chart-1/5'
                    },
                    {
                        label: 'Chunks',
                        value: stats?.database.chunks_total ?? 0,
                        icon: Box,
                        color: 'text-chart-2',
                        gradient: 'from-chart-2/20 to-chart-2/5'
                    },
                    {
                        label: 'Entities',
                        value: stats?.database.entities_total ?? 0,
                        icon: Users,
                        color: 'text-chart-3',
                        gradient: 'from-chart-3/20 to-chart-3/5'
                    },
                    {
                        label: 'Relationships',
                        value: stats?.database.relationships_total ?? 0,
                        icon: Share2,
                        color: 'text-chart-4',
                        gradient: 'from-chart-4/20 to-chart-4/5'
                    }
                ].map((card, idx) => (
                    <motion.div
                        key={card.label}
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: idx * 0.05 }}
                        className="relative overflow-hidden p-5 rounded-xl border border-white/5 bg-background/40 backdrop-blur-md shadow-lg group"
                    >
                        <div className={`absolute inset-0 bg-gradient-to-br ${card.gradient} opacity-0 group-hover:opacity-100 transition-opacity duration-500`} />
                        <div className="relative z-10 flex flex-col h-full justify-between">
                            <div className="flex justify-between items-start mb-2">
                                <p className="text-sm font-medium text-muted-foreground/80">{card.label}</p>
                                <card.icon className={cn("w-5 h-5", card.color)} />
                            </div>
                            <h2 className="text-3xl font-display font-bold tracking-tight">{card.value.toLocaleString()}</h2>
                        </div>
                    </motion.div>
                ))}
            </div>

            <div className="space-y-4">
                <div className="p-2 rounded-xl border border-white/5 bg-background/20 backdrop-blur-md flex justify-between items-center shadow-inner">
                    <div className="relative w-full max-w-md">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
                        <Input
                            type="text"
                            placeholder="Filter documents…"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            name="document-filter"
                            autoComplete="off"
                            className="w-full pl-10 pr-4 bg-transparent border-transparent focus-visible:ring-0 focus-visible:bg-foreground/5 transition-[background-color,box-shadow] duration-200 ease-out text-sm placeholder:text-muted-foreground/50 h-9"
                            aria-label="Filter documents"
                        />
                    </div>
                    <div className="flex items-center pr-2">
                        {documents && documents.length > 0 && (
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setConfirmAction({ type: 'delete-all' })}
                                className="text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                            >
                                <Trash2 className="w-4 h-4 mr-2" />
                                Delete All
                            </Button>
                        )}
                    </div>
                </div>

                {documents?.length === 0 ? (
                    renderEmptyState()
                ) : (
                    <div className="space-y-2">
                        <div className={cn("grid gap-4 px-6 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider opacity-60", listGridClass)}>
                            {canManageShares && (
                                <div className="flex justify-center">
                                    <Checkbox
                                        aria-label="Select all shareable documents"
                                        checked={allVisibleShareableSelected}
                                        disabled={shareableDocuments.length === 0}
                                        onCheckedChange={toggleSelectAllVisible}
                                    />
                                </div>
                            )}
                            <div>Document</div>
                            <div>Status</div>
                            <div>Uploaded</div>
                            <div className="text-right">Action</div>
                        </div>

                        <ul className="space-y-2">
                            <AnimatePresence mode='popLayout'>
                                {filteredDocuments.map((doc, idx) => {
                                    const isShareableDocument = (doc.owner_tenant_id ?? doc.tenant_id) === 'default'

                                    return (
                                        <motion.li
                                            key={doc.id}
                                            layout
                                            initial={{ opacity: 0, x: -10 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            exit={{ opacity: 0, scale: 0.95 }}
                                            transition={{ duration: 0.2, delay: idx * 0.03 }}
                                            className="group"
                                        >
                                            <div className={cn("grid gap-4 items-center p-4 rounded-lg bg-background/40 backdrop-blur-sm border border-white/5 hover:bg-background/60 hover:border-border/60 hover:shadow-lg transition-[background-color,border-color,box-shadow] duration-300 ease-out", listGridClass)}>
                                                {canManageShares && (
                                                    <div className="flex justify-center">
                                                        {isShareableDocument ? (
                                                            <Checkbox
                                                                aria-label={`Select ${doc.title}`}
                                                                checked={selectedDocumentIds.has(doc.id)}
                                                                onCheckedChange={(checked) => toggleDocumentSelection(doc.id, checked)}
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
                                                        {isAdmin ? (
                                                            <Link
                                                                to="/admin/data/documents/$documentId"
                                                                params={{ documentId: doc.id }}
                                                                className="font-medium text-base hover:text-primary transition-colors block truncate"
                                                            >
                                                                {doc.title}
                                                            </Link>
                                                        ) : (
                                                            <Link
                                                                to="/amber/data/documents/$documentId"
                                                                params={{ documentId: doc.id }}
                                                                className="font-medium text-base hover:text-primary transition-colors block truncate"
                                                            >
                                                                {doc.title}
                                                            </Link>
                                                        )}
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
                                                            queryClient.invalidateQueries({ queryKey: ['documents'] });
                                                            queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] });
                                                            queryClient.invalidateQueries({ queryKey: ['graph-top-nodes'] });
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
                                                        onClick={() => setConfirmAction({ type: 'delete-single', documentId: doc.id, documentTitle: doc.title })}
                                                        className="w-8 h-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                                        title="Delete document"
                                                    >
                                                        <Trash2 className="w-4 h-4" />
                                                    </Button>
                                                </div>
                                            </div>
                                        </motion.li>
                                    )
                                })}
                            </AnimatePresence>
                        </ul>
                    </div>
                )}
            </div>

            <ConfirmDialog
                open={confirmAction !== null}
                onOpenChange={(open) => !open && setConfirmAction(null)}
                title={confirmAction?.type === 'delete-single' ? 'Delete Document?' : 'Delete All Documents?'}
                description={
                    confirmAction?.type === 'delete-single'
                        ? `Are you sure you want to delete "${confirmAction.documentTitle}"? This action cannot be undone.`
                        : `Are you sure you want to delete all ${documents?.length || 0} documents? This action cannot be undone.`
                }
                onConfirm={handleConfirmDelete}
                confirmText="Delete"
                variant="destructive"
                loading={isDeleting}
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
                    documentIds={selectedDocuments.map((document) => document.id)}
                    documentTitles={selectedDocuments.map((document) => document.title)}
                    onSaved={() => {
                        queryClient.invalidateQueries({ queryKey: ['documents'] })
                        clearSelectedDocuments()
                    }}
                />
            )}
        </div>
    )
}
