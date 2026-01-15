import { PageHeader } from '../components/PageHeader'
import ConnectorsList from '../components/Connectors/ConnectorsList'

export default function ConnectorsPage() {
    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="Connectors"
                description="Manage external data sources and sync configurations."
            />
            <ConnectorsList />
        </div>
    )
}
