/**
 * Ragas Benchmark Dashboard
 * =========================
 * 
 * Sub-panel for viewing and running Ragas evaluation benchmarks.
 */

import { useState, useEffect, useCallback } from 'react'
import { BarChart3, Play, RefreshCw, Upload, CheckCircle, XCircle, Clock, FileJson } from 'lucide-react'
import { ragasApi, RagasStats, RagasDataset, BenchmarkRunSummary } from '../../../lib/api-admin'

interface StatCardProps {
    label: string
    value: string | number
    icon: React.ReactNode
    trend?: 'up' | 'down' | 'neutral'
    color?: string
}

function StatCard({ label, value, icon, color = 'text-amber-400' }: StatCardProps) {
    return (
        <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg p-4">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-gray-400 text-sm">{label}</p>
                    <p className={`text-2xl font-semibold mt-1 ${color}`}>{value}</p>
                </div>
                <div className={`p-3 rounded-lg bg-gray-700/50 ${color}`}>
                    {icon}
                </div>
            </div>
        </div>
    )
}

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
                return <CheckCircle className="w-4 h-4 text-green-400" />
            case 'failed':
                return <XCircle className="w-4 h-4 text-red-400" />
            case 'running':
                return <RefreshCw className="w-4 h-4 text-amber-400 animate-spin" />
            default:
                return <Clock className="w-4 h-4 text-gray-400" />
        }
    }

    if (loading && !stats) {
        return (
            <div className="flex items-center justify-center h-64">
                <RefreshCw className="w-8 h-8 text-amber-400 animate-spin" />
            </div>
        )
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl font-semibold text-white">RAGAS Evaluation</h2>
                    <p className="text-gray-400 text-sm mt-1">
                        Systematic RAG quality benchmarking with Faithfulness and Relevancy metrics
                    </p>
                </div>
                <button
                    onClick={() => fetchData()}
                    className="p-2 rounded-lg bg-gray-700/50 hover:bg-gray-700 transition-colors"
                >
                    <RefreshCw className="w-5 h-5 text-gray-400" />
                </button>
            </div>

            {error && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400">
                    {error}
                </div>
            )}

            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard
                    label="Total Runs"
                    value={stats?.total_runs ?? 0}
                    icon={<BarChart3 className="w-5 h-5" />}
                />
                <StatCard
                    label="Completed"
                    value={stats?.completed_runs ?? 0}
                    icon={<CheckCircle className="w-5 h-5" />}
                    color="text-green-400"
                />
                <StatCard
                    label="Avg Faithfulness"
                    value={formatScore(stats?.avg_faithfulness ?? null)}
                    icon={<FileJson className="w-5 h-5" />}
                    color="text-blue-400"
                />
                <StatCard
                    label="Avg Relevancy"
                    value={formatScore(stats?.avg_relevancy ?? null)}
                    icon={<FileJson className="w-5 h-5" />}
                    color="text-purple-400"
                />
            </div>

            {/* Run Benchmark Section */}
            <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg p-6">
                <h3 className="text-lg font-medium text-white mb-4">Run Benchmark</h3>

                <div className="flex flex-wrap gap-4 items-end">
                    <div className="flex-1 min-w-[200px]">
                        <label className="block text-sm text-gray-400 mb-2">Dataset</label>
                        <select
                            value={selectedDataset}
                            onChange={(e) => setSelectedDataset(e.target.value)}
                            className="w-full bg-gray-700/50 border border-gray-600 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-amber-500"
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
                        className="flex items-center gap-2 px-6 py-2 bg-amber-600 hover:bg-amber-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg text-white font-medium transition-colors"
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

                    <label className="flex items-center gap-2 px-4 py-2 bg-gray-700/50 hover:bg-gray-700 rounded-lg cursor-pointer transition-colors">
                        <Upload className="w-4 h-4 text-gray-400" />
                        <span className="text-gray-300 text-sm">Upload Dataset</span>
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
            <div className="bg-gray-800/60 border border-gray-700/50 rounded-lg overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-700/50">
                    <h3 className="text-lg font-medium text-white">Recent Benchmark Runs</h3>
                </div>

                {runs.length === 0 ? (
                    <div className="p-8 text-center text-gray-400">
                        <BarChart3 className="w-12 h-12 mx-auto mb-4 opacity-50" />
                        <p>No benchmark runs yet. Upload a dataset and run your first benchmark!</p>
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-gray-700/30">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Status</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Dataset</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Faithfulness</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Relevancy</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Created</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-700/30">
                                {runs.map((run) => (
                                    <tr key={run.id} className="hover:bg-gray-700/20 transition-colors">
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex items-center gap-2">
                                                {getStatusIcon(run.status)}
                                                <span className="text-sm text-gray-300 capitalize">{run.status}</span>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                                            {run.dataset_name}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-blue-400">
                                            {formatScore(run.metrics?.faithfulness ?? null)}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-purple-400">
                                            {formatScore(run.metrics?.response_relevancy ?? null)}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-400">
                                            {new Date(run.created_at).toLocaleString()}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    )
}

export default RagasSubPanel
