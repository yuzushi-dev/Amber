import ConnectorsList from '../components/Connectors/ConnectorsList'

export default function ConnectorsPage() {
    return (
        <div className="container mx-auto p-6 max-w-5xl space-y-8">
            <div className="flex flex-col gap-2">
                <h1 className="text-3xl font-bold tracking-tight">Connectors</h1>
                <p className="text-muted-foreground">
                    Manage external data sources and sync configurations.
                </p>
            </div>

            <ConnectorsList />
        </div>
    )
}
