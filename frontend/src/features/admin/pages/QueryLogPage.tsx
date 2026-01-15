import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select"
import { maintenanceApi, QueryMetrics } from '@/lib/api-admin'
import { QueryLogTable } from '../components/QueryLogTable'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'

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
        (q.conversation_id && q.conversation_id.includes(searchTerm))
    )

    if (isLoading && queries.length === 0) {
        return <PageSkeleton mode="list" />
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="Query Log"
                description="Detailed inspection of recent RAG queries for debugging cost and latency."
                actions={
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={fetchQueries}
                        disabled={isLoading}
                        className="gap-2 h-9 text-xs"
                    >
                        <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
                        Refresh
                    </Button>
                }
            />

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
                <Select
                    value={limit.toString()}
                    onValueChange={(val) => setLimit(Number(val))}
                >
                    <SelectTrigger className="w-[180px] bg-neutral-900/50 border-neutral-800">
                        <SelectValue placeholder="Limit" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="50">Last 50</SelectItem>
                        <SelectItem value="100">Last 100</SelectItem>
                        <SelectItem value="500">Last 500</SelectItem>
                        <SelectItem value="1000">Last 1000</SelectItem>
                    </SelectContent>
                </Select>
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
