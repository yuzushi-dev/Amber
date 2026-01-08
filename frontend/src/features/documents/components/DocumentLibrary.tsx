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
    Share2
} from 'lucide-react'
import { useState } from 'react'
import UploadWizard from './UploadWizard'
import EmptyState from '@/components/ui/EmptyState'
import { ConfirmDialog } from '@/components/ui/dialog'
import { useFuzzySearch } from '@/hooks/useFuzzySearch'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import LiveStatusBadge from './LiveStatusBadge'

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
                    <button
                        onClick={() => setIsUploadOpen(true)}
                        className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-opacity"
                        aria-label="Upload a document"
                    >
                        <Plus className="w-4 h-4" aria-hidden="true" />
                        <span>Upload Document</span>
                    </button>
                </>
            }
        />
    )

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <header className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold">Document Library</h1>
                    <p className="text-muted-foreground">Manage your ingested knowledge sources.</p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setIsUploadOpen(true)}
                        className="flex items-center space-x-2 bg-primary text-primary-foreground px-4 py-2 rounded-md hover:opacity-90 transition-opacity"
                        aria-label="Upload new document"
                    >
                        <Plus className="w-4 h-4" aria-hidden="true" />
                        <span>Upload Files</span>
                    </button>
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

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {[
                    {
                        label: 'Documents',
                        value: stats?.database.documents_total ?? 0,
                        icon: FileText,
                        color: 'text-blue-500',
                        bg: 'bg-blue-500/10'
                    },
                    {
                        label: 'Chunks',
                        value: stats?.database.chunks_total ?? 0,
                        icon: Box,
                        color: 'text-purple-500',
                        bg: 'bg-purple-500/10'
                    },
                    {
                        label: 'Entities',
                        value: stats?.database.entities_total ?? 0,
                        icon: Users,
                        color: 'text-green-500',
                        bg: 'bg-green-500/10'
                    },
                    {
                        label: 'Relationships',
                        value: stats?.database.relationships_total ?? 0,
                        icon: Share2,
                        color: 'text-orange-500',
                        bg: 'bg-orange-500/10'
                    }
                ].map((card) => (
                    <div
                        key={card.label}
                        className="p-4 rounded-xl border bg-card text-card-foreground shadow-sm flex items-center gap-3 transition-all hover:shadow-md"
                    >
                        <div className={`p-2 rounded-full ${card.bg} ${card.color}`}>
                            <card.icon className="w-5 h-5" />
                        </div>
                        <div>
                            <p className="text-xs font-medium text-muted-foreground">{card.label}</p>
                            <h2 className="text-2xl font-bold">{card.value.toLocaleString()}</h2>
                        </div>
                    </div>
                ))}
            </div>

            <div className="bg-card border rounded-lg overflow-hidden">
                <div className="p-4 border-b flex justify-between items-center bg-muted/20">
                    <div className="relative w-64">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
                        <input
                            type="text"
                            placeholder="Filter documents..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full bg-background border rounded-md pl-10 pr-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1"
                            aria-label="Filter documents"
                        />
                    </div>
                    <div className="flex items-center gap-2">
                        {documents && documents.length > 0 && (
                            <button
                                onClick={() => setConfirmAction({ type: 'delete-all' })}
                                className="flex items-center gap-2 px-3 py-2 text-sm text-destructive border border-destructive/30 rounded-md hover:bg-destructive/10 transition-colors"
                                aria-label="Delete all documents"
                            >
                                <Trash2 className="w-4 h-4" aria-hidden="true" />
                                <span>Delete All</span>
                            </button>
                        )}
                    </div>
                </div>

                {isLoading ? (
                    <div className="p-8 text-center text-muted-foreground" role="status" aria-live="polite">
                        <div className="animate-pulse">Loading documents...</div>
                    </div>
                ) : documents?.length === 0 ? (
                    renderEmptyState()
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm" role="table" aria-label="Documents">
                            <thead>
                                <tr className="border-b bg-muted/10 text-left">
                                    <th className="p-4 font-semibold" scope="col">Document</th>
                                    <th className="p-4 font-semibold" scope="col">Status</th>
                                    <th className="p-4 font-semibold" scope="col">Uploaded At</th>
                                    <th className="p-4 font-semibold text-right" scope="col">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredDocuments.map((doc) => (
                                    <tr key={doc.id} className="border-b hover:bg-muted/5 transition-colors">
                                        <td className="p-4">
                                            <div className="flex items-center space-x-3">
                                                <FileText className="w-4 h-4 text-primary" aria-hidden="true" />
                                                <Link
                                                    to="/admin/data/documents/$documentId"
                                                    params={{ documentId: doc.id }}
                                                    className="font-medium hover:underline text-foreground"
                                                >
                                                    {doc.title}
                                                </Link>
                                            </div>
                                        </td>
                                        <td className="p-4">
                                            <LiveStatusBadge
                                                documentId={doc.id}
                                                initialStatus={doc.status}
                                                onComplete={() => refetch()}
                                            />
                                        </td>
                                        <td className="p-4 text-muted-foreground">
                                            {new Date(doc.created_at).toLocaleDateString()}
                                        </td>
                                        <td className="p-4 text-right">
                                            <button
                                                onClick={() => setConfirmAction({ type: 'delete-single', documentId: doc.id, documentTitle: doc.title })}
                                                className="p-2 text-destructive hover:bg-destructive/10 rounded-md transition-colors"
                                                aria-label={`Delete ${doc.title}`}
                                            >
                                                <Trash2 className="w-4 h-4" aria-hidden="true" />
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {isUploadOpen && (
                <UploadWizard onClose={() => setIsUploadOpen(false)} onComplete={() => {
                    setIsUploadOpen(false)
                    refetch()
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
