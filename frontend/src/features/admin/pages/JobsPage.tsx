/**
 * Jobs Page
 * =========
 * 
 * Pipeline control dashboard showing active and recent Celery tasks.
 */

import { useState, useEffect } from 'react'
import { Play, X, RefreshCw, Clock, AlertCircle, CheckCircle } from 'lucide-react'
import { jobsApi, JobInfo } from '@/lib/api-admin'

export default function JobsPage() {
    const [jobs, setJobs] = useState<JobInfo[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [activeCount, setActiveCount] = useState(0)
    const [reservedCount, setReservedCount] = useState(0)
    const [cancellingId, setCancellingId] = useState<string | null>(null)

    const fetchJobs = async () => {
        try {
            setLoading(true)
            const data = await jobsApi.list({ limit: 50 })
            setJobs(data.jobs)
            setActiveCount(data.active_count)
            setReservedCount(data.reserved_count)
            setError(null)
        } catch (err) {
            setError('Failed to fetch jobs')
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchJobs()
        // Poll every 5 seconds
        const interval = setInterval(fetchJobs, 5000)
        return () => clearInterval(interval)
    }, [])

    const handleCancel = async (taskId: string) => {
        try {
            setCancellingId(taskId)
            await jobsApi.cancel(taskId)
            await fetchJobs()
        } catch (err) {
            console.error('Failed to cancel task:', err)
        } finally {
            setCancellingId(null)
        }
    }

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'SUCCESS':
                return <CheckCircle className="w-4 h-4 text-green-500" />
            case 'FAILURE':
                return <AlertCircle className="w-4 h-4 text-red-500" />
            case 'STARTED':
            case 'PROGRESS':
                return <Play className="w-4 h-4 text-blue-500 animate-pulse" />
            case 'PENDING':
                return <Clock className="w-4 h-4 text-yellow-500" />
            case 'REVOKED':
                return <X className="w-4 h-4 text-gray-500" />
            default:
                return <Clock className="w-4 h-4 text-gray-400" />
        }
    }

    const getStatusClass = (status: string) => {
        switch (status) {
            case 'SUCCESS':
                return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
            case 'FAILURE':
                return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
            case 'STARTED':
            case 'PROGRESS':
                return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400'
            case 'PENDING':
                return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400'
            case 'REVOKED':
                return 'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400'
            default:
                return 'bg-gray-100 text-gray-800'
        }
    }

    return (
        <div className="p-6 max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">Pipeline Jobs</h1>
                    <p className="text-muted-foreground">
                        Monitor and control background tasks
                    </p>
                </div>
                <button
                    onClick={fetchJobs}
                    disabled={loading}
                    className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50"
                    aria-label="Refresh jobs"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                <div className="bg-card border rounded-lg p-4">
                    <div className="text-sm text-muted-foreground">Active Tasks</div>
                    <div className="text-2xl font-bold text-blue-600">{activeCount}</div>
                </div>
                <div className="bg-card border rounded-lg p-4">
                    <div className="text-sm text-muted-foreground">Queued Tasks</div>
                    <div className="text-2xl font-bold text-yellow-600">{reservedCount}</div>
                </div>
                <div className="bg-card border rounded-lg p-4">
                    <div className="text-sm text-muted-foreground">Total Listed</div>
                    <div className="text-2xl font-bold">{jobs.length}</div>
                </div>
            </div>

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6">
                    <p className="text-red-800 dark:text-red-400">{error}</p>
                </div>
            )}

            {/* Jobs Table */}
            <div className="bg-card border rounded-lg overflow-hidden">
                <table className="w-full">
                    <thead className="bg-muted/50">
                        <tr>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground">Task</th>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground">Status</th>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground">Progress</th>
                            <th className="text-left px-4 py-3 font-medium text-muted-foreground">Retries</th>
                            <th className="text-right px-4 py-3 font-medium text-muted-foreground">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y">
                        {jobs.length === 0 && !loading && (
                            <tr>
                                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                                    No jobs found. Jobs will appear here when documents are processing.
                                </td>
                            </tr>
                        )}
                        {jobs.map((job) => (
                            <tr key={job.task_id} className="hover:bg-muted/30 transition-colors">
                                <td className="px-4 py-3">
                                    <div className="font-mono text-sm truncate max-w-xs" title={job.task_id}>
                                        {job.task_name || job.task_id.slice(0, 8)}
                                    </div>
                                    <div className="text-xs text-muted-foreground truncate max-w-xs">
                                        {job.task_id}
                                    </div>
                                </td>
                                <td className="px-4 py-3">
                                    <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium ${getStatusClass(job.status)}`}>
                                        {getStatusIcon(job.status)}
                                        {job.status}
                                    </span>
                                </td>
                                <td className="px-4 py-3">
                                    {job.progress !== null ? (
                                        <div className="space-y-1">
                                            <div className="flex items-center gap-2">
                                                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                                                    <div
                                                        className="h-full bg-blue-500 transition-all duration-300"
                                                        style={{ width: `${job.progress}%` }}
                                                    />
                                                </div>
                                                <span className="text-xs text-muted-foreground w-10 text-right">
                                                    {job.progress}%
                                                </span>
                                            </div>
                                            {job.progress_message && (
                                                <div className="text-xs text-muted-foreground truncate max-w-xs">
                                                    {job.progress_message}
                                                </div>
                                            )}
                                        </div>
                                    ) : (
                                        <span className="text-muted-foreground">—</span>
                                    )}
                                </td>
                                <td className="px-4 py-3 text-center">
                                    {job.retries > 0 ? (
                                        <span className="text-yellow-600">{job.retries}</span>
                                    ) : (
                                        <span className="text-muted-foreground">0</span>
                                    )}
                                </td>
                                <td className="px-4 py-3 text-right">
                                    {(job.status === 'STARTED' || job.status === 'PENDING' || job.status === 'PROGRESS') && (
                                        <button
                                            onClick={() => handleCancel(job.task_id)}
                                            disabled={cancellingId === job.task_id}
                                            className="inline-flex items-center gap-1 px-3 py-1 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors disabled:opacity-50"
                                            aria-label={`Cancel task ${job.task_id}`}
                                        >
                                            <X className="w-4 h-4" />
                                            Cancel
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
