/**
 * DataRetentionPage.tsx
 * =====================
 * 
 * Admin page for data retention and conversation export.
 * Features a clean, standard layout with smooth state transitions.
 */

import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
    Download,
    Loader2,
    CheckCircle,
    XCircle,
    Archive,
    FileArchive,
    Database,
    HardDrive,
    FileText
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { exportApi, ExportJobResponse } from '@/lib/api-admin'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

export default function DataRetentionPage() {
    const [isExporting, setIsExporting] = useState(false)
    const [exportJobId, setExportJobId] = useState<string | null>(null)
    const [exportStatus, setExportStatus] = useState<ExportJobResponse | null>(null)

    // Poll for export job status
    useEffect(() => {
        if (!exportJobId) return

        // Stop polling if already completed/failed
        if (exportStatus?.status === 'completed' || exportStatus?.status === 'failed') {
            return
        }

        const pollStatus = async () => {
            try {
                const status = await exportApi.getJobStatus(exportJobId)

                // Only update state if changed to avoid unnecessary re-renders
                if (JSON.stringify(status) !== JSON.stringify(exportStatus)) {
                    setExportStatus(status)

                    if (status.status === 'completed') {
                        setIsExporting(false)
                        toast.success('Export ready for download!')
                    } else if (status.status === 'failed') {
                        setIsExporting(false)
                        toast.error(`Export failed: ${status.error || 'Unknown error'}`)
                    }
                }
            } catch (error) {
                console.error('Failed to poll export status:', error)
            }
        }

        // Poll immediately, then every 2 seconds
        pollStatus()
        const interval = setInterval(pollStatus, 2000)

        return () => clearInterval(interval)
    }, [exportJobId, exportStatus?.status])

    const handleStartExport = useCallback(async () => {
        setIsExporting(true)
        setExportStatus(null)
        try {
            const response = await exportApi.startExportAll()
            setExportJobId(response.job_id)
            toast.info('Export started. This may take a few moments...')
        } catch (error) {
            console.error('Failed to start export:', error)
            toast.error('Failed to start export')
            setIsExporting(false)
        }
    }, [])

    const handleCancelExport = useCallback(async () => {
        if (!exportJobId) return

        try {
            await exportApi.cancelExport(exportJobId)
            toast.success('Export cancelled')
            setExportStatus(null)
            setExportJobId(null)
            setIsExporting(false)
        } catch (error) {
            console.error('Failed to cancel export:', error)
            toast.error('Failed to cancel export')
        }
    }, [exportJobId])

    const handleDownloadExport = useCallback(async () => {
        if (!exportJobId) return

        try {
            const blob = await exportApi.downloadExport(exportJobId)

            // Ensure blob has correct MIME type
            const zipBlob = new Blob([blob], { type: 'application/zip' })

            const url = window.URL.createObjectURL(zipBlob)
            const a = document.createElement('a')
            a.href = url
            a.download = `amber_conversations_export.zip`
            a.style.display = 'none'
            document.body.appendChild(a)
            a.click()

            // Clean up
            setTimeout(() => {
                document.body.removeChild(a)
                window.URL.revokeObjectURL(url)
            }, 100)

            toast.success('Download started')
        } catch (error) {
            console.error('Failed to download export:', error)
            toast.error('Failed to download export')
        }
    }, [exportJobId])

    const formatFileSize = (bytes?: number) => {
        if (!bytes) return 'Unknown size'
        if (bytes < 1024) return `${bytes} B`
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    }

    return (
        <div className="p-6 max-w-4xl mx-auto space-y-8">
            <header>
                <h1 className="text-2xl font-bold flex items-center gap-2">
                    <Archive className="h-6 w-6" />
                    Data Retention
                </h1>
                <p className="text-muted-foreground mt-1">
                    Export all your conversation data, including transcripts, metadata, and source files.
                </p>
            </header>

            <Card className="overflow-hidden">
                <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                        <FileArchive className="h-5 w-5" />
                        Export All Conversations
                    </CardTitle>
                    <CardDescription>
                        Create a full backup of your workspace.
                    </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                    {/* Info Grid */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        {[
                            { icon: FileText, label: "Transcripts", desc: "Txt Format" },
                            { icon: Database, label: "Metadata", desc: "JSON Citations" },
                            { icon: HardDrive, label: "Documents", desc: "Source Files" }
                        ].map((item, i) => (
                            <div key={i} className="flex items-center gap-3 p-3 rounded-lg bg-muted/50 border border-transparent">
                                <item.icon className="w-4 h-4 text-muted-foreground" />
                                <div className="text-sm">
                                    <span className="font-medium block">{item.label}</span>
                                    <span className="text-xs text-muted-foreground">{item.desc}</span>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Action Area */}
                    <div className="pt-2 border-t">
                        <AnimatePresence mode="wait">
                            {!exportStatus || exportStatus.status === 'failed' ? (
                                <motion.div
                                    key="start"
                                    initial={{ opacity: 0, y: 5 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -5 }}
                                    className="flex flex-col gap-4 py-2"
                                >
                                    <div className="flex items-center gap-4">
                                        <Button
                                            onClick={handleStartExport}
                                            disabled={isExporting}
                                            className="flex items-center gap-2"
                                        >
                                            {isExporting ? (
                                                <>
                                                    <Loader2 className="w-4 h-4 animate-spin" />
                                                    Preparing Export...
                                                </>
                                            ) : (
                                                <>
                                                    <Download className="w-4 h-4" />
                                                    Export All
                                                </>
                                            )}
                                        </Button>

                                        {exportStatus?.status === 'failed' && (
                                            <span className="text-sm text-destructive flex items-center gap-2">
                                                <XCircle className="w-4 h-4" />
                                                {exportStatus.error}
                                            </span>
                                        )}
                                    </div>
                                </motion.div>
                            ) : exportStatus.status === 'pending' || exportStatus.status === 'running' ? (
                                <motion.div
                                    key="running"
                                    initial={{ opacity: 0, height: 0 }}
                                    animate={{ opacity: 1, height: "auto" }}
                                    exit={{ opacity: 0, height: 0 }}
                                    className="pt-2"
                                >
                                    <div className="bg-muted/30 rounded-lg p-4 space-y-4">
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-3">
                                                <Loader2 className="w-4 h-4 animate-spin text-primary" />
                                                <div className="text-sm font-medium">
                                                    {exportStatus.status === 'pending' ? 'Queued' : 'Processing Archive...'}
                                                </div>
                                            </div>
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                onClick={handleCancelExport}
                                                className="h-8 text-muted-foreground hover:text-destructive"
                                            >
                                                Stop
                                            </Button>
                                        </div>
                                        <div className="w-full h-1 bg-muted rounded-full overflow-hidden">
                                            <motion.div
                                                className="h-full bg-primary"
                                                initial={{ width: "0%" }}
                                                animate={{ width: "60%" }}
                                                transition={{ duration: 0.5 }}
                                            />
                                        </div>
                                        <div className="text-xs text-muted-foreground font-mono">
                                            Job ID: {exportStatus.job_id}
                                        </div>
                                    </div>
                                </motion.div>
                            ) : (
                                <motion.div
                                    key="completed"
                                    initial={{ opacity: 0, y: 5 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    className="flex items-center gap-4 py-2"
                                >
                                    <Button
                                        onClick={handleDownloadExport}
                                        className="gap-2 bg-green-600 hover:bg-green-700 text-white"
                                    >
                                        <Download className="w-4 h-4" />
                                        Download ZIP
                                    </Button>
                                    <span className="text-sm text-muted-foreground">
                                        Size: {formatFileSize(exportStatus.file_size)}
                                    </span>
                                    <div className="flex-1" />
                                    <Button
                                        variant="ghost"
                                        onClick={handleStartExport}
                                    >
                                        New Export
                                    </Button>
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>
                </CardContent>
            </Card>
        </div>
    )
}
