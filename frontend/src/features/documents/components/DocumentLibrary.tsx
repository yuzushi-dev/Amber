import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'
import { FileText, Plus, Search, RefreshCw, Trash2, BookOpen, AlertTriangle } from 'lucide-react'
import { useState } from 'react'
import UploadWizard from './UploadWizard'
import SampleDataModal from './SampleDataModal'
import EmptyState from '@/components/ui/EmptyState'

interface Document {
    id: string
    filename: string
    title: string  // Alias for filename from backend
    status: string
    created_at: string
}

type ConfirmAction =
    | { type: 'delete-single'; documentId: string; documentTitle: string }
    | { type: 'delete-all' }
    | null

export default function DocumentLibrary() {
    const [isUploadOpen, setIsUploadOpen] = useState(false)
    const [isSampleOpen, setIsSampleOpen] = useState(false)
    const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null)

    const queryClient = useQueryClient()

    const { data: documents, isLoading, refetch } = useQuery({
        queryKey: ['documents'],
        queryFn: async () => {
            const response = await apiClient.get<Document[]>('/documents')
            return response.data
        }
    })

    // Delete single document mutation
    const deleteDocumentMutation = useMutation({
        mutationFn: async (documentId: string) => {
            await apiClient.delete(`/documents/${documentId}`)
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['documents'] })
            setConfirmAction(null)
        },
        onError: (error) => {
            console.error('Failed to delete document:', error)
            setConfirmAction(null)
        }
    })

    // Delete all documents mutation
    const deleteAllDocumentsMutation = useMutation({
        mutationFn: async () => {
            if (!documents) return
            // Delete all documents sequentially
            for (const doc of documents) {
                await apiClient.delete(`/documents/${doc.id}`)
            }
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['documents'] })
            setConfirmAction(null)
        },
        onError: (error) => {
            console.error('Failed to delete all documents:', error)
            setConfirmAction(null)
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

    const handleSampleComplete = () => {
        setIsSampleOpen(false)
        refetch()
    }

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
                    <button
                        onClick={() => setIsSampleOpen(true)}
                        className="flex items-center gap-2 px-4 py-2 border border-primary text-primary rounded-md hover:bg-primary/10 transition-colors"
                        aria-label="Load sample data"
                    >
                        <BookOpen className="w-4 h-4" aria-hidden="true" />
                        <span>Try Sample Data</span>
                    </button>
                </>
            }
        />
    )

    return (
        <div className="p-8 max-w-6xl mx-auto space-y-8">
            <header className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold">Document Library</h1>
                    <p className="text-muted-foreground">Manage your ingested knowledge sources.</p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setIsSampleOpen(true)}
                        className="flex items-center space-x-2 border border-border px-4 py-2 rounded-md hover:bg-muted transition-colors"
                        aria-label="Load sample data"
                    >
                        <BookOpen className="w-4 h-4" aria-hidden="true" />
                        <span>Sample Data</span>
                    </button>
                    <button
                        onClick={() => setIsUploadOpen(true)}
                        className="flex items-center space-x-2 bg-primary text-primary-foreground px-4 py-2 rounded-md hover:opacity-90 transition-opacity"
                        aria-label="Upload new document"
                    >
                        <Plus className="w-4 h-4" aria-hidden="true" />
                        <span>Upload Knowledge</span>
                    </button>
                </div>
            </header>

            <div className="bg-card border rounded-lg overflow-hidden">
                <div className="p-4 border-b flex justify-between items-center bg-muted/20">
                    <div className="relative w-64">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
                        <input
                            type="text"
                            placeholder="Filter documents..."
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
                        <button
                            onClick={() => refetch()}
                            className="p-2 hover:bg-muted rounded-md transition-colors"
                            aria-label="Refresh document list"
                        >
                            <RefreshCw className="w-4 h-4" aria-hidden="true" />
                        </button>
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
                                    <th className="p-4 font-semibold" scope="col">Ingested At</th>
                                    <th className="p-4 font-semibold text-right" scope="col">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {documents?.map((doc) => (
                                    <tr key={doc.id} className="border-b hover:bg-muted/5 transition-colors">
                                        <td className="p-4">
                                            <div className="flex items-center space-x-3">
                                                <FileText className="w-4 h-4 text-primary" aria-hidden="true" />
                                                <span className="font-medium">{doc.title}</span>
                                            </div>
                                        </td>
                                        <td className="p-4">
                                            <span
                                                className="px-2 py-1 rounded-full text-[10px] bg-green-100 text-green-700 font-bold uppercase tracking-wider"
                                                role="status"
                                            >
                                                {doc.status}
                                            </span>
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

            <SampleDataModal
                isOpen={isSampleOpen}
                onClose={() => setIsSampleOpen(false)}
                onComplete={handleSampleComplete}
            />

            {/* Delete Confirmation Modal */}
            {confirmAction && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" role="dialog" aria-modal="true">
                    <div className="bg-card border rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-2 bg-destructive/10 rounded-full">
                                <AlertTriangle className="w-6 h-6 text-destructive" aria-hidden="true" />
                            </div>
                            <h2 className="text-lg font-semibold">
                                {confirmAction.type === 'delete-single'
                                    ? 'Delete Document?'
                                    : 'Delete All Documents?'
                                }
                            </h2>
                        </div>
                        <p className="text-muted-foreground mb-6">
                            {confirmAction.type === 'delete-single'
                                ? `Are you sure you want to delete "${confirmAction.documentTitle}"? This action cannot be undone.`
                                : `Are you sure you want to delete all ${documents?.length || 0} documents? This action cannot be undone.`
                            }
                        </p>
                        <div className="flex justify-end gap-3">
                            <button
                                onClick={() => setConfirmAction(null)}
                                disabled={isDeleting}
                                className="px-4 py-2 border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleConfirmDelete}
                                disabled={isDeleting}
                                className="px-4 py-2 bg-destructive text-destructive-foreground rounded-md hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-2"
                            >
                                {isDeleting ? (
                                    <>
                                        <RefreshCw className="w-4 h-4 animate-spin" aria-hidden="true" />
                                        Deleting...
                                    </>
                                ) : (
                                    <>Delete</>
                                )}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

