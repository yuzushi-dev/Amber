
import { useState, useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { Loader2, AlertCircle } from 'lucide-react'
import { SSEManager } from '@/lib/sse'

interface LiveStatusBadgeProps {
    documentId: string
    initialStatus: string
    onComplete?: () => void
    compact?: boolean
    className?: string
}

export default function LiveStatusBadge({ documentId, initialStatus, onComplete, compact = false, className }: LiveStatusBadgeProps) {
    const [status, setStatus] = useState(initialStatus)

    useEffect(() => {
        // Only connect if not effectively terminal state
        // "ready" and "failed" are terminal. 
        // "ingested" might wait for a trigger, but usually it transitions fast.
        // We subscribe if it's processing or ingested.
        const terminalStates = ['ready', 'failed', 'completed']
        if (terminalStates.includes(status.toLowerCase())) {
            return
        }

        const apiKey = localStorage.getItem('api_key')
        const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000/v1'
        const monitorUrl = `${apiBaseUrl}/documents/${documentId}/events?api_key=${encodeURIComponent(apiKey || '')}`

        const manager = new SSEManager(
            monitorUrl,
            (event) => {
                try {
                    const data = JSON.parse(event.data)
                    if (data.status) {
                        setStatus(data.status)

                        if (['ready', 'completed', 'failed'].includes(data.status.toLowerCase())) {
                            manager.disconnect()
                            if (onComplete) onComplete()
                        }
                    }
                } catch (e) {
                    console.error('Failed to parse SSE event:', e)
                }
            },
            (error) => {
                // Silent error handling for badge to avoid UI flicker
                console.debug('SSE connection issue for badge:', error)
            }
        )

        manager.connect()

        return () => {
            manager.disconnect()
        }
    }, [documentId, status, onComplete])

    // Render logic
    const s = status.toLowerCase()

    // Compact mode for sidebar - just show colored dot
    if (compact) {
        if (s === 'ready' || s === 'completed') {
            return <span className={`w-2 h-2 rounded-full bg-green-500 ${className || ''}`} title="Ready" />
        }
        if (s === 'failed') {
            return <span className={`w-2 h-2 rounded-full bg-destructive ${className || ''}`} title="Failed" />
        }
        return (
            <span title={s} className={className}>
                <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />
            </span>
        )
    }

    if (s === 'ready' || s === 'completed') {
        return (
            <Badge variant="success" className="uppercase tracking-wider">
                READY
            </Badge>
        )
    }

    if (s === 'failed') {
        return (
            <Badge variant="destructive" className="uppercase tracking-wider flex items-center gap-1">
                <AlertCircle className="w-3 h-3" /> FAILED
            </Badge>
        )
    }

    // Active processing state
    return (
        <div className="flex flex-col gap-1">
            <Badge variant="secondary" className="uppercase tracking-wider flex items-center gap-1 w-fit">
                <Loader2 className="w-3 h-3 animate-spin" />
                {s}
            </Badge>
            {/* Optional mini progress bar or detailed text could go here */}
            <span className="text-xs text-muted-foreground capitalize">
                {s === 'extracting' && 'Extracting...'}
                {s === 'classifying' && 'Classifying...'}
                {s === 'chunking' && 'Chunking...'}
                {s === 'embedding' && 'Embedding...'}
                {s === 'graph_sync' && 'Graph Sync...'}
            </span>
        </div>
    )
}
