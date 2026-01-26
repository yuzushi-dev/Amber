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
    Calendar
} from 'lucide-react'
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/lib/utils'
import UploadWizard from './UploadWizard'
import EmptyState from '@/components/ui/EmptyState'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useFuzzySearch } from '@/hooks/useFuzzySearch'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import LiveStatusBadge from './LiveStatusBadge'
import { PageSkeleton } from '@/features/admin/components/PageSkeleton'

interface Document {
    id: string
    filename: string
    title: string  // Alias for filename from backend
    status: string
    created_at: string
    source_type?: string
}

type ConfirmAction =
    | { type: 'delete-single'; documentId: string; documentTitle: string }
    | { type: 'delete-all' }
    | null

export default function DocumentLibrary() {
    const [isUploadOpen, setIsUploadOpen] = useState(false)
    const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null)
    const [searchQuery, setSearchQuery] = useState('')
    const [deleteError, setDeleteError] = useState<string | null>(null)

    const queryClient = useQueryClient()

    const { data: documents, isLoading, refetch } = useQuery({
        queryKey: ['documents'],
        queryFn: async () => {
            const response = await apiClient.get<Document[]>('/documents')
            return response.data
        }
    })

    const { data: stats } = useQuery({
        queryKey: ['maintenance-stats'],
        queryFn: () => maintenanceApi.getStats(),
        refetchInterval: 30000,
    })

    // Apply fuzzy search directly
    const filteredDocuments = useFuzzySearch(documents || [], searchQuery, {
        keys: ['title', 'filename', 'source_type'],
        threshold: 0.4,
    })

    const getDeleteErrorMessage = (error: unknown, fallback: string) => {
        if (error && typeof error === 'object') {
            const responseDetail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
            if (responseDetail) return responseDetail

            const message = (error as { message?: string }).message
            if (message) return message
        }
        return fallback
    }

    // Delete single document mutation
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

    // Delete all documents mutation
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

    // Render empty state with actionable CTAs
    const renderEmptyState = () => (
        <EmptyState
            icon={<FileText className="w-12 h-12 text-muted-foreground" />}
            title="No documents yet"
            description="Upload your first document or try our sample datasets to explore Amber's capabilities."
            actions={
                <>
                    <Button
                        onClick={() => setIsUploadOpen(true)}
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
                        onClick={() => setIsUploadOpen(true)}
                        className="shadow-[0_0_15px_rgba(251,191,36,0.3)] hover:shadow-[0_0_25px_rgba(251,191,36,0.5)] transition-all duration-300"
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

            {/* Glass Stats Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {[
                    {
                        label: 'Documents',
                        value: stats?.database.documents_total ?? 0,
                        icon: FileText,
                        color: 'text-blue-400',
                        gradient: 'from-blue-500/20 to-blue-600/5'
                    },
                    {
                        label: 'Chunks',
                        value: stats?.database.chunks_total ?? 0,
                        icon: Box,
                        color: 'text-purple-400',
                        gradient: 'from-purple-500/20 to-purple-600/5'
                    },
                    {
                        label: 'Entities',
                        value: stats?.database.entities_total ?? 0,
                        icon: Users,
                        color: 'text-green-400',
                        gradient: 'from-green-500/20 to-green-600/5'
                    },
                    {
                        label: 'Relationships',
                        value: stats?.database.relationships_total ?? 0,
                        icon: Share2,
                        color: 'text-orange-400',
                        gradient: 'from-orange-500/20 to-orange-600/5'
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
                {/* Filter Bar */}
                <div className="p-2 rounded-xl border border-white/5 bg-black/20 backdrop-blur-md flex justify-between items-center shadow-inner">
                    <div className="relative w-full max-w-md">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
                        <Input
                            type="text"
                            placeholder="Filter documents..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full pl-10 pr-4 bg-transparent border-transparent focus-visible:ring-0 focus-visible:bg-white/5 transition-all text-sm placeholder:text-muted-foreground/50 h-9"
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
                    /* Premium Glass List */
                    <div className="space-y-2">
                        {/* Header Row */}
                        <div className="grid grid-cols-[2fr_120px_150px_60px] gap-4 px-6 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider opacity-60">
                            <div>Document</div>
                            <div>Status</div>
                            <div>Uploaded</div>
                            <div className="text-right">Action</div>
                        </div>

                        <ul className="space-y-2">
                            <AnimatePresence mode='popLayout'>
                                {filteredDocuments.map((doc, idx) => (
                                    <motion.li
                                        key={doc.id}
                                        layout
                                        initial={{ opacity: 0, x: -10 }}
                                        animate={{ opacity: 1, x: 0 }}
                                        exit={{ opacity: 0, scale: 0.95 }}
                                        transition={{ duration: 0.2, delay: idx * 0.03 }}
                                        className="group"
                                    >
                                        <div className="grid grid-cols-[2fr_120px_150px_60px] gap-4 items-center p-4 rounded-lg bg-background/40 backdrop-blur-sm border border-white/5 hover:bg-background/60 hover:border-white/10 hover:shadow-lg transition-all duration-300">
                                            {/* Column 1: Title & Icon */}
                                            <div className="flex items-center gap-4 min-w-0">
                                                <div className="p-2.5 rounded-lg bg-primary/10 text-primary ring-1 ring-primary/20 shrink-0">
                                                    <FileText className="w-5 h-5" />
                                                </div>
                                                <div className="min-w-0">
                                                    <Link
                                                        to="/admin/data/documents/$documentId"
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

                                            {/* Column 2: Status */}
                                            <div>
                                                <LiveStatusBadge
                                                    documentId={doc.id}
                                                    initialStatus={doc.status}
                                                    onComplete={() => {
                                                        refetch()
                                                        queryClient.invalidateQueries({ queryKey: ['documents'] });
                                                        queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] });
                                                        queryClient.invalidateQueries({ queryKey: ['graph-top-nodes'] });
                                                    }}
                                                />
                                            </div>

                                            {/* Column 3: Date */}
                                            <div className="flex items-center text-sm text-muted-foreground">
                                                <Calendar className="w-3.5 h-3.5 mr-2 opacity-50" />
                                                {new Date(doc.created_at).toLocaleDateString()}
                                            </div>

                                            {/* Column 4: Actions */}
                                            <div className="text-right opacity-0 group-hover:opacity-100 transition-opacity">
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
                                ))}
                            </AnimatePresence>
                        </ul>
                    </div>
                )}
            </div>

            {isUploadOpen && (
                <UploadWizard onClose={() => setIsUploadOpen(false)} onComplete={() => {
                    setIsUploadOpen(false)
                    refetch()
                    queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] })
                }} />
            )}

            {/* Delete Confirmation Dialog */}
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
        </div>
    )
}
