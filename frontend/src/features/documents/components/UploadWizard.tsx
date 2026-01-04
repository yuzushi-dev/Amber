import { useState, useEffect } from 'react'
import { X, Upload, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { AnimatedProgress } from '@/components/ui/animated-progress'
import { SSEManager } from '@/lib/sse'

interface UploadWizardProps {
    onClose: () => void
    onComplete: () => void
}

type ProcessingStatus = 'idle' | 'uploading' | 'extracting' | 'classifying' | 'chunking' | 'embedding' | 'graph_sync' | 'ready' | 'failed'

export default function UploadWizard({ onClose, onComplete }: UploadWizardProps) {
    const [file, setFile] = useState<File | null>(null)
    const [status, setStatus] = useState<ProcessingStatus>('idle')
    const [progress, setProgress] = useState(0)
    const [uploadStats, setUploadStats] = useState({ loaded: 0, total: 0 })
    const [_statusMessage, setStatusMessage] = useState('')
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const [sseManager, setSseManager] = useState<SSEManager | null>(null)

    // Cleanup SSE on unmount
    useEffect(() => {
        return () => {
            if (sseManager) {
                sseManager.disconnect()
            }
        }
    }, [sseManager])

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            setFile(e.target.files[0])
            setErrorMessage(null)
        }
    }

    const handleUpload = async () => {
        if (!file) return

        setStatus('uploading')
        setErrorMessage(null)

        const formData = new FormData()
        formData.append('file', file)

        try {
            const response = await apiClient.post<{ document_id: string, events_url: string }>('/documents', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
                onUploadProgress: (progressEvent) => {
                    const { loaded, total } = progressEvent
                    if (total) {
                        const percent = Math.round((loaded * 100) / total)
                        setProgress(percent)
                        setUploadStats({ loaded, total })
                    }
                }
            })

            const { document_id, events_url } = response.data

            // Start listening for processing events
            startMonitoring(document_id, events_url)

        } catch (err: any) {
            console.error('Upload failed', err)
            setStatus('idle')
            setErrorMessage(err.response?.data?.detail || 'Upload failed. Please try again.')
        }
    }

    const startMonitoring = (documentId: string, eventsUrl?: string) => {
        // Initial state after upload
        setStatus('extracting')
        setStatusMessage('Extracting content...')

        // Get API key for SSE auth
        const apiKey = localStorage.getItem('api_key')

        if (!apiKey) {
            console.error('SSE: No API key found in localStorage')
            setStatus('failed')
            setErrorMessage('Authentication required. Please refresh and log in again.')
            return
        }

        // Construct absolute URL for EventSource (doesn't use Vite proxy)
        // In development, use the backend URL directly; in production, use relative URL
        const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000/v1'
        const baseUrl = eventsUrl || `${apiBaseUrl}/documents/${documentId}/events`

        // Append API key preserving existing query params if any
        const monitorUrl = baseUrl.includes('?')
            ? `${baseUrl}&api_key=${encodeURIComponent(apiKey)}`
            : `${baseUrl}?api_key=${encodeURIComponent(apiKey)}`

        console.log('Connecting to SSE:', monitorUrl)
        console.log('SSE Debug: API key present:', apiKey ? `${apiKey.substring(0, 10)}...` : 'NONE')

        let retryCount = 0
        const maxRetries = 3

        const createManager = () => {
            const manager = new SSEManager(
                monitorUrl,
                (event) => {
                    try {
                        const data = JSON.parse(event.data)
                        console.log('SSE Event:', data)

                        if (data.status) {
                            const s = data.status.toLowerCase()
                            if (['extracting', 'classifying', 'chunking', 'embedding', 'graph_sync', 'ready', 'failed'].includes(s)) {
                                setStatus(s as ProcessingStatus)
                            }

                            if (s === 'ready' || s === 'completed') {
                                setStatus('ready')
                                setStatusMessage('Knowledge successfully integrated!')
                                manager.disconnect()
                                setTimeout(onComplete, 1500)
                            } else if (s === 'failed') {
                                setStatus('failed')
                                setErrorMessage(data.error || 'Processing failed.')
                                manager.disconnect()
                            }
                        }
                    } catch (e) {
                        console.error('Failed to parse SSE event:', e)
                    }
                },
                (error) => {
                    console.error('SSE Error:', error)
                    retryCount++
                    if (retryCount < maxRetries) {
                        console.log(`SSE retry ${retryCount}/${maxRetries}...`)
                        manager.disconnect()
                        setTimeout(() => {
                            createManager()
                        }, 1000 * retryCount)
                    } else {
                        console.error('SSE: Max retries exceeded')
                        setStatus('failed')
                        setErrorMessage('Lost connection to server. Please refresh and try again.')
                    }
                }
            )

            manager.connect()
            setSseManager(manager)
        }

        createManager()
    }

    const getStatusLabel = (s: ProcessingStatus) => {
        switch (s) {
            case 'uploading': return 'Uploading to secure vault...'
            case 'extracting': return 'Extracting text and metadata...'
            case 'classifying': return 'Classifying document domain...'
            case 'chunking': return 'Splitting into semantic chunks...'
            case 'embedding': return 'Generating vector embeddings...'
            case 'graph_sync': return 'Building knowledge graph...'
            case 'ready': return 'Knowledge successfully integrated!'
            case 'failed': return 'Processing failed.'
            default: return 'Processing...'
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
            <div className="bg-card border shadow-2xl rounded-xl w-full max-w-lg overflow-hidden">
                <header className="p-4 border-b flex justify-between items-center bg-muted/30">
                    <h3 className="font-semibold text-lg">Knowledge Ingestion</h3>
                    <button onClick={onClose} className="p-2 hover:bg-muted rounded-full">
                        <X className="w-5 h-5" />
                    </button>
                </header>

                <div className="p-12 text-center space-y-6">
                    {status === 'idle' ? (
                        <>
                            <div
                                className="border-2 border-dashed rounded-xl p-12 transition-colors hover:bg-accent/10 cursor-pointer"
                                onClick={() => document.getElementById('file-upload')?.click()}
                            >
                                <Upload className="w-12 h-12 mx-auto text-primary opacity-50 mb-4" />
                                <p className="text-sm font-medium">Click or drag to upload knowledge</p>
                                <p className="text-xs text-muted-foreground mt-2">Supports PDF, MD, HTML (max 50MB)</p>
                                <input
                                    id="file-upload"
                                    type="file"
                                    className="hidden"
                                    onChange={handleFileChange}
                                />
                            </div>
                            {errorMessage && (
                                <div className="text-destructive text-sm flex items-center justify-center gap-2">
                                    <AlertCircle className="w-4 h-4" />
                                    {errorMessage}
                                </div>
                            )}
                            {file && (
                                <div className="bg-muted p-4 rounded-lg flex items-center justify-between">
                                    <span className="text-sm font-medium truncate max-w-xs">{file.name}</span>
                                    <button
                                        onClick={handleUpload}
                                        className="bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm hover:opacity-90"
                                    >
                                        Start Ingestion
                                    </button>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="space-y-4 py-8">
                            {status === 'ready' ? (
                                <CheckCircle2 className="w-16 h-16 mx-auto text-green-500 animate-in zoom-in duration-300" />
                            ) : status === 'failed' ? (
                                <div className="text-destructive">
                                    <AlertCircle className="w-16 h-16 mx-auto mb-4" />
                                    <p className="font-medium">{errorMessage || 'Processing failed'}</p>
                                </div>
                            ) : (
                                <Loader2 className="w-16 h-16 mx-auto text-primary animate-spin" />
                            )}

                            {status !== 'failed' && (
                                <>
                                    <h4 className="text-xl font-bold capitalize">{status}...</h4>
                                    <p className="text-sm text-muted-foreground">
                                        {getStatusLabel(status)}
                                    </p>
                                </>
                            )}
                        </div>
                    )}

                    {status === 'uploading' && (
                        <div className="w-full max-w-xs mx-auto mt-4">
                            <AnimatedProgress
                                value={progress}
                                stages={[
                                    { label: 'Starting upload...', threshold: 0 },
                                    { label: 'Uploading...', threshold: 10 },
                                    { label: 'Almost done...', threshold: 90 },
                                ]}
                                size="md"
                            />
                            <div className="text-center text-xs text-muted-foreground mt-2">
                                {(uploadStats.loaded / (1024 * 1024)).toFixed(2)} MB / {(uploadStats.total / (1024 * 1024)).toFixed(2)} MB
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
