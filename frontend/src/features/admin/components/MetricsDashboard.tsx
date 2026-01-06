
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatCard } from '@/components/ui/StatCard';
import { maintenanceApi, SystemStats } from '@/lib/api-admin';
import { Activity, Database, Server, Zap } from 'lucide-react';

interface HealthDependency {
    status: 'healthy' | 'degraded' | 'down'
    latency_ms: number
}

interface SystemHealth {
    status: 'ready' | 'degraded' | 'down'
    dependencies: Record<string, HealthDependency>
    timestamp: string
}

export default function MetricsDashboard() {
    const [stats, setStats] = useState<SystemStats | null>(null);
    const [health, setHealth] = useState<SystemHealth | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [statsData, healthRes] = await Promise.all([
                    maintenanceApi.getStats(),
                    fetch('/api/health/ready').then(r => r.json())
                ]);
                setStats(statsData);
                setHealth(healthRes);
            } catch (err) {
                console.error('Failed to load metrics:', err);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
        // Refresh every 30s
        const interval = setInterval(fetchData, 30000);
        return () => clearInterval(interval);
    }, []);

    if (loading) {
        return <div className="animate-pulse space-y-4">
            <div className="h-32 bg-muted rounded-lg"></div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="h-32 bg-muted rounded-lg"></div>
                <div className="h-32 bg-muted rounded-lg"></div>
                <div className="h-32 bg-muted rounded-lg"></div>
            </div>
        </div>;
    }

    const isHealthy = health?.status === 'ready';

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <StatCard
                    icon={Activity}
                    label="System Status"
                    value={isHealthy ? 'Healthy' : 'Degraded'}
                    isString
                    description={isHealthy ? 'All systems operational' : 'Some services are down'}
                    className={isHealthy ? 'border-l-4 border-l-green-500' : 'border-l-4 border-l-red-500'}
                />
                <StatCard
                    icon={Database}
                    label="Knowledge Base"
                    value={stats?.database.documents_total || 0}
                    subLabel="Documents processed"
                />
                <StatCard
                    icon={Zap}
                    label="Vector Index"
                    value={stats?.vector_store.vectors_total || 0}
                    subLabel="Embeddings stored"
                />
                <StatCard
                    icon={Server}
                    label="Redis Cache"
                    value={`${stats?.cache.hit_rate || 0}%`}
                    isString
                    subLabel="Hit Rate"
                    trend={{ value: 2.5, isPositive: true }} // Mock trend
                />
            </div>

            {/* Detailed Health Grid */}
            <Card>
                <CardHeader>
                    <CardTitle className="text-sm font-medium">Service Health</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        {health?.dependencies && Object.entries(health.dependencies).map(([name, status]) => (
                            <div key={name} className="flex items-center justify-between p-3 border rounded-lg bg-muted/20">
                                <span className="capitalize font-medium text-sm">{name}</span>
                                <div className="flex items-center gap-2">
                                    <span className={`w-2 h-2 rounded-full ${status.status === 'healthy' ? 'bg-green-500' : 'bg-red-500'}`} />
                                    <span className="text-xs text-muted-foreground">{status.latency_ms ? `${status.latency_ms.toFixed(0)}ms` : '-'}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}
