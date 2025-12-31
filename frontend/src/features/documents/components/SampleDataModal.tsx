import { useState } from 'react'
import { X, Sparkles, BookOpen, Cpu, Loader2 } from 'lucide-react'
import { apiClient } from '@/lib/api-client'

interface SampleDataModalProps {
    isOpen: boolean
    onClose: () => void
    onComplete: () => void
}

interface Dataset {
    id: string
    name: string
    description: string
    icon: React.ReactNode
}

const DATASETS: Dataset[] = [
    {
        id: 'solar_system',
        name: 'Solar System',
        description: 'Educational content about planets, the Sun, and space exploration',
        icon: <Sparkles className="w-6 h-6" />
    },
    {
        id: 'technology',
        name: 'Technology Concepts',
        description: 'Technical documentation about machine learning and neural networks',
        icon: <Cpu className="w-6 h-6" />
    }
]

/**
 * Modal for selecting and loading sample data.
 * Provides one-click onboarding with pre-built datasets.
 */
export default function SampleDataModal({ isOpen, onClose, onComplete }: SampleDataModalProps) {
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [selectedDataset, setSelectedDataset] = useState<string | null>(null)

    if (!isOpen) return null

    const handleLoadDataset = async (datasetId: string) => {
        setLoading(true)
        setError(null)
        setSelectedDataset(datasetId)

        try {
            await apiClient.post('/admin/seed-sample-data', {
                dataset: datasetId
            })
            onComplete()
        } catch (err) {
            setError('Failed to load sample data. Please try again.')
            console.error('Sample data error:', err)
        } finally {
            setLoading(false)
            setSelectedDataset(null)
        }
    }

    return (
        <div
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
            role="dialog"
            aria-modal="true"
            aria-labelledby="sample-data-title"
        >
            <div
                className="bg-background rounded-xl shadow-2xl max-w-lg w-full mx-4 overflow-hidden"
                role="document"
            >
                {/* Header */}
                <div className="flex items-center justify-between p-6 border-b">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-primary/10 rounded-lg">
                            <BookOpen className="w-5 h-5 text-primary" aria-hidden="true" />
                        </div>
                        <h2 id="sample-data-title" className="text-xl font-semibold">
                            Try Sample Data
                        </h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-muted rounded-lg transition-colors"
                        aria-label="Close modal"
                        disabled={loading}
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Content */}
                <div className="p-6 space-y-4">
                    <p className="text-muted-foreground">
                        Get started quickly with pre-built knowledge bases. Select a dataset to load sample documents.
                    </p>

                    {error && (
                        <div
                            className="p-3 bg-destructive/10 text-destructive rounded-lg text-sm"
                            role="alert"
                        >
                            {error}
                        </div>
                    )}

                    <div className="space-y-3">
                        {DATASETS.map((dataset) => (
                            <button
                                key={dataset.id}
                                onClick={() => handleLoadDataset(dataset.id)}
                                disabled={loading}
                                className={`w-full p-4 border rounded-lg text-left transition-all hover:border-primary hover:bg-muted/30 disabled:opacity-50 disabled:cursor-not-allowed ${selectedDataset === dataset.id ? 'border-primary bg-muted/30' : ''
                                    }`}
                                aria-busy={loading && selectedDataset === dataset.id}
                            >
                                <div className="flex items-start gap-4">
                                    <div className="p-2 bg-muted rounded-lg flex-shrink-0" aria-hidden="true">
                                        {loading && selectedDataset === dataset.id ? (
                                            <Loader2 className="w-6 h-6 animate-spin" />
                                        ) : (
                                            dataset.icon
                                        )}
                                    </div>
                                    <div>
                                        <h3 className="font-medium">{dataset.name}</h3>
                                        <p className="text-sm text-muted-foreground mt-1">
                                            {dataset.description}
                                        </p>
                                    </div>
                                </div>
                            </button>
                        ))}
                    </div>
                </div>

                {/* Footer */}
                <div className="p-6 border-t bg-muted/20">
                    <p className="text-xs text-muted-foreground text-center">
                        Sample data uses Wikipedia public domain content for demonstration purposes.
                    </p>
                </div>
            </div>
        </div>
    )
}
