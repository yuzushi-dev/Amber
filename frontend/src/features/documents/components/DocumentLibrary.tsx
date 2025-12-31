import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'
import { FileText, Plus, Search, RefreshCw, Trash2, BookOpen } from 'lucide-react'
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

export default function DocumentLibrary() {
    const [isUploadOpen, setIsUploadOpen] = useState(false)
    const [isSampleOpen, setIsSampleOpen] = useState(false)

    const { data: documents, isLoading, refetch } = useQuery({
        queryKey: ['documents'],
        queryFn: async () => {
            const response = await apiClient.get<Document[]>('/documents')
            return response.data
        }
    })

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
                    <button
                        onClick={() => refetch()}
                        className="p-2 hover:bg-muted rounded-md transition-colors"
                        aria-label="Refresh document list"
                    >
                        <RefreshCw className="w-4 h-4" aria-hidden="true" />
                    </button>
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
        </div>
    )
}

