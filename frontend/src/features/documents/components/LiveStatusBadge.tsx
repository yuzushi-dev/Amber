
import { useState, useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { Loader2, AlertCircle, CheckCircle2 } from 'lucide-react'
import { SSEManager } from '@/lib/sse'

interface LiveStatusBadgeProps {
    documentId: string
    initialStatus: string
    onComplete?: () => void
}

export default function LiveStatusBadge({ documentId, initialStatus, onComplete }: LiveStatusBadgeProps) {
    const [status, setStatus] = useState(initialStatus)
    const [progress, setProgress] = useState(0)

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
        const monitorUrl = `/v1/documents/${documentId}/events?api_key=${apiKey || ''}`

        const manager = new SSEManager(
            monitorUrl,
            (event) => {
                try {
                    const data = JSON.parse(event.data)
                    if (data.status) {
                        setStatus(data.status)
                        if (data.details?.progress) {
                            setProgress(data.details.progress)
                        }

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
