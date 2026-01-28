
import { useRef, useState } from 'react'
import { X, Upload, CheckCircle2, AlertCircle, Clock, Trash2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { calculateGlobalProgress, useUploadStore, UploadItem } from '../stores/useUploadStore'
import { cn } from '@/lib/utils'

export default function UploadWizard() {
    // We don't use props anymore, we use the store
    const { items, setOpen, enqueueFiles, retry, remove, dismiss } = useUploadStore()
    const [isDragging, setIsDragging] = useState(false)
    const fileInputRef = useRef<HTMLInputElement>(null)

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
            enqueueFiles(Array.from(e.target.files))
            // Reset input
            if (fileInputRef.current) fileInputRef.current.value = ''
        }
    }

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault()
        setIsDragging(false)
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            enqueueFiles(Array.from(e.dataTransfer.files))
        }
    }

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault()
        setIsDragging(true)
    }

    const handleDragLeave = (e: React.DragEvent) => {
        e.preventDefault()
        setIsDragging(false)
    }

    // Calculate Global Progress for Header
    const globalProgress = calculateGlobalProgress(items)

    // Status counts
    const queuedCount = items.filter(i => i.status === 'queued').length
    const activeCount = items.filter(i => i.status === 'uploading' || i.status === 'processing').length
    const completedCount = items.filter(i => i.status === 'ready' || i.status === 'completed').length
    const failedCount = items.filter(i => ['failed', 'interrupted', 'missingFile'].includes(i.status)).length

    const hasItems = items.length > 0

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
            <div
                className="bg-card border shadow-2xl rounded-xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]"
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
            >
                {/* Header */}
                <header className="p-4 border-b flex justify-between items-center bg-muted/30 shrink-0">
                    <div>
                        <h3 className="font-semibold text-lg">Knowledge Ingestion</h3>
                        <p className="text-xs text-muted-foreground">
                            {activeCount > 0 ? `Processing ${activeCount} files...` :
                                queuedCount > 0 ? `Queued ${queuedCount} files...` :
                                    completedCount > 0 ? 'Uploads complete' : 'Upload documents'}
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        {completedCount > 0 && failedCount === 0 && activeCount === 0 && queuedCount === 0 && (
                            <Button variant="outline" size="sm" onClick={() => items.forEach(i => dismiss(i.id))}>
                                Clear All
                            </Button>
                        )}
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setOpen(false)}
                            className="rounded-full hover:bg-muted"
                        >
                            <X className="w-5 h-5" />
                        </Button>
                    </div>
                </header>

                {/* Progress Bar (Global) */}
                {hasItems && (
                    <div className="h-1 bg-secondary w-full">
                        <div
                            className="h-full bg-primary transition-all duration-500 ease-out"
                            style={{ width: `${globalProgress}%` }}
                        />
                    </div>
                )}

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-0 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                    {!hasItems ? (
                        <div className={cn(
                            "flex flex-col items-center justify-center h-full p-12 text-center transition-colors min-h-[300px]",
                            isDragging ? "bg-primary/5" : ""
                        )}>
                            <div
                                className="border-2 border-dashed rounded-xl p-12 transition-all hover:bg-accent/10 cursor-pointer w-full"
                                onClick={() => fileInputRef.current?.click()}
                            >
                                <Upload className="w-12 h-12 mx-auto text-primary opacity-50 mb-4" />
                                <p className="text-sm font-medium">Click or drag files to upload</p>
                                <p className="text-xs text-muted-foreground mt-2">Supports multiple files (max 50MB each)</p>
                            </div>
                        </div>
                    ) : (
                        <div className="divide-y">
                            {items.map(item => (
                                <UploadItemRow
                                    key={item.id}
                                    item={item}
                                    onRetry={() => retry(item.id)}
                                    onRemove={() => remove(item.id)}
                                />
                            ))}

                            {/* Mini Dropzone at bottom */}
                            <div
                                className={cn(
                                    "p-8 text-center border-t border-dashed transition-colors hover:bg-accent/5 cursor-pointer",
                                    isDragging ? "bg-primary/10" : ""
                                )}
                                onClick={() => fileInputRef.current?.click()}
                            >
                                <p className="text-xs text-muted-foreground font-medium">+ Add more files</p>
                            </div>
                        </div>
                    )}
                </div>

                <input
                    ref={fileInputRef}
                    type="file"
                    className="hidden"
                    multiple
                    onChange={handleFileChange}
                />
            </div>
        </div>
    )
}

function UploadItemRow({ item, onRetry, onRemove }: { item: UploadItem, onRetry: () => void, onRemove: () => void }) {

    const getStatusIcon = () => {
        switch (item.status) {
            case 'queued': return <Clock className="w-5 h-5 text-muted-foreground" />
            case 'uploading': return <Upload className="w-5 h-5 text-blue-500 animate-bounce" />
            case 'processing': return <RefreshCw className="w-5 h-5 text-amber-500 animate-spin" />
            case 'ready':
            case 'completed': return <CheckCircle2 className="w-5 h-5 text-green-500" />
            case 'failed':
            case 'interrupted':
            case 'missingFile': return <AlertCircle className="w-5 h-5 text-destructive" />
            default: return <Clock className="w-5 h-5 text-muted-foreground" />
        }
    }

    const getStatusLabel = () => {
        if (item.status === 'uploading') return `Uploading ${item.uploadProgress}%`
        if (item.status === 'processing') {
            if (item.currentStage) {
                // Convert snake_case to Title Case (e.g. graph_sync -> Graph Sync)
                const stageName = item.currentStage
                    .split('_')
                    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                    .join(' ')
                return `${stageName} ${item.stageProgress}%`
            }
            return `Processing ${item.stageProgress}%`
        }
        if (item.status === 'interrupted') return 'Interrupted'
        if (item.status === 'missingFile') return 'File Lost'
        return item.status.charAt(0).toUpperCase() + item.status.slice(1)
    }

    const progressValue = item.status === 'uploading' ? item.uploadProgress
        : item.status === 'processing' ? item.stageProgress
            : (item.status === 'ready' || item.status === 'completed') ? 100 : 0

    return (
        <div className="p-4 flex items-center gap-4 hover:bg-muted/10 group transition-colors">
            <div className="shrink-0">
                {getStatusIcon()}
            </div>

            <div className="flex-1 min-w-0 space-y-1">
                <div className="flex justify-between items-start">
                    <span className="text-sm font-medium truncate" title={item.fileMeta.name}>
                        {item.fileMeta.name}
                    </span>
                    <span className={cn(
                        "text-xs capitalize ml-2",
                        item.status === 'failed' ? "text-destructive" : "text-muted-foreground"
                    )}>
                        {getStatusLabel()}
                    </span>
                </div>

                {/* Progress Bar */}
                {(item.status === 'uploading' || item.status === 'processing') && (
                    <div className="h-1.5 w-full bg-secondary rounded-full overflow-hidden">
                        <div
                            className={cn(
                                "h-full transition-all duration-300",
                                item.status === 'uploading' ? "bg-blue-500" : "bg-amber-500"
                            )}
                            style={{ width: `${progressValue}%` }}
                        />
                    </div>
                )}

                {item.error && (
                    <p className="text-xs text-destructive truncate">{item.error}</p>
                )}
            </div>

            <div className="shrink-0 flex items-center gap-1 opacity-10 group-hover:opacity-100 transition-opacity">
                {(item.status === 'failed' || item.status === 'interrupted') && (
                    <Button variant="ghost" size="icon" onClick={onRetry} title="Retry">
                        <RefreshCw className="w-4 h-4" />
                    </Button>
                )}
                <Button variant="ghost" size="icon" onClick={onRemove} title="Dismiss">
                    {item.status === 'ready' ? <X className="w-4 h-4" /> : <Trash2 className="w-4 h-4" />}
                </Button>
            </div>
        </div>
    )
}
