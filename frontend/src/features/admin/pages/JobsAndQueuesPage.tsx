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
    AlertTriangle,
    StopCircle
} from 'lucide-react'
import { jobsApi, JobInfo, QueuesResponse } from '@/lib/api-admin'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'
import { StatCard } from '@/components/ui/StatCard'

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
    const [stoppingAll, setStoppingAll] = useState(false)

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
            const job = jobs.find(j => j.task_id === taskId)
            const isRunning = job?.status === 'STARTED' || job?.status === 'PROGRESS'
            await jobsApi.cancel(taskId, isRunning)
            await fetchData()
        } catch (err) {
            console.error('Failed to cancel task:', err)
        } finally {
            setCancellingId(null)
        }
    }

    const handleStopAll = async () => {
        if (!confirm('Are you sure you want to stop all jobs? This will immediately terminate all running tasks and clear all queued tasks.')) {
            return
        }
        try {
            setStoppingAll(true)
            await jobsApi.cancelAll()
            await fetchData()
        } catch (err) {
            console.error('Failed to stop all jobs:', err)
        } finally {
            setStoppingAll(false)
        }
    }

    // --- Helpers ---

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'SUCCESS': return <CheckCircle className="w-4 h-4 text-success" />
            case 'FAILURE': return <AlertCircle className="w-4 h-4 text-destructive" />
            case 'STARTED':
            case 'PROGRESS': return <Play className="w-4 h-4 text-info animate-pulse" />
            case 'PENDING': return <Clock className="w-4 h-4 text-warning" />
            case 'REVOKED': return <X className="w-4 h-4 text-muted-foreground" />
            default: return <Clock className="w-4 h-4 text-muted-foreground" />
        }
    }

    const getStatusClass = (status: string) => {
        switch (status) {
            case 'SUCCESS': return 'bg-success-muted text-success-foreground border border-success/30'
            case 'FAILURE': return 'bg-destructive/10 text-destructive border border-destructive/20'
            case 'STARTED':
            case 'PROGRESS': return 'bg-info-muted text-info-foreground border border-info/30'
            case 'PENDING': return 'bg-warning-muted text-warning-foreground border border-warning/30'
            case 'REVOKED': return 'bg-muted/50 text-muted-foreground border border-border'
            default: return 'bg-muted/50 text-muted-foreground border border-border'
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
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleStopAll}
                            disabled={stoppingAll || (activeJobsCount === 0 && reservedJobsCount === 0)}
                            className="flex items-center gap-2 px-4 py-2 bg-destructive/10 hover:bg-destructive/20 text-destructive rounded-md transition-colors disabled:opacity-50 text-sm font-medium h-9"
                        >
                            <StopCircle className={`w-3.5 h-3.5 ${stoppingAll ? 'animate-pulse' : ''}`} />
                            Stop All Jobs
                        </button>
                        <button
                            onClick={() => fetchData(true)}
                            disabled={loading}
                            className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50 text-sm font-medium h-9"
                        >
                            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                            Refresh
                        </button>
                    </div>
                }
            />

            {error && (
                <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4">
                    <p className="text-destructive">{error}</p>
                </div>
            )}

            {/* --- Overview Section --- */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <StatCard
                    icon={Activity}
                    label="Active Jobs"
                    value={activeJobsCount}
                    color="blue"
                    delay={0.1}
                />
                <StatCard
                    icon={Clock}
                    label="Queued Jobs"
                    value={reservedJobsCount}
                    color="yellow"
                    delay={0.2}
                />
                <StatCard
                    icon={Server}
                    label="Online Workers"
                    value={queueData?.workers.length ?? 0}
                    color="green"
                    delay={0.3}
                />
                <StatCard
                    icon={Layers}
                    label="Total Messages"
                    value={queueData?.queues.reduce((sum, q) => sum + q.message_count, 0) ?? 0}
                    color="primary"
                    delay={0.4}
                />
            </div>

            {/* --- Workers Section --- */}
            <div>
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Server className="w-5 h-5" />
                    Workers
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {(!queueData?.workers || queueData.workers.length === 0) && !loading && (
                        <div className="col-span-full bg-warning-muted/40 border border-warning/30 rounded-lg p-4 flex items-center gap-3">
                            <AlertTriangle className="w-5 h-5 text-warning" />
                            <span className="text-warning">
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
                                    ? 'bg-success-muted text-success'
                                    : 'bg-destructive/10 text-destructive'
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
                                                    <div className="h-full bg-info" style={{ width: `${job.progress}%` }} />
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
                                                className="inline-flex items-center gap-1 px-2 py-1 text-xs text-destructive hover:bg-destructive/10 rounded disabled:opacity-50"
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
