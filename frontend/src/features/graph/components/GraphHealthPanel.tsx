import { useQuery } from '@tanstack/react-query'
import { Activity, AlertTriangle, GitBranch, Network, Loader2 } from 'lucide-react'

import { graphEditorApi, GraphHealth } from '@/lib/api-client'

interface GraphHealthPanelProps {
    className?: string
}

const fmtInt = (n: number) => n.toLocaleString()
const fmtFloat = (n: number) => n.toFixed(2)

export function GraphHealthPanel({ className }: GraphHealthPanelProps) {
    const { data, isLoading } = useQuery<GraphHealth>({
        queryKey: ['graph-health'],
        queryFn: graphEditorApi.getHealth,
        refetchInterval: 30000,
        staleTime: 15000,
    })

    if (isLoading || !data) {
        return (
            <div className={`p-4 rounded-xl bg-surface-950/80 backdrop-blur-md border border-white/5 shadow-xl ${className ?? ''}`}>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Loading health…
                </div>
            </div>
        )
    }

    const orphanRatio = data.total_nodes > 0
        ? data.orphan_nodes / data.total_nodes
        : 0

    const orphanSeverity = orphanRatio > 0.1
        ? 'text-destructive'
        : orphanRatio > 0.05
            ? 'text-warning'
            : 'text-muted-foreground'

    return (
        <div className={`p-4 rounded-xl bg-surface-950/80 backdrop-blur-md border border-white/5 shadow-xl space-y-3 ${className ?? ''}`}>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                <Activity className="w-3.5 h-3.5 text-primary" />
                Graph Health
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                <Metric icon={<Network className="w-3 h-3" />} label="Nodes" value={fmtInt(data.total_nodes)} />
                <Metric icon={<GitBranch className="w-3 h-3" />} label="Edges" value={fmtInt(data.total_edges)} />
                <Metric
                    icon={<AlertTriangle className={`w-3 h-3 ${orphanSeverity}`} />}
                    label="Orphans"
                    value={fmtInt(data.orphan_nodes)}
                    valueClass={orphanSeverity}
                />
                <Metric label="Communities" value={fmtInt(data.community_count)} />
                <Metric label="Avg degree" value={fmtFloat(data.avg_degree)} />
                <Metric label="Max degree" value={fmtInt(data.max_degree)} />
                <Metric label="Leaf nodes" value={fmtInt(data.leaf_nodes)} />
            </div>
        </div>
    )
}

interface MetricProps {
    icon?: React.ReactNode
    label: string
    value: string
    valueClass?: string
}

function Metric({ icon, label, value, valueClass }: MetricProps) {
    return (
        <div className="flex items-center justify-between gap-2 min-w-0">
            <span className="flex items-center gap-1 text-muted-foreground/80 truncate">
                {icon}
                {label}
            </span>
            <span className={`font-mono ${valueClass ?? 'text-primary'}`}>{value}</span>
        </div>
    )
}
