import { useParams } from '@tanstack/react-router'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import ZendeskConfigForm from '../components/Connectors/ZendeskConfigForm'
import { ConfluenceConfigForm } from '../components/Connectors/ConfluenceConfigForm'
import CarbonioConfigForm from '../components/Connectors/CarbonioConfigForm'
import ConnectorContentBrowser from '../components/Connectors/ConnectorContentBrowser'
import { useQuery } from '@tanstack/react-query'
import { connectorsApi } from '@/lib/api-connectors'
import { Badge } from '@/components/ui/badge'
import { ConnectorIcon } from '../components/Connectors/ConnectorIcons'
import { CheckCircle2, Settings2, FileSearch } from 'lucide-react'
import { cn } from '@/lib/utils'

export default function ConnectorDetailPage() {
    const { connectorType } = useParams({ from: '/admin/settings/connectors/$connectorType' })

    // Fetch status mainly to check authentication
    const { data: status, refetch } = useQuery({
        queryKey: ['connector-status', connectorType],
        queryFn: () => connectorsApi.getStatus(connectorType)
    })

    const isAuthenticated = status?.is_authenticated

    // Smart tab default: Configuration first if not connected
    const defaultTab = isAuthenticated ? 'content' : 'config'

    return (
        <div className="container mx-auto p-6 max-w-5xl space-y-8">
            {/* Enhanced Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <ConnectorIcon
                        type={connectorType}
                        size="lg"
                        className="shrink-0"
                    />
                    <div>
                        <h1 className="text-3xl font-bold tracking-tight capitalize">
                            {connectorType} Connector
                        </h1>
                        <p className="text-muted-foreground">
                            Configure connection and manage content ingestion.
                        </p>
                    </div>
                </div>
                {status && (
                    <Badge
                        variant={isAuthenticated ? 'default' : 'outline'}
                        className={cn(
                            'text-sm py-1 px-3',
                            isAuthenticated && 'bg-green-600/90 hover:bg-green-600 text-white'
                        )}
                    >
                        {isAuthenticated && <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />}
                        {isAuthenticated ? 'Connected' : 'Not Connected'}
                    </Badge>
                )}
            </div>

            <Tabs defaultValue={defaultTab} className="space-y-6">
                <TabsList className="grid w-full max-w-md grid-cols-2">
                    <TabsTrigger value="content" className="flex items-center gap-2">
                        <FileSearch className="w-4 h-4" />
                        Content Browser
                    </TabsTrigger>
                    <TabsTrigger value="config" className="flex items-center gap-2">
                        <Settings2 className="w-4 h-4" />
                        Configuration
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="config" className="space-y-4">
                    <div className="max-w-xl">
                        {connectorType === 'zendesk' && <ZendeskConfigForm onSuccess={refetch} />}
                        {connectorType === 'confluence' && <ConfluenceConfigForm onSuccess={refetch} />}
                        {connectorType === 'carbonio' && <CarbonioConfigForm onSuccess={refetch} />}
                        {!['zendesk', 'confluence', 'carbonio'].includes(connectorType!) && (
                            <div className="p-6 border border-dashed rounded-lg bg-muted/5 text-center">
                                <p className="text-muted-foreground">
                                    Configuration form for <span className="font-medium">{connectorType}</span> not implemented.
                                </p>
                            </div>
                        )}
                    </div>
                </TabsContent>

                <TabsContent value="content">
                    {isAuthenticated ? (
                        <ConnectorContentBrowser type={connectorType} />
                    ) : (
                        <div className="flex flex-col items-center justify-center py-16 px-4 border border-dashed border-muted rounded-lg bg-muted/5">
                            <div className="w-16 h-16 mb-4 rounded-full bg-primary/10 flex items-center justify-center">
                                <Settings2 className="w-8 h-8 text-primary" />
                            </div>
                            <h3 className="text-lg font-semibold mb-1">Authentication Required</h3>
                            <p className="text-muted-foreground text-center max-w-sm mb-4">
                                Please configure the connector with valid credentials to browse content.
                            </p>
                            <p className="text-sm text-muted-foreground">
                                Switch to the <span className="font-medium text-foreground">Configuration</span> tab to get started.
                            </p>
                        </div>
                    )}
                </TabsContent>
            </Tabs>
        </div>
    )
}
