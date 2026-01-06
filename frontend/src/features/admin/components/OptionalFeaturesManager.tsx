/**
 * Optional Features Management Component
 * =======================================
 * 
 * Displays and manages optional ML features that can be installed on-demand.
 */

import { useState, useEffect, useCallback } from 'react'
import { Download, Check, AlertCircle, Loader2, RefreshCw, Package } from 'lucide-react'

interface Feature {
    id: string
    name: string
    description: string
    size_mb: number
    status: 'not_installed' | 'installing' | 'installed' | 'failed'
    error_message?: string
}

interface SetupStatus {
    initialized: boolean
    setup_complete: boolean
    features: Feature[]
    summary: {
        total: number
        installed: number
        installing: number
        not_installed: number
    }
}

export default function OptionalFeaturesManager() {
    const [status, setStatus] = useState<SetupStatus | null>(null)
    const [loading, setLoading] = useState(true)
    const [installing, setInstalling] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)

    const fetchStatus = useCallback(async () => {
        try {
            const response = await fetch('/api/setup/status')
            if (!response.ok) throw new Error('Failed to fetch status')
            const data: SetupStatus = await response.json()
            setStatus(data)
            setError(null)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error')
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchStatus()
    }, [fetchStatus])

    // Poll while installing
    useEffect(() => {
        if (!installing) return

        const interval = setInterval(async () => {
            await fetchStatus()
            if (status?.features.find(f => f.id === installing)?.status !== 'installing') {
                setInstalling(null)
            }
        }, 2000)

        return () => clearInterval(interval)
    }, [installing, fetchStatus, status])

    const handleInstall = async (featureId: string) => {
        try {
            setInstalling(featureId)
            // 30 minute timeout for large downloads
            const controller = new AbortController()
            const timeoutId = setTimeout(() => controller.abort(), 30 * 60 * 1000)

            const response = await fetch('/api/setup/install', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ feature_ids: [featureId] }),
                signal: controller.signal
            })

            clearTimeout(timeoutId)

            if (!response.ok) {
                const data = await response.json()
                throw new Error(data.detail || 'Installation failed')
            }

            await fetchStatus()
        } catch (err: unknown) {
            const error = err as { name?: string; message?: string }
            const errorMessage = error.name === 'AbortError'
                ? 'Installation timed out. It may still be running in the background.'
                : (err instanceof Error ? err.message : 'Installation failed')

            setError(errorMessage)
            setInstalling(null)
        }
    }

    const formatSize = (mb: number) => {
        if (mb >= 1000) return `${(mb / 1000).toFixed(1)} GB`
        return `${mb} MB`
    }

    const getStatusBadge = (feature: Feature) => {
        switch (feature.status) {
            case 'installed':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                        <Check className="w-3 h-3" />
                        Installed
                    </span>
                )
            case 'installing':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        Installing...
                    </span>
                )
            case 'failed':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" title={feature.error_message}>
                        <AlertCircle className="w-3 h-3" />
                        Failed
                    </span>
                )
            default:
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-muted text-muted-foreground">
                        {formatSize(feature.size_mb)}
                    </span>
                )
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-lg font-semibold flex items-center gap-2">
                        <Package className="w-5 h-5" />
                        Optional Features
                    </h2>
                    <p className="text-sm text-muted-foreground">
                        Install additional ML capabilities for enhanced functionality.
                    </p>
                </div>
                <button
                    onClick={() => {
                        setLoading(true)
                        fetchStatus()
                    }}
                    className="p-2 hover:bg-muted rounded-md transition-colors"
                    title="Refresh status"
                >
                    <RefreshCw className="w-4 h-4" />
                </button>
            </div>

            {error && (
                <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400 text-sm">
                    {error}
                </div>
            )}

            {status && (
                <div className="text-sm text-muted-foreground mb-4">
                    {status.summary.installed} of {status.summary.total} features installed
                </div>
            )}

            <div className="space-y-3">
                {status?.features.map(feature => (
                    <div
                        key={feature.id}
                        className="flex items-center justify-between p-4 border rounded-lg bg-card hover:bg-muted/30 transition-colors"
                    >
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                                <h3 className="font-medium">{feature.name}</h3>
                                {getStatusBadge(feature)}
                            </div>
                            <p className="text-sm text-muted-foreground mt-1 truncate">
                                {feature.description}
                            </p>
                        </div>

                        {feature.status === 'not_installed' && (
                            <button
                                onClick={() => handleInstall(feature.id)}
                                disabled={installing !== null}
                                className="ml-4 flex items-center gap-2 px-3 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors disabled:opacity-50"
                            >
                                <Download className="w-4 h-4" />
                                Install
                            </button>
                        )}

                        {feature.status === 'failed' && (
                            <button
                                onClick={() => handleInstall(feature.id)}
                                disabled={installing !== null}
                                className="ml-4 flex items-center gap-2 px-3 py-2 border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                            >
                                <RefreshCw className="w-4 h-4" />
                                Retry
                            </button>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}
