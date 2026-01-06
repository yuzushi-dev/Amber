/**
 * Ragas Benchmark Dashboard
 * =========================
 *
 * Sub-panel for viewing and running Ragas evaluation benchmarks.
 */

import { useState, useEffect, useCallback } from 'react'
import { BarChart3, Play, RefreshCw, Upload, CheckCircle, XCircle, Clock, FileJson } from 'lucide-react'
import { ragasApi, RagasStats, RagasDataset, BenchmarkRunSummary } from '../../../lib/api-admin'
import { StatCard } from '@/components/ui/StatCard'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'

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
        return (
            <div className="flex items-center justify-center h-64">
                <RefreshCw className="w-8 h-8 text-primary animate-spin" />
            </div>
        )
    }

    return (
        <div className="p-6 pb-32 max-w-7xl mx-auto space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">RAGAS Evaluation</h1>
                    <p className="text-muted-foreground">
                        Systematic RAG quality benchmarking with Faithfulness and Relevancy metrics
                    </p>
                </div>
                <button
                    onClick={() => fetchData()}
                    disabled={loading}
                    className="flex items-center gap-2 px-4 py-2 bg-secondary hover:bg-secondary/80 rounded-md transition-colors disabled:opacity-50"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

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
                        <select
                            value={selectedDataset}
                            onChange={(e) => setSelectedDataset(e.target.value)}
                            className="w-full bg-background border border-input rounded-md px-4 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                            disabled={isRunning}
                        >
                            {datasets.length === 0 && (
                                <option value="">No datasets available</option>
                            )}
                            {datasets.map((ds) => (
                                <option key={ds.name} value={ds.name}>
                                    {ds.name} ({ds.sample_count} samples)
                                </option>
                            ))}
                        </select>
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
                            accept=".json"
                            onChange={handleFileUpload}
                            className="hidden"
                        />
                    </label>
                </div>
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
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </div>
        </div>
    )
}

export default RagasSubPanel
