import { useNavigate } from '@tanstack/react-router'
import {
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, AlertCircle, RefreshCw, Clock } from 'lucide-react'
import { ConnectorStatus } from '@/lib/api-connectors'
import { ConnectorIcon } from './ConnectorIcons'
import { cn } from '@/lib/utils'

interface ConnectorCardProps {
    type: string
    status?: ConnectorStatus
    onSync?: () => void
}

/**
 * Get human-readable description for each connector type
 */
function getConnectorDescription(type: string): string {
    switch (type.toLowerCase()) {
        case 'zendesk':
            return 'Help Center Articles'
        case 'confluence':
            return 'Wiki & Documentation'
        case 'carbonio':
            return 'Mail, Calendar & Chats'
        default:
            return 'External Data Source'
    }
}

/**
 * Format date as relative time (e.g., "2 hours ago")
 */
function formatRelativeTime(dateString: string): string {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
}

export default function ConnectorCard({ type, status, onSync }: ConnectorCardProps) {
    const navigate = useNavigate()

    const isAuthenticated = status?.is_authenticated
    const isSyncing = status?.status === 'syncing'
    const hasError = status?.status === 'error'

    const getStatusBadge = () => {
        if (!status || !isAuthenticated) {
            return (
                <Badge variant="outline" className="text-muted-foreground border-muted-foreground/30">
                    Not Configured
                </Badge>
            )
        }
        if (isSyncing) {
            return (
                <Badge variant="secondary" className="bg-primary/20 text-primary border-primary/30 animate-pulse">
                    <RefreshCw className="w-3 h-3 mr-1 animate-spin" />
                    Syncing
                </Badge>
            )
        }
        if (hasError) {
            return (
                <Badge variant="destructive" className="shadow-glow-destructive">
                    <AlertCircle className="w-3 h-3 mr-1" />
                    Error
                </Badge>
            )
        }
        return (
            <Badge className="bg-green-600/90 hover:bg-green-600 text-white border-green-500/30">
                <CheckCircle2 className="w-3 h-3 mr-1" />
                Active
            </Badge>
        )
    }

    return (
        <Card
            className={cn(
                'group relative overflow-hidden transition-all duration-300',
                'hover:border-primary/40 hover:shadow-glow-sm hover:-translate-y-0.5',
                isAuthenticated && 'border-border/80',
                hasError && 'border-destructive/30'
            )}
        >
            {/* Subtle gradient overlay on hover */}
            <div className="absolute inset-0 bg-gradient-to-br from-primary/0 to-primary/0 group-hover:from-primary/5 group-hover:to-transparent transition-all duration-500 pointer-events-none" />

            <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2 relative">
                <div className="flex flex-col gap-1">
                    <CardTitle className="text-lg capitalize group-hover:text-primary/90 transition-colors">
                        {type}
                    </CardTitle>
                    <CardDescription>
                        {getConnectorDescription(type)}
                    </CardDescription>
                </div>
                <ConnectorIcon
                    type={type}
                    size="md"
                    className="group-hover:scale-110 transition-transform duration-300"
                />
            </CardHeader>

            <CardContent className="relative">
                <div className="flex flex-col gap-3 mt-2">
                    {/* Status row */}
                    <div className="flex justify-between items-center">
                        <span className="text-sm text-muted-foreground">Status</span>
                        {getStatusBadge()}
                    </div>

                    {/* Last sync row */}
                    {status?.last_sync_at && (
                        <div className="flex justify-between items-center">
                            <span className="text-sm text-muted-foreground flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                Last Sync
                            </span>
                            <span className="text-sm font-medium">
                                {formatRelativeTime(status.last_sync_at)}
                            </span>
                        </div>
                    )}

                    {/* Error message */}
                    {status?.error_message && (
                        <div className="p-2.5 bg-destructive/10 border border-destructive/20 rounded-md text-xs text-destructive flex items-start gap-2 mt-1">
                            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                            <span className="line-clamp-2">{status.error_message}</span>
                        </div>
                    )}
                </div>
            </CardContent>

            <CardFooter className="flex justify-between gap-2 relative">
                <Button
                    variant="outline"
                    className="flex-1 group-hover:border-primary/40 group-hover:text-primary transition-colors"
                    onClick={() => navigate({ to: `/admin/settings/connectors/${type}` })}
                >
                    Manage
                </Button>
                {isAuthenticated && (
                    <Button
                        variant="secondary"
                        size="icon"
                        onClick={onSync}
                        disabled={isSyncing}
                        title="Quick Sync"
                        className={cn(
                            'transition-all',
                            isSyncing && 'bg-primary/20'
                        )}
                    >
                        <RefreshCw className={cn('w-4 h-4', isSyncing && 'animate-spin')} />
                    </Button>
                )}
            </CardFooter>
        </Card>
    )
}
