
import { useState, useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { Loader2, AlertCircle } from 'lucide-react'
import { SSEManager } from '@/lib/sse'
import { apiClient } from '@/lib/api-client'
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip"
import { toast } from "sonner"


interface LiveStatusBadgeProps {
    documentId: string
    initialStatus: string
    errorMessage?: string
    onComplete?: () => void
    compact?: boolean
    className?: string
}

export default function LiveStatusBadge({ documentId, initialStatus, errorMessage, onComplete, compact = false, className }: LiveStatusBadgeProps) {
    const [status, setStatus] = useState(initialStatus)
    const [currentError, setCurrentError] = useState<string | null>(errorMessage || null)


    useEffect(() => {
        // Only connect if not effectively terminal state
        // "ready" and "failed" are terminal. 
        // "ingested" might wait for a trigger, but usually it transitions fast.
        // We subscribe if it's processing or ingested.
        const terminalStates = ['ready', 'failed', 'completed']
        if (terminalStates.includes(status.toLowerCase())) {
            return
        }

        let manager: SSEManager | null = null;
        let mounted = true;

        const connect = async () => {
            try {
                // Fetch Ticket (Secure)
                const ticketRes = await apiClient.post<{ ticket: string }>('/auth/ticket')
                const ticket = ticketRes.data.ticket

                if (!mounted) return;

                // Use relative path for SSE to leverage Vite proxy / Nginx
                const apiBaseUrl = '/api/v1'
                const monitorUrl = `${apiBaseUrl}/documents/${documentId}/events?ticket=${encodeURIComponent(ticket)}`

                manager = new SSEManager(
                    monitorUrl,
                    (event) => {
                        try {
                            const data = JSON.parse(event.data)
                            if (mounted && data.status) {
                                setStatus(data.status)

                                if (['ready', 'completed', 'failed'].includes(data.status.toLowerCase())) {
                                    if (data.status.toLowerCase() === 'failed') {
                                        // Attempt to read error message from SSE event if available, 
                                        // otherwise we might need to rely on the next fetch or data.message
                                        let errorText = "Ingestion failed";

                                        // If backend sends error in SSE data
                                        // data.error_message or parsing data.message if structured
                                        if (data.error_message) {
                                            try {
                                                const parsed = JSON.parse(data.error_message);
                                                errorText = parsed.message || parsed.code || errorText;
                                            } catch {
                                                errorText = data.error_message;
                                            }
                                        }

                                        toast.error("Ingestion Failed", {
                                            description: errorText,
                                            duration: 5000,
                                        });
                                        // Update local error state for tooltip
                                        setCurrentError(data.error_message);
                                    }
                                    manager?.disconnect()
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
            } catch (e) {
                console.error('Failed to connect to SSE:', e)
            }
        }

        connect()

        return () => {
            mounted = false
            if (manager) {
                manager.disconnect()
            }
        }
    }, [documentId, status, onComplete])

    // Render logic
    const s = status.toLowerCase()

    // Compact mode for sidebar - just show colored dot
    if (compact) {
        if (s === 'ready' || s === 'completed') {
            return <span className={`w-2 h-2 rounded-full bg-success ${className || ''}`} title="Ready" />
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
        let displayError = "Ingestion failed";
        if (currentError) {
            try {
                const parsed = JSON.parse(currentError);
                displayError = parsed.message || displayError;
            } catch {
                displayError = currentError;
            }
        }

        const badge = (
            <Badge variant="destructive" className="uppercase tracking-wider flex items-center gap-1 cursor-help">
                <AlertCircle className="w-3 h-3" /> FAILED
            </Badge>
        );

        return (
            <TooltipProvider>
                <Tooltip>
                    <TooltipTrigger asChild>
                        {badge}
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs break-words">
                        <p>{displayError}</p>
                    </TooltipContent>
                </Tooltip>
            </TooltipProvider>
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
