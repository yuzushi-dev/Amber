import { useState } from 'react'
import { X, Upload, Loader2, CheckCircle2 } from 'lucide-react'
import { apiClient } from '@/lib/api-client'

interface UploadWizardProps {
    onClose: () => void
    onComplete: () => void
}

export default function UploadWizard({ onClose, onComplete }: UploadWizardProps) {
    const [file, setFile] = useState<File | null>(null)
    const [status, setStatus] = useState<'idle' | 'uploading' | 'processing' | 'done'>('idle')
    const [progress, setProgress] = useState(0)
    const [uploadStats, setUploadStats] = useState({ loaded: 0, total: 0 })

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            setFile(e.target.files[0])
        }
    }

    const handleUpload = async () => {
        if (!file) return

        setStatus('uploading')
        const formData = new FormData()
        formData.append('file', file)

        try {
            await apiClient.post('/documents', formData, {
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
            setStatus('processing')
            // Simulated processing time for UX demonstration
            setTimeout(() => {
                setStatus('done')
                setTimeout(onComplete, 1500)
            }, 2000)
        } catch (err) {
            console.error('Upload failed', err)
            setStatus('idle')
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
                            {status === 'done' ? (
                                <CheckCircle2 className="w-16 h-16 mx-auto text-green-500 animate-in zoom-in duration-300" />
                            ) : (
                                <Loader2 className="w-16 h-16 mx-auto text-primary animate-spin" />
                            )}
                            <h4 className="text-xl font-bold capitalize">{status}...</h4>
                            <p className="text-sm text-muted-foreground">
                                {status === 'uploading' && 'Transferring file to secure vault.'}
                                {status === 'processing' && 'Chunking, vectorizing, and building knowledge graph.'}
                                {status === 'done' && 'Knowledge successfully integrated!'}
                            </p>
                        </div>
                    )}

                    {status === 'uploading' && (
                        <div className="w-full max-w-xs mx-auto mt-4">
                            <div className="h-2 bg-muted rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-primary transition-all duration-300 ease-out"
                                    style={{ width: `${progress}%` }}
                                />
                            </div>
                            <div className="flex justify-between text-xs text-muted-foreground mt-2">
                                <span>{progress}%</span>
                                <span>
                                    {(uploadStats.loaded / (1024 * 1024)).toFixed(2)} MB / {(uploadStats.total / (1024 * 1024)).toFixed(2)} MB
                                </span>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
