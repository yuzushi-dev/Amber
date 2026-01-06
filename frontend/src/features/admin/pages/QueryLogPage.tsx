import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { maintenanceApi, QueryMetrics } from '@/lib/api-admin'
import { QueryLogTable } from '../components/QueryLogTable'

export default function QueryLogPage() {
    const [queries, setQueries] = useState<QueryMetrics[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [searchTerm, setSearchTerm] = useState('')
    const [limit, setLimit] = useState(100)

    const fetchQueries = async () => {
        setIsLoading(true)
        try {
            const data = await maintenanceApi.getQueryMetrics(limit)
            setQueries(data)
        } catch (error) {
            console.error('Failed to fetch query logs:', error)
        } finally {
            setIsLoading(false)
        }
    }

    useEffect(() => {
        fetchQueries()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [limit])

    // Client-side filtering
    const filteredQueries = queries.filter(q =>
        q.query.toLowerCase().includes(searchTerm.toLowerCase()) ||
        q.query_id.includes(searchTerm) ||
        (q.generation.conversation_id && q.generation.conversation_id.includes(searchTerm))
    )

    return (
        <div className="space-y-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight text-white/90">Query Log</h1>
                    <p className="text-neutral-400">
                        Detailed inspection of recent RAG queries for debugging cost and latency.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={fetchQueries}
                        disabled={isLoading}
                        className="gap-2"
                    >
                        <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                        Refresh
                    </Button>
                </div>
            </div>

            <div className="flex items-center gap-4">
                <div className="relative flex-1 max-w-sm">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-neutral-500" />
                    <Input
                        placeholder="Search query, ID, or conversation..."
                        className="pl-9 bg-neutral-900/50 border-neutral-800"
                        value={searchTerm}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchTerm(e.target.value)}
                    />
                </div>
                <select
                    className="h-10 rounded-md border border-neutral-800 bg-neutral-900/50 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                    value={limit}
                    onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setLimit(Number(e.target.value))}
                >
                    <option value={50}>Last 50</option>
                    <option value={100}>Last 100</option>
                    <option value={500}>Last 500</option>
                    <option value={1000}>Last 1000</option>
                </select>
            </div>

            <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
            >
                <QueryLogTable data={filteredQueries} isLoading={isLoading} />
            </motion.div>
        </div>
    )
}
