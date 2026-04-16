/**
 * Token Metrics Page
 * ==================
 *
 * Cross-tenant LLM usage analytics. Super admins see all tenants
 * and can filter; regular admins see only their own tenant.
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
    Zap,
    PlugZap,
    Euro,
    MessageSquare,
    Calculator,
    RefreshCw,
    Filter,
    Building2,
} from 'lucide-react'
import {
    usageMetricsApi,
    tenantsApi,
    maintenanceApi,
    type UsageMetricsResponse,
    type QueryMetrics,
    type Tenant,
} from '@/lib/api-admin'
import { useAuth } from '@/features/auth'
import { Button } from '@/components/ui/button'
import { StatCard } from '@/components/ui/StatCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import RecentActivityTable from '../components/RecentActivityTable'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '@/features/admin/components/PageSkeleton'

const OPERATIONS = [
    { value: 'all', label: 'All operations' },
    { value: 'generation', label: 'Generation' },
    { value: 'embedding', label: 'Embedding' },
]

const DATE_PRESETS = [
    { value: 'all', label: 'All time' },
    { value: '1d',  label: 'Last 24h' },
    { value: '7d',  label: 'Last 7 days' },
    { value: '30d', label: 'Last 30 days' },
    { value: '90d', label: 'Last 90 days' },
]

function datePresetToRange(preset: string): { start_date?: string; end_date?: string } {
    if (preset === 'all') return {}
    const days = parseInt(preset)
    const end = new Date()
    const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000)
    return { start_date: start.toISOString(), end_date: end.toISOString() }
}

function formatTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
    return n.toString()
}

function formatCurrency(usd: number): string {
    const eur = usd * 0.92
    return new Intl.NumberFormat('en-DE', {
        style: 'currency',
        currency: 'EUR',
        minimumFractionDigits: 4,
        maximumFractionDigits: 4,
    }).format(eur)
}

export default function TokenMetricsPage() {
    const { isSuperAdmin } = useAuth()

    const [data, setData] = useState<UsageMetricsResponse | null>(null)
    const [recentActivity, setRecentActivity] = useState<QueryMetrics[]>([])
    const [tenants, setTenants] = useState<Tenant[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    // Filters
    const [selectedTenant, setSelectedTenant] = useState<string>('all')
    const [selectedOperation, setSelectedOperation] = useState<string>('all')
    const [selectedDatePreset, setSelectedDatePreset] = useState<string>('30d')

    const fetchData = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const dateRange = datePresetToRange(selectedDatePreset)
            const tenantFilter = selectedTenant !== 'all' ? selectedTenant : undefined
            const [metricsData, recentData, tenantList] = await Promise.all([
                usageMetricsApi.getTokenUsage({
                    tenant_id: tenantFilter,
                    operation: selectedOperation !== 'all' ? selectedOperation : undefined,
                    ...dateRange,
                }),
                maintenanceApi.getQueryMetrics(50, tenantFilter),
                isSuperAdmin ? tenantsApi.list() : Promise.resolve([]),
            ])
            setData(metricsData)
            setRecentActivity(recentData)
            setTenants(tenantList)
        } catch (err) {
            setError('Failed to load usage metrics.')
            console.error(err)
        } finally {
            setLoading(false)
        }
    }, [selectedTenant, selectedOperation, selectedDatePreset, isSuperAdmin])

    useEffect(() => { fetchData() }, [fetchData])

    const totals = data?.totals
    const tenantRows = data?.tenants ?? []
    const avgTokensPerCall = totals && totals.call_count > 0
        ? Math.round(totals.total_tokens / totals.call_count)
        : 0
    const maxTokens = useMemo(
        () => Math.max(...tenantRows.map(r => r.total_tokens), 1),
        [tenantRows],
    )

    if (loading && !data) return <PageSkeleton />

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="Token Usage & Costs"
                description={
                    isSuperAdmin
                        ? 'LLM usage aggregated across all tenants.'
                        : 'LLM usage for your tenant.'
                }
                actions={
                    <Button variant="secondary" onClick={fetchData} disabled={loading} className="gap-2">
                        <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                        Refresh
                    </Button>
                }
            />

            {error && (
                <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4">
                    <p className="text-destructive text-sm">{error}</p>
                </div>
            )}

            {/* Filters — super admin only */}
            {isSuperAdmin && (
                <Card>
                    <CardHeader className="pb-3">
                        <CardTitle className="text-sm font-medium flex items-center gap-2">
                            <Filter className="w-4 h-4 text-muted-foreground" />
                            Filters
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="flex flex-wrap gap-4">
                            <div className="flex flex-col gap-1 min-w-52">
                                <span className="text-xs text-muted-foreground">Tenant</span>
                                <Select value={selectedTenant} onValueChange={setSelectedTenant}>
                                    <SelectTrigger>
                                        <SelectValue placeholder="All tenants" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="all">All tenants</SelectItem>
                                        {tenants.map(t => (
                                            <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>

                            <div className="flex flex-col gap-1 min-w-48">
                                <span className="text-xs text-muted-foreground">Operation</span>
                                <Select value={selectedOperation} onValueChange={setSelectedOperation}>
                                    <SelectTrigger><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                        {OPERATIONS.map(op => (
                                            <SelectItem key={op.value} value={op.value}>{op.label}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>

                            <div className="flex flex-col gap-1 min-w-44">
                                <span className="text-xs text-muted-foreground">Period</span>
                                <Select value={selectedDatePreset} onValueChange={setSelectedDatePreset}>
                                    <SelectTrigger><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                        {DATE_PRESETS.map(p => (
                                            <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Summary Stats */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <StatCard icon={Zap} label="Total Tokens"
                    value={formatTokens(totals?.total_tokens ?? 0)} isString
                    subLabel={`${formatTokens(totals?.input_tokens ?? 0)} in · ${formatTokens(totals?.output_tokens ?? 0)} out`}
                    color="amber" delay={0.1} />
                <StatCard icon={Euro} label="Estimated Cost"
                    value={formatCurrency(totals?.cost ?? 0)} isString
                    subLabel={`$${(totals?.cost ?? 0).toFixed(4)} USD`}
                    color="green" delay={0.2} />
                <StatCard icon={MessageSquare} label="Total Calls"
                    value={totals?.call_count ?? 0}
                    subLabel={isSuperAdmin ? `${tenantRows.length} active tenants` : 'Total requests'}
                    color="blue" delay={0.3} />
                <StatCard icon={Calculator} label="Avg Tokens / Call"
                    value={formatTokens(avgTokensPerCall)} isString
                    subLabel="Average per request"
                    color="purple" delay={0.4} />
            </div>

            {/* Per-tenant breakdown — super admin only */}
            {isSuperAdmin && (
                <Card>
                    <CardHeader>
                        <CardTitle className="text-lg flex items-center gap-2">
                            <Building2 className="w-5 h-5 text-muted-foreground" />
                            Usage by Tenant
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {tenantRows.length === 0 ? (
                            <p className="text-muted-foreground text-sm">
                                No data for the selected filters.
                            </p>
                        ) : (
                            <div className="space-y-4">
                                {tenantRows.map(row => (
                                    <div key={row.tenant_id} className="space-y-1.5">
                                        <div className="flex items-center justify-between text-sm">
                                            <div className="flex items-center gap-2">
                                                <span className="font-medium">
                                                    {row.tenant_name ?? row.tenant_id.slice(0, 16)}
                                                </span>
                                                {!row.tenant_name && (
                                                    <span className="text-xs text-muted-foreground font-mono">
                                                        {row.tenant_id.slice(0, 8)}…
                                                    </span>
                                                )}
                                            </div>
                                            <span className="text-muted-foreground tabular-nums">
                                                {formatTokens(row.total_tokens)} tokens
                                            </span>
                                        </div>
                                        <div className="h-2 bg-muted rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-primary rounded-full transition-[width] duration-500 ease-out"
                                                style={{ width: `${(row.total_tokens / maxTokens) * 100}%` }}
                                            />
                                        </div>
                                        <div className="flex justify-between text-xs text-muted-foreground">
                                            <span>{row.call_count.toLocaleString()} calls</span>
                                            <span>
                                                {formatTokens(row.input_tokens)} in ·{' '}
                                                {formatTokens(row.output_tokens)} out
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </CardContent>
                </Card>
            )}

            {/* Recent chat activity with per-query token counts */}
            <div>
                <div className="flex items-center gap-2 mb-4">
                    <PlugZap size={18} className="text-primary" />
                    <h3 className="text-lg font-bold">Recent Chat Activity</h3>
                    <span className="text-xs text-muted-foreground ml-1">
                        — token counts from recent sessions (Redis, last ~24h)
                    </span>
                </div>
                <RecentActivityTable records={recentActivity} isLoading={loading} />
            </div>
        </div>
    )
}
