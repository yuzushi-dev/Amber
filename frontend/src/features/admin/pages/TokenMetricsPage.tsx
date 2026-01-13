/**
 * Token Metrics Page
 * ==================
 * 
 * Dashboard for viewing LLM token usage and costs.
 * Aggregates data from chat history API.
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
    Zap,
    ChessPawn,
    PlugZap,
    Euro,
    MessageSquare,
    Calculator,
    RefreshCw,
    ChessQueen
} from 'lucide-react'
import { chatHistoryApi, ChatHistoryItem, maintenanceApi, QueryMetrics } from '@/lib/api-admin'
import { Button } from '@/components/ui/button'
import { StatCard } from '@/components/ui/StatCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import RecentActivityTable from '../components/RecentActivityTable'

interface TokenMetrics {
    totalTokens: number
    totalCost: number
    conversationCount: number
    avgTokensPerQuery: number
    byModel: Record<string, { tokens: number; cost: number; count: number }>
    byProvider: Record<string, { tokens: number; cost: number; count: number }>
}

export default function TokenMetricsPage() {
    const [conversations, setConversations] = useState<ChatHistoryItem[]>([])
    const [recentActivity, setRecentActivity] = useState<QueryMetrics[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const fetchData = useCallback(async () => {
        try {
            setLoading(true)
            const [convData, queryData] = await Promise.all([
                chatHistoryApi.list({ limit: 100 }),
                maintenanceApi.getQueryMetrics(50)
            ])
            setConversations(convData.conversations)
            setRecentActivity(queryData)
            setError(null)
        } catch (err) {
            setError('Failed to load token metrics')
            console.error(err)
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchData()
    }, [fetchData])

    // Aggregate metrics from QueryMetrics (recentActivity) for accurate data
    const metrics: TokenMetrics = useMemo(() => {
        const byModel: Record<string, { tokens: number; cost: number; count: number }> = {}
        const byProvider: Record<string, { tokens: number; cost: number; count: number }> = {}
        let totalTokens = 0
        let totalCost = 0

        for (const query of recentActivity) {
            totalTokens += query.tokens_used || 0
            totalCost += query.cost_estimate || 0

            // By model
            const model = query.model || 'unknown'
            if (!byModel[model]) {
                byModel[model] = { tokens: 0, cost: 0, count: 0 }
            }
            byModel[model].tokens += query.tokens_used || 0
            byModel[model].cost += query.cost_estimate || 0
            byModel[model].count += 1

            // By provider
            const provider = query.provider || 'unknown'
            if (!byProvider[provider]) {
                byProvider[provider] = { tokens: 0, cost: 0, count: 0 }
            }
            byProvider[provider].tokens += query.tokens_used || 0
            byProvider[provider].cost += query.cost_estimate || 0
            byProvider[provider].count += 1
        }

        return {
            totalTokens,
            totalCost,
            conversationCount: recentActivity.length,
            avgTokensPerQuery: recentActivity.length > 0
                ? Math.round(totalTokens / recentActivity.length)
                : 0,
            byModel,
            byProvider,
        }
    }, [recentActivity])

    const formatCurrency = (value: number) => {
        // Convert USD to EUR (approximate rate)
        const eurValue = value * 0.92
        return new Intl.NumberFormat('de-DE', {
            style: 'currency',
            currency: 'EUR',
            minimumFractionDigits: 4,
            maximumFractionDigits: 4,
        }).format(eurValue)
    }

    const formatNumber = (value: number) => {
        return new Intl.NumberFormat('en-US').format(value)
    }

    if (loading && conversations.length === 0) {
        return (
            <div className="p-6 pb-32 max-w-7xl mx-auto">
                <div className="animate-pulse space-y-6">
                    <div className="h-8 w-48 bg-muted rounded"></div>
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                        {[1, 2, 3, 4].map(i => (
                            <div key={i} className="h-32 bg-muted rounded-lg"></div>
                        ))}
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="p-6 pb-16 max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">Token Usage & Costs</h1>
                    <p className="text-muted-foreground">
                        LLM usage analytics from recent conversations
                    </p>
                </div>
                <Button
                    variant="secondary"
                    onClick={fetchData}
                    disabled={loading}
                    className="gap-2"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </Button>
            </div>

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-6">
                    <p className="text-red-800 dark:text-red-400">{error}</p>
                </div>
            )}

            {/* Summary Stats */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
                <StatCard
                    icon={Zap}
                    label="Total Tokens"
                    value={formatNumber(metrics.totalTokens)}
                    isString
                    subLabel="Input + Output"
                />
                <StatCard
                    icon={Euro}
                    label="Total Cost"
                    value={formatCurrency(metrics.totalCost)}
                    isString
                    subLabel={`Estimated EUR • $${metrics.totalCost.toFixed(4)} USD`}
                />
                <StatCard
                    icon={MessageSquare}
                    label="Conversations"
                    value={metrics.conversationCount}
                    subLabel="Total queries"
                />
                <StatCard
                    icon={Calculator}
                    label="Avg Tokens/Query"
                    value={formatNumber(metrics.avgTokensPerQuery)}
                    isString
                    subLabel="Per conversation"
                />
            </div>

            {/* Breakdown Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
                {/* By Provider */}
                <Card>
                    <CardHeader>
                        <CardTitle className="text-lg flex items-center gap-2">
                            Usage by Provider
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {Object.keys(metrics.byProvider).length === 0 ? (
                            <p className="text-muted-foreground text-sm">No data available</p>
                        ) : (
                            <div className="space-y-4">
                                {Object.entries(metrics.byProvider)
                                    .filter(([, data]) => data.tokens > 0)
                                    .sort((a, b) => b[1].tokens - a[1].tokens)
                                    .map(([provider, data]) => (
                                        <div key={provider} className="space-y-2">
                                            <div className="flex items-center justify-between text-sm">
                                                <span className="font-medium capitalize">{provider}</span>
                                                <span className="text-muted-foreground">
                                                    {formatNumber(data.tokens)} tokens
                                                </span>
                                            </div>
                                            <div className="h-2 bg-muted rounded-full overflow-hidden">
                                                <div
                                                    className="h-full bg-primary rounded-full transition-all"
                                                    style={{
                                                        width: `${(data.tokens / metrics.totalTokens) * 100}%`
                                                    }}
                                                />
                                            </div>
                                            <div className="flex justify-between text-xs text-muted-foreground">
                                                <span>{data.count} queries</span>
                                                <span>{formatCurrency(data.cost)}</span>
                                            </div>
                                        </div>
                                    ))}
                            </div>
                        )}
                    </CardContent>
                </Card>

                {/* By Model */}
                <Card>
                    <CardHeader>
                        <CardTitle className="text-lg flex items-center gap-2">
                            Usage by Model
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {Object.keys(metrics.byModel).length === 0 ? (
                            <p className="text-muted-foreground text-sm">No data available</p>
                        ) : (
                            <div className="space-y-4">
                                {Object.entries(metrics.byModel)
                                    .filter(([, data]) => data.tokens > 0)
                                    .sort((a, b) => b[1].tokens - a[1].tokens)
                                    .map(([model, data]) => (
                                        <div key={model} className="space-y-2">
                                            <div className="flex items-center justify-between text-sm">
                                                <span className="font-medium font-mono text-xs">{model}</span>
                                                <span className="text-muted-foreground">
                                                    {formatNumber(data.tokens)} tokens
                                                </span>
                                            </div>
                                            <div className="h-2 bg-muted rounded-full overflow-hidden">
                                                <div
                                                    className="h-full bg-accent-500 rounded-full transition-all"
                                                    style={{
                                                        width: `${(data.tokens / metrics.totalTokens) * 100}%`
                                                    }}
                                                />
                                            </div>
                                            <div className="flex justify-between text-xs text-muted-foreground">
                                                <span>{data.count} queries</span>
                                                <span>{formatCurrency(data.cost)}</span>
                                            </div>
                                        </div>
                                    ))}
                            </div>
                        )}
                    </CardContent>
                </Card>
            </div>

            {/* Recent Activity */}
            <div>
                <div className="flex items-center gap-2 mb-4">
                    <PlugZap size={18} className="text-primary" />
                    <h3 className="text-lg font-bold">Recent Activity</h3>
                </div>
                <div>
                    <RecentActivityTable records={recentActivity} isLoading={loading} />
                </div>
            </div>
        </div>
    )
}
