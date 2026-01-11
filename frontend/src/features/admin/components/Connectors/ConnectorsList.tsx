import { useEffect, useState } from 'react'
import { connectorsApi, ConnectorStatus } from '@/lib/api-connectors'
import ConnectorCard from './ConnectorCard'
import { ConnectorCardSkeleton } from './ConnectorCardSkeleton'
import { toast } from 'sonner'

export default function ConnectorsList() {
    const [connectors, setConnectors] = useState<string[]>([])
    const [statuses, setStatuses] = useState<Record<string, ConnectorStatus>>({})
    const [loading, setLoading] = useState(true)

    const fetchData = async () => {
        try {
            const list = await connectorsApi.list()
            setConnectors(list)

            // Fetch status for each
            const statusMap: Record<string, ConnectorStatus> = {}
            await Promise.all(list.map(async (type) => {
                try {
                    const status = await connectorsApi.getStatus(type)
                    statusMap[type] = status
                } catch (e) {
                    console.error(`Failed to get status for ${type}`, e)
                }
            }))
            setStatuses(statusMap)
        } catch (err) {
            console.error('Failed to load connectors:', err)
            toast.error('Failed to load available connectors')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchData()

        // Poll for updates every 10s
        const interval = setInterval(fetchData, 10000)
        return () => clearInterval(interval)
    }, [])

    const handleSync = async (type: string) => {
        try {
            await connectorsApi.sync(type)
            toast.success('Sync started')
            fetchData()
        } catch (err) {
            toast.error('Failed to start sync')
        }
    }

    if (loading) {
        return (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {[1, 2, 3].map(i => (
                    <ConnectorCardSkeleton key={i} />
                ))}
            </div>
        )
    }

    if (connectors.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center py-16 px-4 border border-dashed border-muted rounded-lg bg-muted/5">
                <div className="w-16 h-16 mb-4 rounded-full bg-muted/20 flex items-center justify-center">
                    <svg className="w-8 h-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                    </svg>
                </div>
                <h3 className="text-lg font-semibold mb-1">No Connectors Available</h3>
                <p className="text-muted-foreground text-center max-w-sm">
                    External data source connectors are not configured on this instance.
                </p>
            </div>
        )
    }

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {connectors.map(type => (
                <ConnectorCard
                    key={type}
                    type={type}
                    status={statuses[type]}
                    onSync={() => handleSync(type)}
                />
            ))}
        </div>
    )
}
