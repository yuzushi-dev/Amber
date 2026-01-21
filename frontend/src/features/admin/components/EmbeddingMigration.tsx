import { useState, useEffect, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2, RefreshCw, CheckCircle, XCircle, StopCircle, Clock, FileText } from 'lucide-react'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { embeddingsApi, EmbeddingStatus, MigrationResult, MigrationStatusResponse } from '@/lib/api-admin'

interface EmbeddingMigrationProps {
    autoMigrate?: boolean
    tenantId?: string
    onMigrationComplete?: () => void
}

export function EmbeddingMigration({ autoMigrate = false, tenantId, onMigrationComplete }: EmbeddingMigrationProps) {
    const queryClient = useQueryClient()
    const [statuses, setStatuses] = useState<EmbeddingStatus[]>([])
    const [loading, setLoading] = useState(true)
    const [migrationOpen, setMigrationOpen] = useState(false)
    const [selectedTenant, setSelectedTenant] = useState<EmbeddingStatus | null>(null)
    const [confirmText, setConfirmText] = useState('')
    const [migrating, setMigrating] = useState(false)
    const [result, setResult] = useState<MigrationResult | null>(null)
    const [error, setError] = useState<string | null>(null)

    // Progress tracking state
    const [progressStatus, setProgressStatus] = useState<MigrationStatusResponse | null>(null)
    const [showProgressDialog, setShowProgressDialog] = useState(false)
    const [cancelConfirmOpen, setCancelConfirmOpen] = useState(false)

    const pollingRef = useRef<NodeJS.Timeout | null>(null)
    const autoMigrateTriggered = useRef(false)
    const [elapsedTime, setElapsedTime] = useState(0)
    const timerRef = useRef<NodeJS.Timeout | null>(null)
    const startTimeRef = useRef<number | null>(null)

    useEffect(() => {
        checkStatus()
        return () => {
            if (pollingRef.current) clearInterval(pollingRef.current)
            if (timerRef.current) clearInterval(timerRef.current)
        }
    }, [])

    // Elapsed time timer
    useEffect(() => {
        if (showProgressDialog && progressStatus?.status === 'running') {
            if (!startTimeRef.current) {
                startTimeRef.current = Date.now()
            }
            timerRef.current = setInterval(() => {
                if (startTimeRef.current) {
                    setElapsedTime(Math.floor((Date.now() - startTimeRef.current) / 1000))
                }
            }, 1000)
        } else if (progressStatus?.status !== 'running' && timerRef.current) {
            clearInterval(timerRef.current)
            timerRef.current = null
        }

        return () => {
            if (timerRef.current) clearInterval(timerRef.current)
        }
    }, [showProgressDialog, progressStatus?.status])

    const formatElapsedTime = (seconds: number) => {
        const mins = Math.floor(seconds / 60)
        const secs = seconds % 60
        return `${mins}:${secs.toString().padStart(2, '0')}`
    }

    // Auto-migrate handling
    useEffect(() => {
        if (autoMigrate && tenantId && !autoMigrateTriggered.current && statuses.length > 0) {
            autoMigrateTriggered.current = true
            // Find the tenant and start migration automatically
            const tenant = statuses.find(s => s.tenant_id === tenantId)
            if (tenant) {
                startAutoMigration(tenant)
            }
        }
    }, [autoMigrate, tenantId, statuses])

    const checkStatus = async () => {
        try {
            setLoading(true)
            const data = await embeddingsApi.checkCompatibility()
            setStatuses(data)
        } catch (error) {
            console.error("Failed to check embedding status", error)
        } finally {
            setLoading(false)
        }
    }

    const startProgressPolling = useCallback((tid: string) => {
        if (pollingRef.current) clearInterval(pollingRef.current)

        pollingRef.current = setInterval(async () => {
            try {
                const status = await embeddingsApi.getMigrationStatus(tid)
                setProgressStatus(status)

                if (status.status === 'complete' || status.status === 'failed' || status.status === 'cancelled') {
                    if (pollingRef.current) clearInterval(pollingRef.current)
                    pollingRef.current = null

                    if (status.status === 'complete') {
                        checkStatus()
                        // Invalidate all document-related queries so they refresh on next view
                        queryClient.invalidateQueries({ queryKey: ['documents'] })
                        queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] })
                        onMigrationComplete?.()
                    }
                }
            } catch (err) {
                console.error('Failed to poll migration status:', err)
            }
        }, 2000) // Poll every 2 seconds
    }, [onMigrationComplete])

    const handleMigrateClick = (status: EmbeddingStatus) => {
        setSelectedTenant(status)
        setConfirmText('')
        setResult(null)
        setError(null)
        setMigrationOpen(true)
    }

    const startAutoMigration = async (tenant: EmbeddingStatus) => {
        setSelectedTenant(tenant)
        setShowProgressDialog(true)
        setElapsedTime(0)
        startTimeRef.current = Date.now()
        setProgressStatus({
            status: 'running',
            phase: 'preparing',
            progress: 0,
            message: 'Starting migration...'
        })

        try {
            setMigrating(true)
            const res = await embeddingsApi.migrateTenant(tenant.tenant_id)
            setResult(res)
            startProgressPolling(tenant.tenant_id)
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error occurred")
            setProgressStatus({
                status: 'failed',
                phase: 'error',
                progress: 0,
                message: err instanceof Error ? err.message : 'Migration failed'
            })
        } finally {
            setMigrating(false)
        }
    }

    const handleConfirmMigration = async () => {
        if (!selectedTenant) return

        setShowProgressDialog(true)
        setMigrationOpen(false)
        setElapsedTime(0)
        startTimeRef.current = Date.now()
        setProgressStatus({
            status: 'running',
            phase: 'preparing',
            progress: 0,
            message: 'Starting migration...'
        })

        try {
            setMigrating(true)
            setError(null)
            const res = await embeddingsApi.migrateTenant(selectedTenant.tenant_id)
            setResult(res)
            startProgressPolling(selectedTenant.tenant_id)
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error occurred")
            setProgressStatus({
                status: 'failed',
                phase: 'error',
                progress: 0,
                message: err instanceof Error ? err.message : 'Migration failed'
            })
        } finally {
            setMigrating(false)
        }
    }

    const handleCancelMigration = async () => {
        if (!selectedTenant) return

        try {
            await embeddingsApi.cancelMigration(selectedTenant.tenant_id)
            if (pollingRef.current) clearInterval(pollingRef.current)
            setProgressStatus({
                status: 'cancelled',
                phase: 'cancelled',
                progress: progressStatus?.progress || 0,
                message: 'Migration cancelled by user'
            })
        } catch (err) {
            console.error('Failed to cancel migration:', err)
        }
        setCancelConfirmOpen(false)
    }

    const handleCloseProgress = () => {
        setShowProgressDialog(false)
        setProgressStatus(null)
        setResult(null)
        setError(null)
        if (pollingRef.current) clearInterval(pollingRef.current)
    }

    const handleClose = () => {
        setMigrationOpen(false)
        setResult(null)
        setError(null)
    }

    const incompatibleTenants = statuses.filter(s => !s.is_compatible)

    // Show progress dialog if active (from auto-migrate or manual)
    if (showProgressDialog && progressStatus) {
        return (
            <div className="mb-8">
                <Dialog open={showProgressDialog} onOpenChange={() => { }}>
                    <DialogContent className="bg-zinc-950 border-white/10 shadow-2xl p-0 gap-0 overflow-hidden sm:max-w-lg">
                        <DialogHeader className="p-6 border-b border-white/5 bg-white/[0.02]">
                            <DialogTitle className="font-display tracking-tight text-lg flex items-center gap-3">
                                <div className={`p-2 rounded-lg ${progressStatus.status === 'complete' ? 'bg-green-500/10' :
                                    progressStatus.status === 'failed' || progressStatus.status === 'cancelled' ? 'bg-red-500/10' :
                                        'bg-amber-500/10'
                                    }`}>
                                    {progressStatus.status === 'running' && <Loader2 className="h-5 w-5 text-amber-500 animate-spin" />}
                                    {progressStatus.status === 'complete' && <CheckCircle className="h-5 w-5 text-green-500" />}
                                    {(progressStatus.status === 'failed' || progressStatus.status === 'cancelled') && <AlertTriangle className="h-5 w-5 text-red-500" />}
                                </div>
                                {progressStatus.status === 'complete' ? 'Migration Complete' :
                                    progressStatus.status === 'failed' ? 'Migration Failed' :
                                        progressStatus.status === 'cancelled' ? 'Migration Cancelled' :
                                            'Migration in Progress'}
                            </DialogTitle>
                        </DialogHeader>

                        <div className="p-6 space-y-5">
                            {/* Progress Bar */}
                            <div className="space-y-2">
                                <div className="flex justify-between text-sm">
                                    <span className="text-muted-foreground capitalize">{progressStatus.phase.replace('_', ' ')}</span>
                                    <span className="font-mono font-medium">{progressStatus.progress}%</span>
                                </div>
                                <div className="relative h-2 w-full overflow-hidden rounded-full bg-muted/20">
                                    <div
                                        className={`absolute inset-y-0 left-0 transition-all duration-300 ease-out rounded-full ${progressStatus.status === 'complete' ? 'bg-green-500' :
                                            progressStatus.status === 'failed' ? 'bg-red-500' :
                                                'bg-primary'
                                            }`}
                                        style={{ width: `${progressStatus.progress}%` }}
                                    />
                                </div>
                            </div>

                            {/* Status Message */}
                            <div className={`p-4 rounded-lg border ${progressStatus.status === 'complete' ? 'bg-green-500/5 border-green-500/10 text-green-500' :
                                progressStatus.status === 'failed' ? 'bg-red-500/5 border-red-500/10 text-red-500' :
                                    progressStatus.status === 'cancelled' ? 'bg-muted/10 border-white/5 text-muted-foreground' :
                                        'bg-primary/5 border-primary/10 text-primary'
                                }`}>
                                <p className="text-sm">{progressStatus.message}</p>
                            </div>

                            {/* Current Document */}
                            {progressStatus.status === 'running' && progressStatus.current_document && (
                                <div className="flex items-center justify-between p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
                                    <span className="text-sm text-blue-400 flex items-center gap-2">
                                        <FileText className="h-3.5 w-3.5" />
                                        Processing
                                    </span>
                                    <span className="font-mono font-medium text-foreground text-sm truncate max-w-[200px]" title={progressStatus.current_document}>
                                        {progressStatus.current_document}
                                    </span>
                                </div>
                            )}

                            {/* Document Progress */}
                            {progressStatus.total_docs && progressStatus.total_docs > 0 && (
                                <div className="flex items-center justify-between p-3 rounded-lg bg-muted/10 border border-white/5">
                                    <span className="text-sm text-muted-foreground">Documents processed</span>
                                    <span className="font-mono font-medium text-foreground">
                                        {progressStatus.completed_docs || 0} / {progressStatus.total_docs}
                                    </span>
                                </div>
                            )}

                            {/* Elapsed Time */}
                            <div className="flex items-center justify-between p-3 rounded-lg bg-muted/10 border border-white/5">
                                <span className="text-sm text-muted-foreground flex items-center gap-2">
                                    <Clock className="h-3.5 w-3.5" />
                                    Elapsed time
                                </span>
                                <span className="font-mono font-medium text-foreground">
                                    {formatElapsedTime(elapsedTime)}
                                </span>
                            </div>

                            {/* Success Summary */}
                            {progressStatus.status === 'complete' && result && (
                                <div className="p-4 rounded-lg bg-green-500/5 border border-green-500/10 space-y-3">
                                    <p className="text-sm font-medium text-green-500">Migration Summary</p>
                                    <div className="grid grid-cols-3 gap-3 text-center">
                                        <div className="p-2 rounded bg-green-500/5">
                                            <div className="text-xs text-muted-foreground mb-1">Chunks Deleted</div>
                                            <div className="text-lg font-bold text-foreground">{result.chunks_deleted}</div>
                                        </div>
                                        <div className="p-2 rounded bg-green-500/5">
                                            <div className="text-xs text-muted-foreground mb-1">Docs Queued</div>
                                            <div className="text-lg font-bold text-foreground">{result.docs_queued}</div>
                                        </div>
                                        <div className="p-2 rounded bg-green-500/5">
                                            <div className="text-xs text-muted-foreground mb-1">New Model</div>
                                            <div className="text-sm font-medium text-foreground truncate">{result.new_model}</div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>

                        <DialogFooter className="p-4 bg-muted/5 border-t border-white/5 gap-3">
                            {progressStatus.status === 'running' ? (
                                <Button
                                    variant="ghost"
                                    onClick={() => setCancelConfirmOpen(true)}
                                    className="text-red-500 hover:text-red-400 hover:bg-red-500/10"
                                >
                                    <StopCircle className="w-4 h-4 mr-2" />
                                    Cancel Migration
                                </Button>
                            ) : (
                                <Button
                                    onClick={handleCloseProgress}
                                    className="bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/20"
                                >
                                    Close
                                </Button>
                            )}
                        </DialogFooter>
                    </DialogContent>
                </Dialog>

                {/* Cancel Confirmation Dialog */}
                <Dialog open={cancelConfirmOpen} onOpenChange={setCancelConfirmOpen}>
                    <DialogContent className="bg-zinc-950 border-white/10 shadow-2xl p-0 gap-0 overflow-hidden sm:max-w-sm">
                        <DialogHeader className="p-6 border-b border-white/5 bg-white/[0.02]">
                            <DialogTitle className="font-display tracking-tight text-lg flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-red-500/10">
                                    <AlertTriangle className="h-5 w-5 text-red-500" />
                                </div>
                                Cancel Migration?
                            </DialogTitle>
                        </DialogHeader>
                        <div className="p-6 space-y-3">
                            <p className="text-sm text-muted-foreground leading-relaxed">
                                Are you sure you want to cancel the migration?
                            </p>
                            <div className="p-3 rounded-lg bg-muted/10 border border-white/5 text-xs text-muted-foreground">
                                Note: Documents already queued for processing may still complete.
                            </div>
                        </div>
                        <DialogFooter className="p-4 bg-muted/5 border-t border-white/5 gap-3">
                            <Button variant="ghost" onClick={() => setCancelConfirmOpen(false)} className="hover:bg-white/5">
                                Keep Running
                            </Button>
                            <Button variant="destructive" onClick={handleCancelMigration}>
                                Yes, Cancel
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>
            </div>
        )
    }

    if (loading || incompatibleTenants.length === 0) {
        return null
    }

    return (
        <div className="mb-8 animate-in fade-in slide-in-from-top-4 duration-500">
            {incompatibleTenants.map(tenant => (
                <Alert
                    key={tenant.tenant_id}
                    variant="destructive"
                    className="border-destructive/50 bg-destructive/10 text-destructive dark:text-red-400 dark:border-red-900/50 dark:bg-red-900/20 shadow-[0_0_15px_rgba(239,68,68,0.1)] mb-4"
                >
                    <div className="flex items-start gap-4">
                        <AlertTriangle className="h-5 w-5 mt-1 shrink-0 animate-pulse" />
                        <div className="flex-1">
                            <AlertTitle className="text-lg font-bold tracking-tight mb-2 flex items-center gap-2">
                                System Critical: Embedding Model Mismatch
                            </AlertTitle>
                            <AlertDescription className="text-sm/relaxed space-y-4">
                                <p>
                                    The configured embedding model
                                    <span className="font-mono bg-black/20 px-1.5 py-0.5 rounded mx-1.5 text-foreground font-semibold">
                                        {tenant.system_config.model}
                                    </span>
                                    does not match the existing vector data for tenant
                                    <strong> {tenant.tenant_name}</strong>.
                                </p>

                                <div className="grid grid-cols-2 gap-4 bg-black/5 p-3 rounded-md border border-black/5 text-xs font-mono">
                                    <div>
                                        <div className="text-muted-foreground mb-1 uppercase tracking-wider text-[10px]">Stored Configuration</div>
                                        <div className="flex flex-col gap-0.5">
                                            <span>Model: {tenant.stored_config.model || 'Unknown'}</span>
                                            <span>Dims: {tenant.stored_config.dimensions || '?'}</span>
                                        </div>
                                    </div>
                                    <div>
                                        <div className="text-muted-foreground mb-1 uppercase tracking-wider text-[10px]">Active System Config</div>
                                        <div className="flex flex-col gap-0.5 text-foreground font-semibold">
                                            <span>Model: {tenant.system_config.model}</span>
                                            <span>Dims: {tenant.system_config.dimensions}</span>
                                        </div>
                                    </div>
                                </div>

                                <p className="text-destructive-foreground/80">
                                    New documents will fail to ingest, and retrieval may produce runtime errors.
                                    You must migrate the data to resolve this.
                                </p>

                                <div className="pt-2">
                                    <Button
                                        variant="destructive"
                                        className="gap-2 shadow-lg shadow-red-900/20 hover:shadow-red-900/40 transition-all active:scale-95"
                                        onClick={() => handleMigrateClick(tenant)}
                                    >
                                        <RefreshCw className="w-4 h-4" />
                                        Initiate Migration Protocol
                                    </Button>
                                </div>
                            </AlertDescription>
                        </div>
                    </div>
                </Alert>
            ))}

            {/* Manual Migration Confirmation Dialog */}
            <Dialog open={migrationOpen} onOpenChange={() => !migrating && handleClose()}>
                <DialogContent className="bg-zinc-950 border-white/10 shadow-2xl p-0 gap-0 overflow-hidden sm:max-w-md">
                    <DialogHeader className="p-6 border-b border-white/5 bg-white/[0.02]">
                        <DialogTitle className="font-display tracking-tight text-lg flex items-center gap-3">
                            <div className={`p-2 rounded-lg ${result ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
                                {result ? <CheckCircle className="h-5 w-5 text-green-500" /> : <AlertTriangle className="h-5 w-5 text-red-500" />}
                            </div>
                            {result ? 'Migration Initiated' : 'Confirm Migration'}
                        </DialogTitle>
                    </DialogHeader>

                    <div className="p-6 space-y-4">
                        {result ? (
                            <div className="space-y-4">
                                <div className="p-4 rounded-lg bg-green-500/5 border border-green-500/10 space-y-3">
                                    <p className="text-sm font-medium text-green-500">Migration Started Successfully</p>
                                    <div className="grid grid-cols-3 gap-3 text-center">
                                        <div className="p-2 rounded bg-green-500/5">
                                            <div className="text-xs text-muted-foreground mb-1">Chunks Deleted</div>
                                            <div className="text-lg font-bold text-foreground">{result.chunks_deleted}</div>
                                        </div>
                                        <div className="p-2 rounded bg-green-500/5">
                                            <div className="text-xs text-muted-foreground mb-1">Docs Queued</div>
                                            <div className="text-lg font-bold text-foreground">{result.docs_queued}</div>
                                        </div>
                                        <div className="p-2 rounded bg-green-500/5">
                                            <div className="text-xs text-muted-foreground mb-1">New Model</div>
                                            <div className="text-sm font-medium text-foreground truncate">{result.new_model}</div>
                                        </div>
                                    </div>
                                </div>
                                <p className="text-sm text-muted-foreground">
                                    The system is now re-ingesting your documents in the background.
                                </p>
                            </div>
                        ) : error ? (
                            <div className="p-4 rounded-lg bg-red-500/5 border border-red-500/10 flex items-start gap-3">
                                <XCircle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
                                <div>
                                    <p className="font-medium text-red-500">Migration Failed</p>
                                    <p className="text-sm text-red-500/80 mt-1">{error}</p>
                                </div>
                            </div>
                        ) : (
                            <>
                                <div className="p-4 rounded-lg bg-red-500/5 border border-red-500/10">
                                    <p className="text-sm font-medium text-red-500 mb-2">This action is irreversible</p>
                                    <ul className="text-xs text-red-500/80 space-y-1 list-disc list-inside">
                                        <li>Vector collection <span className="font-mono">amber_{selectedTenant?.tenant_id}</span> will be dropped</li>
                                        <li>All existing chunks will be deleted</li>
                                        <li>Documents will be reset to INGESTED status</li>
                                        <li>All documents will be re-processed</li>
                                    </ul>
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium block">
                                        Type <span className="font-mono font-bold text-foreground bg-muted/50 px-1.5 py-0.5 rounded">MIGRATE</span> to confirm
                                    </label>
                                    <Input
                                        value={confirmText}
                                        onChange={(e) => setConfirmText(e.target.value)}
                                        placeholder="MIGRATE"
                                        className="font-mono tracking-wider bg-muted/10 border-white/10"
                                        disabled={migrating}
                                    />
                                </div>
                            </>
                        )}
                    </div>

                    <DialogFooter className="p-4 bg-muted/5 border-t border-white/5 gap-3">
                        {result ? (
                            <Button
                                onClick={handleClose}
                                className="bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/20"
                            >
                                Close
                            </Button>
                        ) : (
                            <>
                                <Button
                                    variant="ghost"
                                    onClick={handleClose}
                                    disabled={migrating}
                                    className="hover:bg-white/5"
                                >
                                    Cancel
                                </Button>
                                <Button
                                    variant="destructive"
                                    onClick={handleConfirmMigration}
                                    disabled={confirmText !== 'MIGRATE' || migrating}
                                >
                                    {migrating ? (
                                        <>
                                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                            Processing...
                                        </>
                                    ) : (
                                        'Execute Migration'
                                    )}
                                </Button>
                            </>
                        )}
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
