import { useEffect, useState } from 'react'
import { connectorsApi, ConnectorStatus } from '@/lib/api-connectors'
import ConnectorCard from './ConnectorCard'
import { toast } from 'sonner'
import { Skeleton } from '@/components/ui/skeleton'

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
        return <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2].map(i => (
                <Skeleton key={i} className="h-[200px] w-full" />
            ))}
        </div>
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
