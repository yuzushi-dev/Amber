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
import { CheckCircle2, AlertCircle, RefreshCw } from 'lucide-react'
import { ConnectorStatus } from '@/lib/api-connectors'

interface ConnectorCardProps {
    type: string
    status?: ConnectorStatus
    onSync?: () => void
}

export default function ConnectorCard({ type, status, onSync }: ConnectorCardProps) {
    const navigate = useNavigate()

    const getIcon = () => {
        // Simple icon mapping
        return <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary font-bold text-lg">
            {type.charAt(0).toUpperCase()}
        </div>
    }

    const getStatusBadge = () => {
        if (!status || !status.is_authenticated) {
            return <Badge variant="outline" className="text-muted-foreground">Not Configured</Badge>
        }
        if (status.status === 'syncing') {
            return <Badge variant="secondary" className="animate-pulse">Syncing...</Badge>
        }
        if (status.status === 'error') {
            return <Badge variant="destructive">Error</Badge>
        }
        return <Badge variant="default" className="bg-green-600 hover:bg-green-600"><CheckCircle2 className="w-3 h-3 mr-1" /> Active</Badge>
    }

    return (
        <Card>
            <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
                <div className="flex flex-col gap-1">
                    <CardTitle className="text-lg capitalize">{type}</CardTitle>
                    <CardDescription>
                        {type === 'zendesk' ? 'Help Center Articles' :
                            type === 'carbonio' ? 'Mail, Calendar & Chats' :
                                'External Data Source'}
                    </CardDescription>
                </div>
                {getIcon()}
            </CardHeader>
            <CardContent>
                <div className="flex flex-col gap-4 mt-2">
                    <div className="flex justify-between items-center">
                        <span className="text-sm text-muted-foreground">Status</span>
                        {getStatusBadge()}
                    </div>

                    {status?.last_sync_at && (
                        <div className="flex justify-between items-center">
                            <span className="text-sm text-muted-foreground">Last Sync</span>
                            <span className="text-sm">{new Date(status.last_sync_at).toLocaleDateString()}</span>
                        </div>
                    )}

                    {status?.error_message && (
                        <div className="p-2 bg-destructive/10 rounded-md text-xs text-destructive flex items-start gap-2">
                            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                            <span>{status.error_message}</span>
                        </div>
                    )}
                </div>
            </CardContent>
            <CardFooter className="flex justify-between gap-2">
                <Button
                    variant="outline"
                    className="flex-1"
                    onClick={() => navigate({ to: `/admin/settings/connectors/${type}` })}
                >
                    Manage
                </Button>
                {status?.is_authenticated && (
                    <Button
                        variant="secondary"
                        size="icon"
                        onClick={onSync}
                        disabled={status.status === 'syncing'}
                        title="Quick Sync"
                    >
                        <RefreshCw className={`w-4 h-4 ${status.status === 'syncing' ? 'animate-spin' : ''}`} />
                    </Button>
                )}
            </CardFooter>
        </Card>
    )
}
