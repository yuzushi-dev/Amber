import React, { useState, useEffect } from 'react';
import { Database, ShieldCheck, ShieldAlert, Loader2, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

interface DBStatus {
    status: 'healthy' | 'needs_migration' | 'error';
    current_revision: string | null;
    head_revision: string | null;
    up_to_date: boolean;
    error?: string;
}

interface DatabaseSetupProps {
    onComplete: () => void;
    apiBaseUrl?: string;
}

export const DatabaseSetup: React.FC<DatabaseSetupProps> = ({ onComplete, apiBaseUrl = '' }) => {
    const [status, setStatus] = useState<DBStatus | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isMigrating, setIsMigrating] = useState(false);
    const [logs, setLogs] = useState<string[]>([]);
    const hasInitialized = React.useRef(false);

    const addLog = (msg: string) => setLogs(prev => [...prev, `> ${msg}`]);

    const checkStatus = async () => {
        try {
            const apiKey = localStorage.getItem('api_key') || '';
            const response = await fetch(`${apiBaseUrl}/api/v1/setup/db/status`, {
                headers: { 'X-API-Key': apiKey }
            });
            const data = await response.json();
            setStatus(data);
            setIsLoading(false);
        } catch (err) {
            setStatus({
                status: 'error',
                current_revision: null,
                head_revision: null,
                up_to_date: false,
                error: String(err)
            });
            setIsLoading(false);
        }
    };

    useEffect(() => {
        if (!hasInitialized.current) {
            hasInitialized.current = true;
            addLog('Checking system core integrity...');
            checkStatus();
        }
    }, []);

    const handleMigrate = async () => {
        setIsMigrating(true);
        addLog('Initiating database migration sequence...');

        try {
            // Artificial delay for better UX feeling
            await new Promise(r => setTimeout(r, 800));
            addLog('Applied Alembic configuration...');

            const apiKey = localStorage.getItem('api_key') || '';
            const response = await fetch(`${apiBaseUrl}/api/v1/setup/db/migrate`, {
                method: 'POST',
                headers: { 'X-API-Key': apiKey }
            });

            if (!response.ok) throw new Error('Migration failed');

            addLog('Migration applied successfully.');
            addLog('Verifying consistency...');
            await checkStatus();
            addLog('System core verification complete.');
        } catch (err) {
            addLog(`Error: ${String(err)}`);
            // Refresh status anyway to be sure
            checkStatus();
        } finally {
            setIsMigrating(false);
        }
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-muted-foreground">
                <Loader2 className="w-8 h-8 animate-spin mb-4 text-primary" />
                <div className="font-mono text-sm">Initializing System Core...</div>
            </div>
        );
    }

    const isHealthy = status?.status === 'healthy';

    return (
        <div className="flex flex-col h-full animate-in fade-in duration-500 bg-background/95">
            {/* Header */}
            <div className="p-6 border-b bg-muted/10">
                <div className="flex items-center gap-4">
                    <div className={`w-14 h-14 rounded-2xl flex items-center justify-center border-2 shadow-lg
                        ${isHealthy
                            ? 'bg-success-muted border-success/20 text-success shadow-[0_0_10px_hsl(var(--success)/0.1)]'
                            : 'bg-warning-muted border-warning/20 text-warning shadow-glow-warning'
                        }`}
                    >
                        <Database className="w-7 h-7" />
                    </div>
                    <div>
                        <h2 className="text-xl font-bold tracking-tight text-foreground">System Core Initialization</h2>
                        <div className="flex items-center gap-2 mt-1.5">
                            <Badge
                                variant="outline"
                                className={`font-mono text-[10px] uppercase tracking-wider border-none px-2 py-0.5
                                    ${isHealthy
                                        ? 'bg-success-muted text-success'
                                        : 'bg-warning-muted text-warning'
                                    }`}
                            >
                                {isHealthy ? 'Operational' : 'Maintenance Required'}
                            </Badge>
                            <span className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest opacity-70">
                                REV: {status?.current_revision?.substring(0, 7) || 'UNKNOWN'}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 p-6 space-y-6 overflow-y-auto">
                <div className={`rounded-xl border p-4 transition-colors ${isHealthy
                    ? 'border-success/20 bg-success-muted/50'
                    : 'border-warning/20 bg-warning-muted/50'
                    }`}>
                    <div className="flex gap-4">
                        <div className={`mt-0.5 ${isHealthy ? 'text-success' : 'text-warning'}`}>
                            {isHealthy ? <ShieldCheck className="w-5 h-5" /> : <ShieldAlert className="w-5 h-5" />}
                        </div>
                        <div className="space-y-1">
                            <h4 className={`font-medium tracking-tight ${isHealthy ? 'text-success' : 'text-warning'}`}>
                                {isHealthy ? 'System Core Synchronized' : 'Schema Update Required'}
                            </h4>
                            <p className="text-sm text-muted-foreground leading-relaxed">
                                {isHealthy
                                    ? 'The database schema matches the application version. You are ready to proceed.'
                                    : 'The database schema is outdated. Run the migration wizard to align the system core.'
                                }
                            </p>
                        </div>
                    </div>
                </div>

                {/* Terminal View */}
                <div className="bg-surface-950 rounded-lg border border-white/5 p-4 font-mono text-xs shadow-2xl relative overflow-hidden group">
                    {/* Scanline effect */}
                    <div className="absolute inset-0 bg-[linear-gradient(hsl(var(--surface-950)/0)_50%,hsl(var(--surface-950)/0.25)_50%),linear-gradient(90deg,hsl(var(--chart-1)/0.06),hsl(var(--chart-2)/0.02),hsl(var(--chart-3)/0.06))] z-[1] bg-[length:100%_2px,3px_100%] pointer-events-none opacity-20" />

                    <div className="flex items-center justify-between border-b border-white/5 pb-3 mb-3 relative z-10">
                        <span className="text-muted-foreground/60 flex items-center gap-2 select-none">
                            <span className="text-muted-foreground/40">{'>_'}</span>
                            system_log
                        </span>
                        <div className="flex gap-1.5 opacity-50 group-hover:opacity-100 transition-opacity">
                            <div className="w-2.5 h-2.5 rounded-full bg-destructive/40" />
                            <div className="w-2.5 h-2.5 rounded-full bg-warning/40" />
                            <div className="w-2.5 h-2.5 rounded-full bg-success/40" />
                        </div>
                    </div>
                    <div className="space-y-1.5 h-36 overflow-y-auto custom-scrollbar relative z-10 font-medium">
                        {logs.map((log, i) => (
                            <div key={i} className="text-success/90 flex gap-2">
                                <span className="opacity-50 select-none">{'>>'}</span>
                                {log.startsWith('>') ? log.substring(2) : log}
                            </div>
                        ))}
                        {isMigrating && (
                            <div className="flex items-center gap-2 text-success/90">
                                <span className="opacity-50 select-none">{'>>'}</span>
                                <span className="animate-pulse">_</span>
                            </div>
                        )}
                        {!isMigrating && logs.length === 0 && (
                            <div className="flex items-center gap-2 text-success/30">
                                <span className="opacity-30 select-none">{'>>'}</span>
                                <span className="animate-pulse">_</span>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Footer */}
            <div className="p-6 border-t bg-muted/10 flex justify-end gap-3">
                {isHealthy ? (
                    <Button onClick={onComplete} className="gap-2 px-8 font-medium" size="lg">
                        Proceed to Feature Setup
                        <ChevronRight className="w-4 h-4 text-primary-foreground/70" />
                    </Button>
                ) : (
                    <Button
                        onClick={handleMigrate}
                        disabled={isMigrating}
                        className="gap-2 px-8 bg-warning text-warning-foreground font-medium min-w-[200px] shadow-glow-warning hover:bg-warning/90"
                        size="lg"
                    >
                        {isMigrating ? (
                            <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                <span className="animate-pulse">Patching Core...</span>
                            </>
                        ) : (
                            <>
                                <Database className="w-4 h-4" />
                                Initialize Database
                            </>
                        )}
                    </Button>
                )}
            </div>
        </div>
    );
};
