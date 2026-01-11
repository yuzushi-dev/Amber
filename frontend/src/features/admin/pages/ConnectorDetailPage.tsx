import { useParams } from '@tanstack/react-router'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import ZendeskConfigForm from '../components/Connectors/ZendeskConfigForm'
import { ConfluenceConfigForm } from '../components/Connectors/ConfluenceConfigForm'
import CarbonioConfigForm from '../components/Connectors/CarbonioConfigForm'
import ConnectorContentBrowser from '../components/Connectors/ConnectorContentBrowser'
import { useQuery } from '@tanstack/react-query'
import { connectorsApi } from '@/lib/api-connectors'
import { Badge } from '@/components/ui/badge'

export default function ConnectorDetailPage() {
    const { connectorType } = useParams({ from: '/admin/settings/connectors/$connectorType' })

    // Fetch status mainly to check authentication
    const { data: status, refetch } = useQuery({
        queryKey: ['connector-status', connectorType],
        queryFn: () => connectorsApi.getStatus(connectorType)
    })

    return (
        <div className="container mx-auto p-6 max-w-5xl space-y-8">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight capitalize">{connectorType} Connector</h1>
                    <p className="text-muted-foreground">
                        Configure connection and manage content ingestion.
                    </p>
                </div>
                {status && (
                    <Badge variant={status.is_authenticated ? 'default' : 'outline'}>
                        {status.is_authenticated ? 'Connected' : 'Not Connected'}
                    </Badge>
                )}
            </div>

            <Tabs defaultValue="content" className="space-y-4">
                <TabsList>
                    <TabsTrigger value="content">Content Browser</TabsTrigger>
                    <TabsTrigger value="config">Configuration</TabsTrigger>
                </TabsList>

                <TabsContent value="config">
                    <div className="max-w-xl">
                        {connectorType === 'zendesk' && <ZendeskConfigForm onSuccess={refetch} />}
                        {connectorType === 'confluence' && <ConfluenceConfigForm onSuccess={refetch} />}
                        {connectorType === 'carbonio' && <CarbonioConfigForm onSuccess={refetch} />}
                        {!['zendesk', 'confluence', 'carbonio'].includes(connectorType!) && (
                            <div className="p-4 border rounded-md text-muted-foreground">
                                Configuration form for {connectorType} not implemented.
                            </div>
                        )}
                    </div>
                </TabsContent>

                <TabsContent value="content">
                    {status?.is_authenticated ? (
                        <ConnectorContentBrowser type={connectorType} />
                    ) : (
                        <div className="flex flex-col items-center justify-center p-12 border rounded-md bg-muted/10">
                            <h3 className="text-lg font-semibold">Authentication Required</h3>
                            <p className="text-muted-foreground mb-4">
                                Please configure the connector with valid credentials to browse content.
                            </p>
                        </div>
                    )}
                </TabsContent>
            </Tabs>
        </div>
    )
}
