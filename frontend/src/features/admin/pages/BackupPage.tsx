/**
 * BackupPage.tsx
 * ==============
 * 
 * Admin page for system backup and restore operations.
 * Features: create backups, view history, restore, and schedule configuration.
 */

import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
    Download,
    Loader2,
    Trash2,
    DatabaseBackup,
    Calendar,
    RotateCcw,
    CheckCircle2,
    XCircle,
    AlertTriangle,
    Clock,
    FileArchive,
    Circle
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { backupApi, BackupJob, RestoreJob, BackupSchedule } from '@/lib/api-admin'
import { toast } from 'sonner'
import { PageHeader } from '../components/PageHeader'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { ConfirmDialog } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

// Helpers
const formatBytes = (bytes: number | null | undefined): string => {
    if (!bytes) return '-'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const formatDate = (dateStr: string | null | undefined): string => {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleString()
}

const getStatusIcon = (status: string) => {
    switch (status) {
        case 'completed': return <CheckCircle2 className="h-4 w-4 text-green-500" />
        case 'running': return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
        case 'failed': return <XCircle className="h-4 w-4 text-red-500" />
        case 'pending': return <Clock className="h-4 w-4 text-yellow-500" />
        default: return <Clock className="h-4 w-4 text-gray-500" />
    }
}

// Simple Radio Option component (inline replacement for missing RadioGroup)
interface RadioOptionProps {
    selected: boolean
    onSelect: () => void
    children: React.ReactNode
    className?: string
}

function RadioOption({ selected, onSelect, children, className }: RadioOptionProps) {
    return (
        <div
            onClick={onSelect}
            className={cn(
                "flex items-start gap-3 p-4 border rounded-lg cursor-pointer transition-colors",
                selected ? "border-primary bg-primary/5" : "hover:bg-muted/50",
                className
            )}
        >
            <div className="mt-1">
                {selected ? (
                    <div className="h-4 w-4 rounded-full border-2 border-primary bg-primary flex items-center justify-center">
                        <Circle className="h-2 w-2 text-primary-foreground fill-current" />
                    </div>
                ) : (
                    <div className="h-4 w-4 rounded-full border-2 border-muted-foreground/50" />
                )}
            </div>
            {children}
        </div>
    )
}

export default function BackupPage() {
    // === Create Backup State ===
    const [scope, setScope] = useState<'user_data' | 'full_system'>('user_data')
    const [isCreating, setIsCreating] = useState(false)
    const [currentJobId, setCurrentJobId] = useState<string | null>(null)
    const [currentJob, setCurrentJob] = useState<BackupJob | null>(null)

    // === Backup List State ===
    const [backups, setBackups] = useState<BackupJob[]>([])
    const [isLoadingBackups, setIsLoadingBackups] = useState(false)

    // === Restore State ===
    const [restoreMode, setRestoreMode] = useState<'merge' | 'replace'>('merge')
    const [isRestoring, setIsRestoring] = useState(false)
    const [restoreJobId, setRestoreJobId] = useState<string | null>(null)
    const [restoreJob, setRestoreJob] = useState<RestoreJob | null>(null)
    const [confirmRestore, setConfirmRestore] = useState<BackupJob | null>(null)

    // === Schedule State ===
    const [schedule, setSchedule] = useState<BackupSchedule | null>(null)
    const [isLoadingSchedule, setIsLoadingSchedule] = useState(false)
    const [isSavingSchedule, setIsSavingSchedule] = useState(false)

    // === Data Loading ===
    const loadBackups = useCallback(async () => {
        setIsLoadingBackups(true)
        try {
            const response = await backupApi.listBackups({ size: 50 })
            setBackups(response.backups)
        } catch (error) {
            console.error('Failed to load backups:', error)
            toast.error('Failed to load backups')
        } finally {
            setIsLoadingBackups(false)
        }
    }, [])

    const loadSchedule = useCallback(async () => {
        setIsLoadingSchedule(true)
        try {
            const data = await backupApi.getSchedule()
            setSchedule(data)
        } catch (error) {
            console.error('Failed to load schedule:', error)
        } finally {
            setIsLoadingSchedule(false)
        }
    }, [])

    useEffect(() => {
        loadBackups()
        loadSchedule()
    }, [loadBackups, loadSchedule])

    // === Create Backup Polling ===
    useEffect(() => {
        if (!currentJobId) return
        if (currentJob?.status === 'completed' || currentJob?.status === 'failed') return

        const poll = async () => {
            try {
                const job = await backupApi.getBackupJob(currentJobId)
                setCurrentJob(job)
                if (job.status === 'completed') {
                    setIsCreating(false)
                    toast.success('Backup created successfully!')
                    loadBackups()
                } else if (job.status === 'failed') {
                    setIsCreating(false)
                    toast.error(`Backup failed: ${job.error_message || 'Unknown error'}`)
                }
            } catch (error) {
                console.error('Failed to poll backup status:', error)
            }
        }

        poll()
        const interval = setInterval(poll, 2000)
        return () => clearInterval(interval)
    }, [currentJobId, currentJob?.status, loadBackups])

    // === Restore Polling ===
    useEffect(() => {
        if (!restoreJobId) return
        if (restoreJob?.status === 'completed' || restoreJob?.status === 'failed') return

        const poll = async () => {
            try {
                const job = await backupApi.getRestoreJob(restoreJobId)
                setRestoreJob(job)
                if (job.status === 'completed') {
                    setIsRestoring(false)
                    toast.success(`Restore complete! ${job.items_restored} items restored.`)
                } else if (job.status === 'failed') {
                    setIsRestoring(false)
                    toast.error(`Restore failed: ${job.error_message || 'Unknown error'}`)
                }
            } catch (error) {
                console.error('Failed to poll restore status:', error)
            }
        }

        poll()
        const interval = setInterval(poll, 2000)
        return () => clearInterval(interval)
    }, [restoreJobId, restoreJob?.status])

    // === Handlers ===
    const handleCreateBackup = useCallback(async () => {
        setIsCreating(true)
        setCurrentJob(null)
        try {
            const response = await backupApi.createBackup(scope)
            setCurrentJobId(response.job_id)
            toast.info('Backup started...')
        } catch (error) {
            console.error('Failed to start backup:', error)
            toast.error('Failed to start backup')
            setIsCreating(false)
        }
    }, [scope])

    const handleDownload = useCallback(async (jobId: string) => {
        try {
            const blob = await backupApi.downloadBackup(jobId)
            const url = window.URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `backup_${jobId.slice(0, 8)}.zip`
            document.body.appendChild(a)
            a.click()
            document.body.removeChild(a)
            window.URL.revokeObjectURL(url)
            toast.success('Backup downloaded')
        } catch (error) {
            console.error('Failed to download backup:', error)
            toast.error('Failed to download backup')
        }
    }, [])

    const handleDelete = useCallback(async (jobId: string) => {
        try {
            await backupApi.deleteBackup(jobId)
            toast.success('Backup deleted')
            loadBackups()
        } catch (error) {
            console.error('Failed to delete backup:', error)
            toast.error('Failed to delete backup')
        }
    }, [loadBackups])

    const handleStartRestore = useCallback(async (backup: BackupJob) => {
        setIsRestoring(true)
        setRestoreJob(null)
        setConfirmRestore(null)
        try {
            const response = await backupApi.startRestore(backup.id, restoreMode)
            setRestoreJobId(response.job_id)
            toast.info('Restore started...')
        } catch (error) {
            console.error('Failed to start restore:', error)
            toast.error('Failed to start restore')
            setIsRestoring(false)
        }
    }, [restoreMode])

    const handleSaveSchedule = useCallback(async () => {
        if (!schedule) return
        setIsSavingSchedule(true)
        try {
            await backupApi.setSchedule(schedule)
            toast.success('Schedule saved')
        } catch (error) {
            console.error('Failed to save schedule:', error)
            toast.error('Failed to save schedule')
        } finally {
            setIsSavingSchedule(false)
        }
    }, [schedule])

    const restoreDialogDescription = confirmRestore
        ? `You are about to restore from backup created on ${formatDate(confirmRestore.created_at)}. Mode: ${restoreMode === 'merge' ? 'Merge (keep existing data)' : 'Replace (delete all existing data)'}. ${restoreMode === 'replace' ? 'Warning: Replace mode will delete all existing data. This cannot be undone!' : ''}`
        : ''

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="Backup & Restore"
                description="Create backups, restore from backups, and configure scheduled backups"
            />

            <Tabs defaultValue="create" className="w-full">
                <TabsList className="mb-8">
                    <TabsTrigger value="create" className="gap-2">
                        <DatabaseBackup className="h-4 w-4" />
                        Create Backup
                    </TabsTrigger>
                    <TabsTrigger value="history" className="gap-2">
                        <FileArchive className="h-4 w-4" />
                        Backups ({backups.length})
                    </TabsTrigger>
                    <TabsTrigger value="restore" className="gap-2">
                        <RotateCcw className="h-4 w-4" />
                        Restore
                    </TabsTrigger>
                    <TabsTrigger value="schedule" className="gap-2">
                        <Calendar className="h-4 w-4" />
                        Schedule
                    </TabsTrigger>
                </TabsList>

                {/* === CREATE BACKUP TAB === */}
                <TabsContent value="create">
                    <Card>
                        <CardHeader>
                            <CardTitle>Create New Backup</CardTitle>
                            <CardDescription>
                                Choose what to include in your backup
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-6">
                            <div className="space-y-4">
                                <RadioOption
                                    selected={scope === 'user_data'}
                                    onSelect={() => setScope('user_data')}
                                >
                                    <div className="space-y-1">
                                        <Label className="text-base font-medium cursor-pointer">
                                            User Data Only
                                        </Label>
                                        <p className="text-sm text-muted-foreground">
                                            Documents, conversations, user facts, and memory summaries.
                                            Recommended for regular backups.
                                        </p>
                                    </div>
                                </RadioOption>
                                <RadioOption
                                    selected={scope === 'full_system'}
                                    onSelect={() => setScope('full_system')}
                                >
                                    <div className="space-y-1">
                                        <Label className="text-base font-medium cursor-pointer">
                                            Full System
                                        </Label>
                                        <p className="text-sm text-muted-foreground">
                                            Everything above plus global rules, tenant config, and metadata.
                                            Larger file size.
                                        </p>
                                    </div>
                                </RadioOption>
                            </div>

                            {/* Progress during backup */}
                            <AnimatePresence>
                                {isCreating && currentJob && (
                                    <motion.div
                                        initial={{ opacity: 0, height: 0 }}
                                        animate={{ opacity: 1, height: 'auto' }}
                                        exit={{ opacity: 0, height: 0 }}
                                        className="space-y-2"
                                    >
                                        <div className="flex items-center justify-between text-sm">
                                            <span className="flex items-center gap-2">
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                                Creating backup...
                                            </span>
                                            <span>{currentJob.progress}%</span>
                                        </div>
                                        <Progress value={currentJob.progress} />
                                    </motion.div>
                                )}
                            </AnimatePresence>

                            {/* Success state */}
                            {currentJob?.status === 'completed' && (
                                <motion.div
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="flex items-center gap-3 p-4 bg-green-500/10 border border-green-500/20 rounded-lg"
                                >
                                    <CheckCircle2 className="h-5 w-5 text-green-500" />
                                    <div className="flex-1">
                                        <p className="font-medium">Backup ready!</p>
                                        <p className="text-sm text-muted-foreground">
                                            Size: {formatBytes(currentJob.file_size)}
                                        </p>
                                    </div>
                                    <Button onClick={() => handleDownload(currentJob.id)}>
                                        <Download className="h-4 w-4 mr-2" />
                                        Download
                                    </Button>
                                </motion.div>
                            )}

                            <Button
                                onClick={handleCreateBackup}
                                disabled={isCreating}
                                size="lg"
                                className="w-full"
                            >
                                {isCreating ? (
                                    <>
                                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                        Creating Backup...
                                    </>
                                ) : (
                                    <>
                                        <DatabaseBackup className="h-4 w-4 mr-2" />
                                        Create Backup
                                    </>
                                )}
                            </Button>
                        </CardContent>
                    </Card>
                </TabsContent>

                {/* === BACKUP HISTORY TAB === */}
                <TabsContent value="history">
                    <Card>
                        <CardHeader>
                            <CardTitle>Available Backups</CardTitle>
                            <CardDescription>
                                View, download, or delete previous backups
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            {isLoadingBackups ? (
                                <div className="flex items-center justify-center py-8">
                                    <Loader2 className="h-6 w-6 animate-spin" />
                                </div>
                            ) : backups.length === 0 ? (
                                <div className="text-center py-8 text-muted-foreground">
                                    <FileArchive className="h-12 w-12 mx-auto mb-3 opacity-30" />
                                    <p>No backups yet</p>
                                    <p className="text-sm">Create your first backup to get started</p>
                                </div>
                            ) : (
                                <div className="space-y-2">
                                    {backups.map((backup) => (
                                        <div
                                            key={backup.id}
                                            className="flex items-center gap-4 p-4 border rounded-lg hover:bg-muted/50 transition-colors"
                                        >
                                            {getStatusIcon(backup.status)}
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center gap-2">
                                                    <span className="font-medium">
                                                        {backup.scope === 'full_system' ? 'Full System' : 'User Data'}
                                                    </span>
                                                    <span className="text-xs px-2 py-0.5 bg-muted rounded-full">
                                                        {backup.status}
                                                    </span>
                                                </div>
                                                <div className="text-sm text-muted-foreground">
                                                    {formatDate(backup.created_at)} • {formatBytes(backup.file_size)}
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                {backup.status === 'completed' && (
                                                    <>
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            onClick={() => handleDownload(backup.id)}
                                                        >
                                                            <Download className="h-4 w-4" />
                                                        </Button>
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            onClick={() => setConfirmRestore(backup)}
                                                        >
                                                            <RotateCcw className="h-4 w-4" />
                                                        </Button>
                                                    </>
                                                )}
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={() => handleDelete(backup.id)}
                                                >
                                                    <Trash2 className="h-4 w-4 text-destructive" />
                                                </Button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </TabsContent>

                {/* === RESTORE TAB === */}
                <TabsContent value="restore">
                    <Card>
                        <CardHeader>
                            <CardTitle>Restore from Backup</CardTitle>
                            <CardDescription>
                                Restore your system from a previous backup
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-6">
                            <div className="space-y-4">
                                <Label className="text-base">Restore Mode</Label>
                                <RadioOption
                                    selected={restoreMode === 'merge'}
                                    onSelect={() => setRestoreMode('merge')}
                                >
                                    <div className="space-y-1">
                                        <Label className="font-medium cursor-pointer">
                                            Merge
                                        </Label>
                                        <p className="text-sm text-muted-foreground">
                                            Keep existing data and add items from backup.
                                            Duplicate items will be skipped.
                                        </p>
                                    </div>
                                </RadioOption>
                                <RadioOption
                                    selected={restoreMode === 'replace'}
                                    onSelect={() => setRestoreMode('replace')}
                                    className="border-destructive/50 bg-destructive/5"
                                >
                                    <div className="space-y-1">
                                        <Label className="font-medium cursor-pointer flex items-center gap-2">
                                            Replace
                                            <AlertTriangle className="h-4 w-4 text-destructive" />
                                        </Label>
                                        <p className="text-sm text-muted-foreground">
                                            Delete all existing data and replace with backup contents.
                                            This action cannot be undone!
                                        </p>
                                    </div>
                                </RadioOption>
                            </div>

                            {/* Restore Progress */}
                            <AnimatePresence>
                                {isRestoring && restoreJob && (
                                    <motion.div
                                        initial={{ opacity: 0, height: 0 }}
                                        animate={{ opacity: 1, height: 'auto' }}
                                        exit={{ opacity: 0, height: 0 }}
                                        className="space-y-2 p-4 border rounded-lg"
                                    >
                                        <div className="flex items-center justify-between text-sm">
                                            <span className="flex items-center gap-2">
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                                Restoring...
                                            </span>
                                            <span>{restoreJob.progress}%</span>
                                        </div>
                                        <Progress value={restoreJob.progress} />
                                    </motion.div>
                                )}
                            </AnimatePresence>

                            {restoreJob?.status === 'completed' && (
                                <motion.div
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="flex items-center gap-3 p-4 bg-green-500/10 border border-green-500/20 rounded-lg"
                                >
                                    <CheckCircle2 className="h-5 w-5 text-green-500" />
                                    <div>
                                        <p className="font-medium">Restore complete!</p>
                                        <p className="text-sm text-muted-foreground">
                                            {restoreJob.items_restored} items restored
                                        </p>
                                    </div>
                                </motion.div>
                            )}

                            <div className="text-sm text-muted-foreground">
                                Select a backup from the "Backups" tab and click the restore button,
                                or use the options above to configure restore behavior.
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>

                {/* === SCHEDULE TAB === */}
                <TabsContent value="schedule">
                    <Card>
                        <CardHeader>
                            <CardTitle>Scheduled Backups</CardTitle>
                            <CardDescription>
                                Configure automatic backup schedule
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-6">
                            {isLoadingSchedule ? (
                                <div className="flex items-center justify-center py-8">
                                    <Loader2 className="h-6 w-6 animate-spin" />
                                </div>
                            ) : schedule && (
                                <>
                                    <div className="flex items-center justify-between">
                                        <div className="space-y-0.5">
                                            <Label className="text-base">Enable Scheduled Backups</Label>
                                            <p className="text-sm text-muted-foreground">
                                                Automatically create backups on a schedule
                                            </p>
                                        </div>
                                        <Switch
                                            checked={schedule.enabled}
                                            onCheckedChange={(checked) =>
                                                setSchedule({ ...schedule, enabled: checked })
                                            }
                                        />
                                    </div>

                                    {schedule.enabled && (
                                        <motion.div
                                            initial={{ opacity: 0, height: 0 }}
                                            animate={{ opacity: 1, height: 'auto' }}
                                            className="space-y-4 pt-4 border-t"
                                        >
                                            <div className="grid grid-cols-2 gap-4">
                                                <div className="space-y-2">
                                                    <Label>Frequency</Label>
                                                    <Select
                                                        value={schedule.frequency}
                                                        onValueChange={(v: 'daily' | 'weekly') =>
                                                            setSchedule({ ...schedule, frequency: v })
                                                        }
                                                    >
                                                        <SelectTrigger>
                                                            <SelectValue />
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            <SelectItem value="daily">Daily</SelectItem>
                                                            <SelectItem value="weekly">Weekly</SelectItem>
                                                        </SelectContent>
                                                    </Select>
                                                </div>
                                                <div className="space-y-2">
                                                    <Label>Time (UTC)</Label>
                                                    <Input
                                                        type="time"
                                                        value={schedule.time_utc}
                                                        onChange={(e) =>
                                                            setSchedule({ ...schedule, time_utc: e.target.value })
                                                        }
                                                    />
                                                </div>
                                            </div>

                                            {schedule.frequency === 'weekly' && (
                                                <div className="space-y-2">
                                                    <Label>Day of Week</Label>
                                                    <Select
                                                        value={schedule.day_of_week?.toString() ?? '0'}
                                                        onValueChange={(v: string) =>
                                                            setSchedule({ ...schedule, day_of_week: parseInt(v) })
                                                        }
                                                    >
                                                        <SelectTrigger>
                                                            <SelectValue />
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            <SelectItem value="0">Monday</SelectItem>
                                                            <SelectItem value="1">Tuesday</SelectItem>
                                                            <SelectItem value="2">Wednesday</SelectItem>
                                                            <SelectItem value="3">Thursday</SelectItem>
                                                            <SelectItem value="4">Friday</SelectItem>
                                                            <SelectItem value="5">Saturday</SelectItem>
                                                            <SelectItem value="6">Sunday</SelectItem>
                                                        </SelectContent>
                                                    </Select>
                                                </div>
                                            )}

                                            <div className="grid grid-cols-2 gap-4">
                                                <div className="space-y-2">
                                                    <Label>Backup Scope</Label>
                                                    <Select
                                                        value={schedule.scope}
                                                        onValueChange={(v: 'user_data' | 'full_system') =>
                                                            setSchedule({ ...schedule, scope: v })
                                                        }
                                                    >
                                                        <SelectTrigger>
                                                            <SelectValue />
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            <SelectItem value="user_data">User Data</SelectItem>
                                                            <SelectItem value="full_system">Full System</SelectItem>
                                                        </SelectContent>
                                                    </Select>
                                                </div>
                                                <div className="space-y-2">
                                                    <Label>Keep Last N Backups</Label>
                                                    <Input
                                                        type="number"
                                                        min={1}
                                                        max={30}
                                                        value={schedule.retention_count}
                                                        onChange={(e) =>
                                                            setSchedule({ ...schedule, retention_count: parseInt(e.target.value) || 7 })
                                                        }
                                                    />
                                                </div>
                                            </div>

                                            {schedule.last_run_at && (
                                                <div className="text-sm text-muted-foreground">
                                                    Last run: {formatDate(schedule.last_run_at)} ({schedule.last_run_status})
                                                </div>
                                            )}
                                        </motion.div>
                                    )}

                                    <Button
                                        onClick={handleSaveSchedule}
                                        disabled={isSavingSchedule}
                                        className="w-full"
                                    >
                                        {isSavingSchedule ? (
                                            <>
                                                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                                Saving...
                                            </>
                                        ) : (
                                            'Save Schedule'
                                        )}
                                    </Button>
                                </>
                            )}
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>

            {/* Restore Confirmation Dialog */}
            <ConfirmDialog
                open={!!confirmRestore}
                onOpenChange={(open) => !open && setConfirmRestore(null)}
                title="Restore from Backup?"
                description={restoreDialogDescription}
                confirmText={restoreMode === 'replace' ? 'Confirm Replace' : 'Confirm Restore'}
                cancelText="Cancel"
                onConfirm={() => confirmRestore && handleStartRestore(confirmRestore)}
                variant={restoreMode === 'replace' ? 'destructive' : 'default'}
            />
        </div>
    )
}
