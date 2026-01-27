/**
 * Optional Features Management Component
 * =======================================
 * 
 * Displays and manages optional ML features that can be installed on-demand.
 */

import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Download, Check, AlertCircle, Loader2, RefreshCw, ChevronUp, ChevronDown } from 'lucide-react'
import { PageHeader } from './PageHeader'
import { PageSkeleton } from './PageSkeleton'
import { useInstallProgress } from '../hooks/useInstallProgress'
import { AnimatedProgress } from '@/components/ui/animated-progress'

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

const FEATURE_DETAILS: Record<string, string[]> = {
    'local_embeddings': [
        'Model: BAAI/bge-small-en-v1.5 (FastEmbed)',
        'Packages: torch, sentence-transformers',
        'Size: ~2.1 GB (PyTorch included)',
        'Purpose: Local vector generation for documents'
    ],
    'reranking': [
        'Model: ms-marco-MiniLM-L-12-v2 (FlashRank)',
        'Packages: flashrank',
        'Size: ~50 MB',
        'Purpose: High-precision result re-ranking'
    ],
    'community_detection': [
        'Algorithm: Leiden (Graph Clustering)',
        'Packages: cdlib, leidenalg, python-igraph',
        'Size: ~150 MB',
        'Purpose: Advanced community structure analysis'
    ],
    'document_processing': [
        'Engine: Unstructured.io & PyMuPDF',
        'Packages: unstructured, python-magic, pymupdf4llm',
        'Size: ~800 MB',
        'Purpose: PDF, DOCX, and HTML extraction'
    ],
    'ragas': [
        'Framework: Ragas (RAG Assessment)',
        'Packages: ragas, datasets',
        'Size: ~150 MB',
        'Purpose: Automated faithfulness and relevancy scoring'
    ],
    'ocr': [
        'Engine: Marker PDF & Surya OCR',
        'Packages: marker-pdf, surya-ocr',
        'Size: ~3.0 GB',
        'Purpose: Deep learning PDF extraction'
    ]
}

export default function OptionalFeaturesManager() {
    const [status, setStatus] = useState<SetupStatus | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [expandedFeatures, setExpandedFeatures] = useState<Record<string, boolean>>({})

    // SSE progress hook
    const { startInstall, progress, isInstalling, error: installError } = useInstallProgress(() => {
        // On complete, refresh status
        fetchStatus()
    })

    const toggleFeature = (featureId: string) => {
        setExpandedFeatures(prev => ({
            ...prev,
            [featureId]: !prev[featureId]
        }))
    }

    const fetchStatus = useCallback(async () => {
        try {
            const apiKey = localStorage.getItem('api_key') || ''
            const response = await fetch('/api/v1/setup/status', {
                headers: { 'X-API-Key': apiKey }
            })
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

    // Combine SSE error with local error
    useEffect(() => {
        if (installError) {
            setError(installError)
        }
    }, [installError])

    const handleInstall = (featureId: string) => {
        setError(null)
        startInstall([featureId])
    }

    const handleInstallAll = () => {
        if (!status) return

        const featuresToInstall = status.features
            .filter(f => f.status === 'not_installed' || f.status === 'failed')
            .map(f => f.id)

        if (featuresToInstall.length === 0) return
        setError(null)
        startInstall(featuresToInstall)
    }

    const hasInstallableFeatures = status?.features.some(
        f => f.status === 'not_installed' || f.status === 'failed'
    ) ?? false

    // Helper to get progress for a feature
    const getFeatureProgress = (featureId: string) => progress[featureId]

    const formatSize = (mb: number) => {
        if (mb >= 1000) return `${(mb / 1000).toFixed(1)} GB`
        return `${mb} MB`
    }

    const getStatusBadge = (feature: Feature) => {
        switch (feature.status) {
            case 'installed':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-success-muted text-success">
                        <Check className="w-3 h-3" />
                        Installed
                    </span>
                )
            case 'installing':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-info-muted text-info-foreground">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        Installing...
                    </span>
                )
            case 'failed':
                return (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-destructive/10 text-destructive" title={feature.error_message}>
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
        return <PageSkeleton mode="list" />
    }

    return (
        <div className="space-y-4">
            <PageHeader
                title="Optional Features"
                description="Install additional ML capabilities for enhanced functionality."
                actions={
                    <div className="flex gap-2">
                        <Button
                            onClick={handleInstallAll}
                            disabled={isInstalling || !hasInstallableFeatures}
                            className="gap-2 text-xs h-9"
                        >
                            {isInstalling ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                                <Download className="w-3.5 h-3.5" />
                            )}
                            Install All
                        </Button>
                        <Button
                            variant="outline"
                            onClick={() => {
                                setLoading(true)
                                fetchStatus()
                            }}
                            className="gap-2 text-xs h-9"
                            title="Refresh status"
                        >
                            <RefreshCw className="w-3.5 h-3.5" />
                            Refresh
                        </Button>
                    </div>
                }
            />

            {error && (
                <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-sm">
                    {error}
                </div>
            )}

            {status && (
                <div className="text-sm text-muted-foreground mb-4">
                    {status.summary.installed} of {status.summary.total} features installed
                </div>
            )}

            <div className="space-y-3">
                {status?.features.map(feature => {
                    const hasDetails = (FEATURE_DETAILS[feature.id] || []).length > 0
                    const isExpanded = expandedFeatures[feature.id]
                    const featureProgress = getFeatureProgress(feature.id)

                    return (
                        <div
                            key={feature.id}
                            className="p-4 border rounded-lg bg-card hover:bg-muted/30 transition-colors"
                        >
                            <div className="flex items-start justify-between">
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                        <h3 className="font-medium">{feature.name}</h3>
                                        {getStatusBadge(feature)}
                                    </div>
                                    <p className="text-sm text-muted-foreground mt-1">
                                        {feature.description}
                                    </p>

                                    {/* Inline Progress Bar */}
                                    {featureProgress && featureProgress.phase !== 'complete' && featureProgress.phase !== 'failed' && (
                                        <div className="mt-3">
                                            <AnimatedProgress
                                                value={featureProgress.progress}
                                                size="sm"
                                                stages={[
                                                    { label: 'Downloading...', threshold: 0 },
                                                    { label: 'Installing...', threshold: 70 },
                                                    { label: 'Verifying...', threshold: 90 },
                                                ]}
                                            />
                                            <p className="text-xs text-muted-foreground truncate mt-1.5">
                                                {featureProgress.message}
                                            </p>
                                        </div>
                                    )}

                                    {/* Detailed Download List (Expandable) */}
                                    {hasDetails && (
                                        <div className="mt-2">
                                            <Button
                                                variant="link"
                                                size="sm"
                                                onClick={() => toggleFeature(feature.id)}
                                                className="h-auto p-0 text-xs flex items-center gap-1 text-primary hover:text-primary/80 font-medium"
                                            >
                                                {isExpanded ? 'Hide Details' : 'Show Details'}
                                                {isExpanded ? (
                                                    <ChevronUp className="w-3 h-3 ml-1" />
                                                ) : (
                                                    <ChevronDown className="w-3 h-3 ml-1" />
                                                )}
                                            </Button>

                                            {isExpanded && (
                                                <div className="mt-2 bg-muted/50 rounded-md p-3 animate-in fade-in slide-in-from-top-1 duration-200">
                                                    <p className="text-xs font-semibold text-muted-foreground mb-1 uppercase tracking-wider">
                                                        Downloads
                                                    </p>
                                                    <ul className="space-y-1">
                                                        {FEATURE_DETAILS[feature.id]?.map((detail, idx) => (
                                                            <li key={idx} className="text-xs text-muted-foreground flex items-center gap-2">
                                                                <div className="w-1 h-1 rounded-full bg-primary/50" />
                                                                {detail}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                <div className="ml-4 flex-shrink-0">
                                    {feature.status === 'not_installed' && !featureProgress && (
                                        <Button
                                            onClick={() => handleInstall(feature.id)}
                                            disabled={isInstalling}
                                            className="gap-2"
                                        >
                                            <Download className="w-4 h-4" />
                                            Install
                                        </Button>
                                    )}

                                    {feature.status === 'failed' && !featureProgress && (
                                        <Button
                                            variant="outline"
                                            onClick={() => handleInstall(feature.id)}
                                            disabled={isInstalling}
                                            className="gap-2"
                                        >
                                            <RefreshCw className="w-4 h-4" />
                                            Retry
                                        </Button>
                                    )}
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
