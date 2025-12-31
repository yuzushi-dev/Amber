/**
 * Queues Page
 * ===========
 * 
 * Queue and worker status dashboard.
 */

import { useState, useEffect } from 'react'
import { Server, Layers, Activity, RefreshCw, AlertTriangle } from 'lucide-react'
import { jobsApi, QueuesResponse, WorkerInfo } from '@/lib/api-admin'

export default function QueuesPage() {
    const [data, setData] = useState<QueuesResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const fetchQueues = async () => {
        try {
            setLoading(true)
            const response = await jobsApi.getQueues()
            setData(response)
            setError(null)
        } catch (err) {
            setError('Failed to fetch queue status')
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchQueues()
        const interval = setInterval(fetchQueues, 10000)
        return () => clearInterval(interval)
    }, [])

    return (
        <div className="p-6 max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">Queue Monitor</h1>
                    <p className="text-muted-foreground">
                        Worker status and queue depths
                    </p>
                </div>
                <button
                    onClick={fetchQueues}
                    disabled={loading}
                    className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6">
                    <p className="text-red-800 dark:text-red-400">{error}</p>
                </div>
            )}

            {/* Summary Card */}
            <div className="bg-card border rounded-lg p-6 mb-6">
                <div className="flex items-center gap-3 mb-4">
                    <Activity className="w-6 h-6 text-primary" />
                    <h2 className="text-lg font-semibold">System Overview</h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div>
                        <div className="text-3xl font-bold text-blue-600">
                            {data?.total_active_tasks ?? 0}
                        </div>
                        <div className="text-sm text-muted-foreground">
                            Active Tasks
                        </div>
                    </div>
                    <div>
                        <div className="text-3xl font-bold text-green-600">
                            {data?.workers.length ?? 0}
                        </div>
                        <div className="text-sm text-muted-foreground">
                            Online Workers
                        </div>
                    </div>
                    <div>
                        <div className="text-3xl font-bold">
                            {data?.queues.reduce((sum, q) => sum + q.message_count, 0) ?? 0}
                        </div>
                        <div className="text-sm text-muted-foreground">
                            Queued Messages
                        </div>
                    </div>
                </div>
            </div>

            {/* Workers Section */}
            <div className="mb-6">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Server className="w-5 h-5" />
                    Workers
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {(!data?.workers || data.workers.length === 0) && !loading && (
                        <div className="col-span-full bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 flex items-center gap-3">
                            <AlertTriangle className="w-5 h-5 text-yellow-600" />
                            <span className="text-yellow-800 dark:text-yellow-400">
                                No workers online. Tasks will queue until a worker connects.
                            </span>
                        </div>
                    )}
                    {data?.workers.map((worker) => (
                        <WorkerCard key={worker.hostname} worker={worker} />
                    ))}
                </div>
            </div>

            {/* Queues Section */}
            <div>
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Layers className="w-5 h-5" />
                    Queues
                </h2>
                <div className="bg-card border rounded-lg overflow-hidden">
                    <table className="w-full">
                        <thead className="bg-muted/50">
                            <tr>
                                <th className="text-left px-4 py-3 font-medium text-muted-foreground">Queue</th>
                                <th className="text-right px-4 py-3 font-medium text-muted-foreground">Messages</th>
                                <th className="text-right px-4 py-3 font-medium text-muted-foreground">Consumers</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y">
                            {(!data?.queues || data.queues.length === 0) && !loading && (
                                <tr>
                                    <td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">
                                        No queue information available
                                    </td>
                                </tr>
                            )}
                            {data?.queues.map((queue) => (
                                <tr key={queue.queue_name} className="hover:bg-muted/30 transition-colors">
                                    <td className="px-4 py-3 font-mono">{queue.queue_name}</td>
                                    <td className="px-4 py-3 text-right">
                                        <span className={queue.message_count > 100 ? 'text-yellow-600 font-semibold' : ''}>
                                            {queue.message_count}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-right">
                                        {queue.consumer_count > 0 ? (
                                            <span className="text-green-600">{queue.consumer_count}</span>
                                        ) : (
                                            <span className="text-red-600">0</span>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}

function WorkerCard({ worker }: { worker: WorkerInfo }) {
    return (
        <div className="bg-card border rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
                <div className="font-mono text-sm truncate" title={worker.hostname}>
                    {worker.hostname.split('@')[1] || worker.hostname}
                </div>
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${worker.status === 'online'
                    ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                    : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                    }`}>
                    {worker.status}
                </span>
            </div>
            <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                    <span className="text-muted-foreground">Active</span>
                    <span className="font-medium">{worker.active_tasks}</span>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted-foreground">Processed</span>
                    <span className="font-medium">{worker.processed_total}</span>
                </div>
                <div className="flex justify-between">
                    <span className="text-muted-foreground">Concurrency</span>
                    <span className="font-medium">{worker.concurrency}</span>
                </div>
                <div className="pt-2 border-t">
                    <span className="text-muted-foreground text-xs">Queues: </span>
                    <span className="text-xs">{worker.queues.join(', ') || 'celery'}</span>
                </div>
            </div>
        </div>
    )
}
