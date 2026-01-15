/**
 * Ragas Benchmark Dashboard
 * =========================
 *
 * Sub-panel for viewing and running Ragas evaluation benchmarks.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { BarChart3, CheckCircle, Clock, FileJson, Play, RefreshCw, Upload, XCircle, Trash2 } from 'lucide-react'
import { ragasApi, RagasStats, RagasDataset, BenchmarkRunSummary } from '../../../lib/api-admin'
import { StatCard } from '@/components/ui/StatCard'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { toast } from 'sonner'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select"
import { PageHeader } from './PageHeader'
import { PageSkeleton } from './PageSkeleton'

export function RagasSubPanel() {
    const [stats, setStats] = useState<RagasStats | null>(null)
    const [datasets, setDatasets] = useState<RagasDataset[]>([])
    const [runs, setRuns] = useState<BenchmarkRunSummary[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selectedDataset, setSelectedDataset] = useState<string>('')
    const [isRunning, setIsRunning] = useState(false)
    const [activeJobId, setActiveJobId] = useState<string | null>(null)

    const fetchData = useCallback(async () => {
        try {
            setLoading(true)
            const [statsData, datasetsData, runsData] = await Promise.all([
                ragasApi.getStats(),
                ragasApi.getDatasets(),
                ragasApi.listRuns({ limit: 10 })
            ])
            setStats(statsData)
            setDatasets(datasetsData)
            setRuns(runsData)
            if (datasetsData.length > 0 && !selectedDataset) {
                setSelectedDataset(datasetsData[0].name)
            }
            setError(null)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load data')
        } finally {
            setLoading(false)
        }
    }, [selectedDataset])

    useEffect(() => {
        fetchData()
    }, [fetchData])

    // Poll for active job status
    useEffect(() => {
        if (!activeJobId) return

        const interval = setInterval(async () => {
            try {
                const status = await ragasApi.getJobStatus(activeJobId)
                if (status.status === 'completed' || status.status === 'failed') {
                    setActiveJobId(null)
                    setIsRunning(false)
                    fetchData()
                }
            } catch {
                setActiveJobId(null)
                setIsRunning(false)
            }
        }, 2000)

        return () => clearInterval(interval)
    }, [activeJobId, fetchData])

    const handleRunBenchmark = async () => {
        if (!selectedDataset || isRunning) return

        try {
            setIsRunning(true)
            const result = await ragasApi.runBenchmark({ dataset_name: selectedDataset })
            setActiveJobId(result.benchmark_run_id)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to start benchmark')
            setIsRunning(false)
        }
    }

    const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0]
        if (!file) return

        try {
            await ragasApi.uploadDataset(file)
            fetchData()
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to upload dataset')
        }
    }

    const handleDeleteRun = async (runId: string) => {
        if (!confirm('Are you sure you want to delete this benchmark run?')) return

        try {
            await ragasApi.deleteRun(runId)
            fetchData()
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to delete run')
        }
    }

    const handleDeleteDataset = async () => {
        if (!selectedDataset) return
        if (!confirm(`Are you sure you want to delete dataset "${selectedDataset}"?`)) return

        try {
            await ragasApi.deleteDataset(selectedDataset)
            setSelectedDataset('')
            fetchData()
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to delete dataset')
        }
    }

    // Polling for active runs + detect failures and show toasts
    const shownErrors = React.useRef<Set<string>>(new Set())

    useEffect(() => {
        const hasActive = runs.some(r => r.status === 'running' || r.status === 'pending')
        if (hasActive) {
            const interval = setInterval(fetchData, 1000)
            return () => clearInterval(interval)
        }

        // Check for new failures and show toasts
        runs.filter(r => r.status === 'failed').forEach(run => {
            if (!shownErrors.current.has(run.id)) {
                shownErrors.current.add(run.id)
                const errorMsg = run.error_message || 'Unknown error'

                // Categorize error type for appropriate toast
                if (errorMsg.toLowerCase().includes('quota') || errorMsg.includes('429')) {
                    toast.error('OpenAI Quota Exceeded', {
                        description: 'Please check your billing at platform.openai.com',
                        duration: 10000,
                    })
                } else if (errorMsg.toLowerCase().includes('max_tokens') || errorMsg.toLowerCase().includes('incomplete')) {
                    toast.error('Output Truncated', {
                        description: 'The response was cut off. Check token limits.',
                        duration: 8000,
                    })
                } else {
                    toast.error('Benchmark Failed', {
                        description: errorMsg.slice(0, 100),
                        duration: 8000,
                    })
                }
            }
        })
        // eslint-disable-next-line react-hooks/exhaustive-deps -- fetchData is stable, polling is intentional
    }, [runs])

    const formatScore = (score: number | null) => {
        if (score === null || score === undefined) return '—'
        return `${(score * 100).toFixed(1)}%`
    }

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'completed':
                return <CheckCircle className="w-4 h-4 text-success" />
            case 'failed':
                return <XCircle className="w-4 h-4 text-destructive" />
            case 'running':
                return <RefreshCw className="w-4 h-4 text-primary animate-spin" />
            default:
                return <Clock className="w-4 h-4 text-muted-foreground" />
        }
    }

    if (loading && !stats) {
        return <PageSkeleton />
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-6">
            <PageHeader
                title="RAGAS Evaluation"
                description="Systematic RAG quality benchmarking with Faithfulness and Relevancy metrics."
                actions={
                    <button
                        onClick={() => fetchData()}
                        disabled={loading}
                        className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50 text-sm font-medium h-9"
                    >
                        <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                        Refresh
                    </button>
                }
            />

            {error && (
                <Alert variant="destructive" className="mb-6">
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}

            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard
                    icon={BarChart3}
                    label="Total Runs"
                    value={stats?.total_runs ?? 0}
                />
                <StatCard
                    icon={CheckCircle}
                    label="Completed"
                    value={stats?.completed_runs ?? 0}
                />
                <StatCard
                    icon={FileJson}
                    label="Avg Faithfulness"
                    value={formatScore(stats?.avg_faithfulness ?? null)}
                    isString
                />
                <StatCard
                    icon={FileJson}
                    label="Avg Relevancy"
                    value={formatScore(stats?.avg_relevancy ?? null)}
                    isString
                />
            </div>

            {/* Run Benchmark Section */}
            <div className="bg-card border rounded-lg p-6">
                <h3 className="text-lg font-semibold mb-4">Run Benchmark</h3>

                <div className="flex flex-wrap gap-4 items-end">
                    <div className="flex-1 min-w-[200px]">
                        <label className="block text-sm text-muted-foreground mb-2">Dataset</label>
                        <div className="flex gap-2">
                            <Select
                                value={selectedDataset}
                                onValueChange={(val) => setSelectedDataset(val)}
                                disabled={isRunning}
                            >
                                <SelectTrigger className="w-full min-w-[200px]">
                                    <SelectValue placeholder="Select a dataset" />
                                </SelectTrigger>
                                <SelectContent>
                                    {datasets.length === 0 && (
                                        <SelectItem value="none" disabled>No datasets available</SelectItem>
                                    )}
                                    {datasets.map((ds) => (
                                        <SelectItem key={ds.name} value={ds.name}>
                                            {ds.name} ({ds.sample_count} samples)
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <button
                                onClick={handleDeleteDataset}
                                disabled={!selectedDataset || isRunning}
                                className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-md transition-colors disabled:opacity-50"
                                title="Delete Dataset"
                            >
                                <Trash2 className="w-4 h-4" />
                            </button>
                        </div>
                    </div>

                    <button
                        onClick={handleRunBenchmark}
                        disabled={!selectedDataset || isRunning}
                        className="flex items-center gap-2 px-6 py-2 bg-primary hover:bg-primary/90 disabled:bg-muted disabled:cursor-not-allowed rounded-md text-primary-foreground font-medium transition-colors"
                    >
                        {isRunning ? (
                            <>
                                <RefreshCw className="w-4 h-4 animate-spin" />
                                Running...
                            </>
                        ) : (
                            <>
                                <Play className="w-4 h-4" />
                                Run Benchmark
                            </>
                        )}
                    </button>

                    <label className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md cursor-pointer transition-colors">
                        <Upload className="w-4 h-4" />
                        <span className="text-sm">Upload Dataset</span>
                        <input
                            type="file"
                            accept=".json,.csv"
                            onChange={handleFileUpload}
                            className="hidden"
                        />
                    </label>
                </div>

                {/* Active Run Progress */}
                {isRunning && (
                    <div className="mt-6 w-full">
                        <div className="flex justify-between text-sm text-muted-foreground mb-2">
                            <span>Running benchmark...</span>
                            <span>{runs.find(r => r.status === 'running')?.metrics?.progress || 0}%</span>
                        </div>
                        <div className="w-full h-2 bg-secondary rounded-full overflow-hidden">
                            <div
                                className="h-full bg-primary transition-all duration-500 ease-in-out"
                                style={{ width: `${runs.find(r => r.status === 'running')?.metrics?.progress || 0}%` }}
                            />
                        </div>
                    </div>
                )}
            </div>

            {/* Recent Runs Table */}
            <div className="bg-card border rounded-lg overflow-hidden">
                <div className="px-6 py-4 border-b">
                    <h2 className="text-lg font-semibold">Recent Benchmark Runs</h2>
                </div>

                {runs.length === 0 ? (
                    <div className="p-8 text-center text-muted-foreground">
                        <BarChart3 className="w-12 h-12 mx-auto mb-4 opacity-50" />
                        <p>No benchmark runs yet. Upload a dataset and run your first benchmark!</p>
                    </div>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Status</TableHead>
                                <TableHead>Dataset</TableHead>
                                <TableHead>Faithfulness</TableHead>
                                <TableHead>Relevancy</TableHead>
                                <TableHead>Created</TableHead>
                                <TableHead className="w-[50px]"></TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {runs.map((run) => (
                                <TableRow key={run.id}>
                                    <TableCell>
                                        <div className="flex items-center gap-2">
                                            {getStatusIcon(run.status)}
                                            <span className="text-sm capitalize">{run.status}</span>
                                        </div>
                                    </TableCell>
                                    <TableCell className="font-medium">
                                        {run.dataset_name}
                                    </TableCell>
                                    <TableCell className="font-mono">
                                        {formatScore(run.metrics?.faithfulness ?? null)}
                                    </TableCell>
                                    <TableCell className="font-mono">
                                        {formatScore(run.metrics?.response_relevancy ?? null)}
                                    </TableCell>
                                    <TableCell className="text-muted-foreground">
                                        {new Date(run.created_at).toLocaleString()}
                                    </TableCell>
                                    <TableCell>
                                        <button
                                            onClick={() => handleDeleteRun(run.id)}
                                            className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-md transition-colors"
                                            title="Delete Run"
                                        >
                                            <Trash2 className="w-4 h-4" />
                                        </button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </div>
        </div >
    )
}

export default RagasSubPanel
