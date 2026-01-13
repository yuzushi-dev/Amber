import { useState, useEffect, useRef } from 'react'
import { X, Upload, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { AnimatedProgress } from '@/components/ui/animated-progress'
import { Button } from '@/components/ui/button'
import { SSEManager } from '@/lib/sse'

interface UploadWizardProps {
    onClose: () => void
    onComplete: () => void
}

type ProcessingStatus = 'idle' | 'uploading' | 'extracting' | 'classifying' | 'chunking' | 'embedding' | 'graph_sync' | 'ready' | 'completed' | 'failed'

interface ProcessingStatusResponse {
    status: string
    error_message?: string
}

export default function UploadWizard({ onClose, onComplete }: UploadWizardProps) {
    const [file, setFile] = useState<File | null>(null)
    const [status, setStatus] = useState<ProcessingStatus>('idle')
    const [progress, setProgress] = useState(0)
    const [uploadStats, setUploadStats] = useState({ loaded: 0, total: 0 })
    const [, setStatusMessage] = useState('')
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const [sseManager, setSseManager] = useState<SSEManager | null>(null)
    const pollingRef = useRef<NodeJS.Timeout | null>(null)

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (sseManager) {
                sseManager.disconnect()
            }
            if (pollingRef.current) {
                clearInterval(pollingRef.current)
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

        } catch (err: unknown) {
            const error = err as { message?: string; response?: { data?: { detail?: string } } }
            const message = error.message || 'Upload failed'
            setStatus('failed')
            setStatusMessage(`Upload failed: ${message}`)
            setErrorMessage(error.response?.data?.detail || 'Upload failed. Please try again.')
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

        // Use relative path for SSE so it goes through the Vite proxy (or Nginx in prod)
        // This ensures it works on remote servers (e.g., cph-01) where localhost is incorrect.
        // We use /api/v1 prefix which the Vite proxy rewrites to the VITE_API_TARGET
        const baseUrl = eventsUrl || `/api/v1/documents/${documentId}/events`

        // Append API key preserving existing query params if any
        const monitorUrl = baseUrl.includes('?')
            ? `${baseUrl}&api_key=${encodeURIComponent(apiKey)}`
            : `${baseUrl}?api_key=${encodeURIComponent(apiKey)}`

        console.log('Connecting to SSE:', monitorUrl)

        // Status precedence for aggregation (SSE + Polling)
        const STATUS_ORDER = ['idle', 'uploading', 'ingested', 'extracting', 'classifying', 'chunking', 'embedding', 'graph_sync', 'ready', 'completed', 'failed']

        const updateStatus = (newStatus: string, error?: string) => {
            const s = newStatus.toLowerCase() as ProcessingStatus

            setStatus(prev => {
                const prevIndex = STATUS_ORDER.indexOf(prev)
                const newIndex = STATUS_ORDER.indexOf(s)

                // Always jump to failed or ready. For progress, only move forward.
                if (s === 'failed' || s === 'ready' || s === 'completed' || newIndex > prevIndex) {
                    return s
                }
                return prev
            })

            if (s === 'ready' || s === 'completed') {
                setStatusMessage('Knowledge successfully integrated!')
                cleanup()
                setTimeout(onComplete, 1500)
            } else if (s === 'failed') {
                setErrorMessage(error || 'Processing failed.')
                cleanup()
            }
        }

        const cleanup = () => {
            if (pollingRef.current) clearInterval(pollingRef.current)
            manager.disconnect()
        }

        // SSE Setup
        let retryCount = 0
        const maxRetries = 3

        const createManager = () => {
            const manager = new SSEManager(
                monitorUrl,
                (event) => {
                    try {
                        const data = JSON.parse(event.data)
                        // console.log('SSE Event:', data)
                        if (data.status) {
                            updateStatus(data.status, data.error)
                        }
                    } catch (e) {
                        console.error('Failed to parse SSE event:', e)
                    }
                },
                (error) => {
                    console.warn('SSE warning:', error)
                    retryCount++
                    if (retryCount < maxRetries) {
                        manager.disconnect()
                        setTimeout(createManager, 1000 * retryCount)
                    } else {
                        // SSE failed, rely on polling
                        console.warn('SSE connection lost, switching to polling only.')
                    }
                }
            )
            manager.connect()
            setSseManager(manager)
            return manager
        }

        const manager = createManager()

        // Polling Fallback (every 3s)
        pollingRef.current = setInterval(async () => {
            try {
                // apiClient base is /v1, so request /documents/{id}
                const res = await apiClient.get<ProcessingStatusResponse>(`/documents/${documentId}`)
                if (res.data && res.data.status) {
                    // console.log('Poll Status:', res.data.status)
                    updateStatus(res.data.status, res.data.error_message)
                }
            } catch (err) {
                console.warn('Poll failed', err)
            }
        }, 3000)
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
                    <Button variant="ghost" size="icon" onClick={onClose} className="rounded-full hover:bg-muted">
                        <X className="w-5 h-5" />
                    </Button>
                </header>

                <div className="p-12 text-center space-y-6">
                    {status === 'idle' ? (
                        <>
                            <div
                                className="border-2 border-dashed rounded-xl p-12 transition-colors hover:bg-accent/10 cursor-pointer"
                                onClick={() => document.getElementById('file-upload')?.click()}
                            >
                                <Upload className="w-12 h-12 mx-auto text-primary opacity-50 mb-4" />
                                <p className="text-sm font-medium">Click or drag to upload a file</p>
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
                                    <Button
                                        onClick={handleUpload}
                                        className="bg-primary text-primary-foreground hover:opacity-90"
                                    >
                                        Start Ingestion
                                    </Button>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="space-y-4 py-8">
                            {status === 'ready' ? (
                                <CheckCircle2 className="w-16 h-16 mx-auto text-success animate-in zoom-in duration-300" />
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
