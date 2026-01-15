/**
 * Jobs and Queues Page
 * ====================
 * 
 * Unified dashboard for system status, displaying worker queues and active pipeline jobs.
 */

import { useState, useEffect } from 'react'
import {
    Activity,
    Server,
    Layers,
    RefreshCw,
    Play,
    Clock,
    X,
    CheckCircle,
    AlertCircle,
    AlertTriangle
} from 'lucide-react'
import { jobsApi, JobInfo, QueuesResponse } from '@/lib/api-admin'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'

export default function JobsAndQueuesPage() {
    // Jobs State
    const [jobs, setJobs] = useState<JobInfo[]>([])
    const [activeJobsCount, setActiveJobsCount] = useState(0)
    const [reservedJobsCount, setReservedJobsCount] = useState(0)
    const [cancellingId, setCancellingId] = useState<string | null>(null)

    // Queues State
    const [queueData, setQueueData] = useState<QueuesResponse | null>(null)

    // Shared State
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const fetchData = async (showLoading = false) => {
        try {
            if (showLoading) setLoading(true)
            const [jobsResponse, queuesResponse] = await Promise.all([
                jobsApi.list({ limit: 50 }),
                jobsApi.getQueues()
            ])

            // Update Jobs
            setJobs(jobsResponse.jobs)
            setActiveJobsCount(jobsResponse.active_count)
            setReservedJobsCount(jobsResponse.reserved_count)

            // Update Queues
            setQueueData(queuesResponse)

            setError(null)
        } catch (err) {
            console.error(err)
            setError('Failed to fetch system status')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchData(true) // Show loading only on initial fetch
        const interval = setInterval(() => fetchData(false), 15000) // 15s silent refresh
        return () => clearInterval(interval)
    }, [])

    const handleCancelJob = async (taskId: string) => {
        try {
            setCancellingId(taskId)
            await jobsApi.cancel(taskId)
            await fetchData()
        } catch (err) {
            console.error('Failed to cancel task:', err)
        } finally {
            setCancellingId(null)
        }
    }

    // --- Helpers ---

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'SUCCESS': return <CheckCircle className="w-4 h-4 text-green-500" />
            case 'FAILURE': return <AlertCircle className="w-4 h-4 text-red-500" />
            case 'STARTED':
            case 'PROGRESS': return <Play className="w-4 h-4 text-blue-500 animate-pulse" />
            case 'PENDING': return <Clock className="w-4 h-4 text-yellow-500" />
            case 'REVOKED': return <X className="w-4 h-4 text-gray-500" />
            default: return <Clock className="w-4 h-4 text-gray-400" />
        }
    }

    const getStatusClass = (status: string) => {
        switch (status) {
            case 'SUCCESS': return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
            case 'FAILURE': return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
            case 'STARTED':
            case 'PROGRESS': return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400'
            case 'PENDING': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400'
            case 'REVOKED': return 'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400'
            default: return 'bg-gray-100 text-gray-800'
        }
    }

    if (loading && jobs.length === 0 && !queueData) {
        return <PageSkeleton />
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="System Status"
                description="Monitor active jobs, workers, and queues."
                actions={
                    <button
                        onClick={() => fetchData(true)}
                        disabled={loading}
                        className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50 text-sm font-medium h-9"
                    >
                        <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                        Refresh
                    </button>
                }
            />

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
                    <p className="text-red-800 dark:text-red-400">{error}</p>
                </div>
            )}

            {/* --- Overview Section --- */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="bg-card border rounded-lg p-4">
                    <div className="text-sm text-muted-foreground flex items-center gap-2">
                        <Activity className="w-4 h-4" /> Active Jobs
                    </div>
                    <div className="text-2xl font-bold text-blue-600">{activeJobsCount}</div>
                </div>
                <div className="bg-card border rounded-lg p-4">
                    <div className="text-sm text-muted-foreground flex items-center gap-2">
                        <Clock className="w-4 h-4" /> Queued Jobs
                    </div>
                    <div className="text-2xl font-bold text-yellow-600">{reservedJobsCount}</div>
                </div>
                <div className="bg-card border rounded-lg p-4">
                    <div className="text-sm text-muted-foreground flex items-center gap-2">
                        <Server className="w-4 h-4" /> Online Workers
                    </div>
                    <div className="text-2xl font-bold text-green-600">{queueData?.workers.length ?? 0}</div>
                </div>
                <div className="bg-card border rounded-lg p-4">
                    <div className="text-sm text-muted-foreground flex items-center gap-2">
                        <Layers className="w-4 h-4" /> Total Messages
                    </div>
                    <div className="text-2xl font-bold">
                        {queueData?.queues.reduce((sum, q) => sum + q.message_count, 0) ?? 0}
                    </div>
                </div>
            </div>

            {/* --- Workers Section --- */}
            <div>
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Server className="w-5 h-5" />
                    Workers
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {(!queueData?.workers || queueData.workers.length === 0) && !loading && (
                        <div className="col-span-full bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 flex items-center gap-3">
                            <AlertTriangle className="w-5 h-5 text-yellow-600" />
                            <span className="text-yellow-800 dark:text-yellow-400">
                                No workers online. Tasks will queue until a worker connects.
                            </span>
                        </div>
                    )}
                    {queueData?.workers.map((worker) => (
                        <div key={worker.hostname} className="bg-card border rounded-lg p-4">
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
                            <div className="space-y-1 text-sm">
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Active Tasks</span>
                                    <span className="font-medium">{worker.active_tasks}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Concurrency</span>
                                    <span className="font-medium">{worker.concurrency}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Queues</span>
                                    <span className="font-medium text-xs max-w-[150px] truncate text-right">{worker.queues.join(', ') || 'celery'}</span>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* --- Jobs List Section --- */}
            <div className="space-y-4">
                <h2 className="text-lg font-semibold flex items-center gap-2">
                    <Activity className="w-5 h-5" />
                    Recent Jobs
                </h2>

                <div className="bg-card border rounded-lg overflow-hidden">
                    <table className="w-full">
                        <thead className="bg-muted/50">
                            <tr>
                                <th className="text-left px-4 py-3 font-medium text-muted-foreground">Task</th>
                                <th className="text-left px-4 py-3 font-medium text-muted-foreground">Status</th>
                                <th className="text-left px-4 py-3 font-medium text-muted-foreground">Progress</th>
                                <th className="text-right px-4 py-3 font-medium text-muted-foreground">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y">
                            {jobs.length === 0 && !loading && (
                                <tr>
                                    <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                                        No jobs found.
                                    </td>
                                </tr>
                            )}
                            {jobs.map((job) => (
                                <tr key={job.task_id} className="hover:bg-muted/30 transition-colors">
                                    <td className="px-4 py-3">
                                        <div className="font-mono text-sm truncate max-w-xs">{job.task_name || 'Task'}</div>
                                        <div className="text-xs text-muted-foreground font-mono">{job.task_id.slice(0, 8)}...</div>
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium ${getStatusClass(job.status)}`}>
                                            {getStatusIcon(job.status)}
                                            {job.status}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3">
                                        {job.progress !== null ? (
                                            <div className="w-32 space-y-1">
                                                <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                                                    <div className="h-full bg-blue-500" style={{ width: `${job.progress}%` }} />
                                                </div>
                                                <div className="text-xs text-right text-muted-foreground">{job.progress}%</div>
                                            </div>
                                        ) : <span className="text-muted-foreground">—</span>}
                                    </td>
                                    <td className="px-4 py-3 text-right">
                                        {(job.status === 'STARTED' || job.status === 'PENDING' || job.status === 'PROGRESS') && (
                                            <button
                                                onClick={() => handleCancelJob(job.task_id)}
                                                disabled={cancellingId === job.task_id}
                                                className="inline-flex items-center gap-1 px-2 py-1 text-xs text-red-600 hover:bg-red-50 rounded disabled:opacity-50"
                                            >
                                                <X className="w-3 h-3" /> Cancel
                                            </button>
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
