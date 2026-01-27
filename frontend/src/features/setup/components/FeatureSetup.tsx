/**
 * FeatureSetup Component
 * 
 * Allows users to select which ML features to install.
 * Extracted from SetupWizard.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Package, Download, Check, Loader2, AlertCircle, AlertTriangle, ChevronRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useInstallProgress } from '@/features/admin/hooks/useInstallProgress';
import { AnimatedProgress } from '@/components/ui/animated-progress';

interface Feature {
    id: string;
    name: string;
    description: string;
    size_mb: number;
    status: 'not_installed' | 'installing' | 'installed' | 'failed';
    error_message?: string;
    packages?: string[];
}

interface SetupStatus {
    initialized: boolean;
    setup_complete: boolean;
    db_migration_needed: boolean;
    features: Feature[];
    summary: {
        total: number;
        installed: number;
        installing: number;
        not_installed: number;
    };
}

interface FeatureSetupProps {
    onComplete: () => void;
    apiBaseUrl?: string;
}

export const FeatureSetup: React.FC<FeatureSetupProps> = ({
    onComplete,
    apiBaseUrl = ''
}) => {
    const [status, setStatus] = useState<SetupStatus | null>(null);
    const [selectedFeatures, setSelectedFeatures] = useState<Set<string>>(new Set());
    const [error, setError] = useState<string | null>(null);
    const [showConfirmSkip, setShowConfirmSkip] = useState(false);

    // SSE progress hook
    const { startInstall, progress, isInstalling, error: installError } = useInstallProgress(() => {
        // On complete, refresh status
        fetchStatus();
    });

    const fetchStatus = useCallback(async () => {
        try {
            const apiKey = localStorage.getItem('api_key') || '';
            const response = await fetch(`${apiBaseUrl}/api/v1/setup/status`, {
                headers: { 'X-API-Key': apiKey }
            });
            if (!response.ok) throw new Error('Failed to fetch setup status');
            const data: SetupStatus = await response.json();
            setStatus(data);

            // Select all not_installed features by default
            const notInstalled = data.features
                .filter(f => f.status === 'not_installed')
                .map(f => f.id);
            setSelectedFeatures(new Set(notInstalled));

            return data;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Unknown error');
            return null;
        }
    }, [apiBaseUrl]);

    useEffect(() => {
        const init = async () => {
            const data = await fetchStatus();

            // Auto-skip if all features installed
            if (data && data.features.every(f => f.status === 'installed')) {
                onComplete();
            }
        };
        init();
    }, [fetchStatus, onComplete]);

    // Poll during installation to refresh status
    useEffect(() => {
        if (!isInstalling) return;

        const interval = setInterval(async () => {
            await fetchStatus();
        }, 5000);

        return () => clearInterval(interval);
    }, [isInstalling, fetchStatus]);

    // Combine SSE error with local error
    useEffect(() => {
        if (installError) {
            setError(installError);
        }
    }, [installError]);

    const handleFeatureToggle = (featureId: string) => {
        if (isInstalling) return;

        const newSelected = new Set(selectedFeatures);
        if (newSelected.has(featureId)) {
            newSelected.delete(featureId);
        } else {
            newSelected.add(featureId);
        }
        setSelectedFeatures(newSelected);
    };

    const handleInstall = () => {
        if (selectedFeatures.size === 0) return;
        setError(null);
        startInstall(Array.from(selectedFeatures));
    };

    // Helper to get progress for a feature
    const getFeatureProgress = (featureId: string) => progress[featureId];

    const handleSkipAttempt = () => {
        // If no features selected, show confirmation
        if (selectedFeatures.size === 0) {
            setShowConfirmSkip(true);
        } else {
            // Just skip without installing selected
            setShowConfirmSkip(true);
        }
    };

    const handleConfirmSkip = async () => {
        try {
            const response = await fetch(`${apiBaseUrl}/api/v1/setup/skip`, {
                method: 'POST',
                headers: { 'X-API-Key': localStorage.getItem('api_key') || '' }
            });

            if (!response.ok) throw new Error('Failed to skip setup');

            onComplete();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to skip setup');
        }
    };

    const handleContinue = async () => {
        try {
            // Ensure backend knows setup is complete
            await fetch(`${apiBaseUrl}/api/v1/setup/skip`, {
                method: 'POST',
                headers: { 'X-API-Key': localStorage.getItem('api_key') || '' }
            });
        } catch (err) {
            console.error('Failed to mark setup complete', err);
        }
        onComplete();
    };

    // Calculate selected size
    const selectedSize = status?.features
        .filter(f => selectedFeatures.has(f.id))
        .reduce((acc, f) => acc + f.size_mb, 0) || 0;

    const formatSize = (mb: number) => {
        if (mb >= 1000) {
            return `${(mb / 1000).toFixed(1)} GB`;
        }
        return `${mb} MB`;
    };

    const getStatusBadge = (feature: Feature) => {
        switch (feature.status) {
            case 'installed':
                return (
                    <Badge variant="success" className="gap-1">
                        <Check className="w-3 h-3" />
                        Installed
                    </Badge>
                );
            case 'installing':
                return (
                    <Badge variant="default" className="gap-1">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        Installing...
                    </Badge>
                );
            case 'failed':
                return (
                    <Badge variant="destructive" className="gap-1" title={feature.error_message}>
                        <AlertCircle className="w-3 h-3" />
                        Failed
                    </Badge>
                );
            default:
                return (
                    <span className="text-xs text-muted-foreground">
                        {formatSize(feature.size_mb)}
                    </span>
                );
        }
    };

    if (!status) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-muted-foreground">
                <Loader2 className="w-8 h-8 animate-spin mb-4 text-primary" />
                <div>Loading optional components...</div>
            </div>
        );
    }

    // If all features installed or setup complete, show continue
    const allInstalled = status.summary.installed === status.summary.total;

    // Confirmation dialog
    if (showConfirmSkip) {
        return (
            <div className="h-full flex flex-col items-center justify-center p-6 animate-in fade-in zoom-in-95 duration-300">
                <div className="w-full max-w-md">
                    <header className="mb-6 bg-warning-muted/40 p-4 rounded-lg border border-warning/30">
                        <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-full bg-warning-muted flex items-center justify-center">
                                <AlertTriangle className="w-4 h-4 text-warning" />
                            </div>
                            <div>
                                <h2 className="font-bold text-lg">Are you sure?</h2>
                                <p className="text-xs text-muted-foreground">
                                    Some features won't work properly
                                </p>
                            </div>
                        </div>
                    </header>

                    <div className="space-y-4 mb-6">
                        <p className="text-muted-foreground text-sm">
                            Without these optional features, Amber will have limited functionality:
                        </p>
                        <ul className="space-y-2 text-sm bg-muted/30 p-4 rounded-lg">
                            <li className="flex items-start gap-2">
                                <span className="text-warning mt-0.5">•</span>
                                <span><strong>Document Processing</strong> – Can't extract text from PDFs and Office files</span>
                            </li>
                            <li className="flex items-start gap-2">
                                <span className="text-warning mt-0.5">•</span>
                                <span><strong>Local Embeddings</strong> – Slower search, requires API calls</span>
                            </li>
                            <li className="flex items-start gap-2">
                                <span className="text-warning mt-0.5">•</span>
                                <span><strong>Reranking</strong> – Less accurate search results</span>
                            </li>
                        </ul>
                        <p className="text-xs text-muted-foreground text-center">
                            You can install these later from Admin → Tuning.
                        </p>
                    </div>

                    <div className="flex gap-3">
                        <Button
                            onClick={() => setShowConfirmSkip(false)}
                            className="flex-1"
                        >
                            Go Back & Install
                        </Button>
                        <Button
                            variant="outline"
                            onClick={handleConfirmSkip}
                            className="flex-1"
                        >
                            Skip Anyway
                        </Button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full animate-in fade-in duration-500">
            {/* Header */}
            <div className="p-6 border-b bg-muted/20">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                        <Package className="w-5 h-5 text-primary" />
                    </div>
                    <div>
                        <h2 className="text-xl font-bold tracking-tight">Optional Modules</h2>
                        <p className="text-sm text-muted-foreground">
                            Enhance capabilities with local AI models
                        </p>
                    </div>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 p-6 space-y-4 overflow-y-auto">
                {error && (
                    <Alert variant="destructive" dismissible onDismiss={() => setError(null)}>
                        <AlertDescription>{error}</AlertDescription>
                    </Alert>
                )}

                {/* Restart Warning Banner */}
                <Alert variant="warning" showIcon={false} className="py-2 px-3">
                    <AlertDescription className="text-xs flex items-center gap-2">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                        System restart may be required after installation
                    </AlertDescription>
                </Alert>

                <div className="space-y-3">
                    {status.features.map(feature => {
                        const isSelected = selectedFeatures.has(feature.id);
                        const isClickable = feature.status === 'not_installed' && !isInstalling;
                        const featureProgress = getFeatureProgress(feature.id);

                        return (
                            <div
                                key={feature.id}
                                onClick={() => isClickable && handleFeatureToggle(feature.id)}
                                className={`
                                    flex items-center gap-4 p-4 border rounded-lg transition-[background-color,border-color,box-shadow] duration-200 ease-out relative overflow-hidden group
                                    ${isClickable ? 'cursor-pointer hover:border-primary/50 hover:bg-muted/30' : ''}
                                    ${isSelected ? 'border-primary bg-primary/5' : 'border-border bg-card'}
                                    ${feature.status === 'installed'
                                        ? '!bg-success-muted !border-success/30'
                                        : ''
                                    }
                                    ${feature.status === 'installing' || featureProgress
                                        ? '!bg-info-muted/60 !border-info/40 shadow-glow-info ring-1 ring-info/30'
                                        : ''
                                    }
                                `}
                            >
                                {/* Checkbox */}
                                <div className="shrink-0">
                                    {feature.status === 'not_installed' && !featureProgress ? (
                                        <div className={`
                                            w-5 h-5 rounded border-2 flex items-center justify-center transition-colors
                                            ${isSelected
                                                ? 'bg-primary border-primary'
                                                : 'border-muted-foreground/30 group-hover:border-primary/50'
                                            }
                                        `}>
                                            {isSelected && <Check className="w-3 h-3 text-primary-foreground" />}
                                        </div>
                                    ) : feature.status === 'installed' ? (
                                        <div className="w-5 h-5 rounded-full bg-success flex items-center justify-center">
                                            <Check className="w-3 h-3 text-success-foreground" />
                                        </div>
                                    ) : featureProgress || feature.status === 'installing' ? (
                                        <Loader2 className="w-5 h-5 animate-spin text-primary" />
                                    ) : (
                                        <AlertCircle className="w-5 h-5 text-destructive" />
                                    )}
                                </div>

                                {/* Content */}
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                        <h3 className="font-medium text-foreground">
                                            {feature.name}
                                        </h3>
                                        {getStatusBadge(feature)}
                                    </div>
                                    <p className="text-sm mt-1 text-foreground/80 font-medium leading-relaxed">
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
                                            <p className="text-xs text-foreground/80 truncate mt-2 font-mono ml-0.5">
                                                {featureProgress.message}
                                            </p>
                                        </div>
                                    )}

                                    {feature.packages && feature.packages.length > 0 && !featureProgress && (
                                        <div className="mt-3 text-xs text-foreground/60 leading-relaxed bg-background/50 p-2 rounded border border-border/50">
                                            <span className="font-semibold text-foreground/80">Packages: </span>
                                            {feature.packages.join(', ')}
                                        </div>
                                    )}
                                </div>

                                {/* Size indicator */}
                                {feature.status === 'not_installed' && !featureProgress && (
                                    <div className="shrink-0 text-right">
                                        <Download className="w-4 h-4 text-muted-foreground mx-auto mb-1 group-hover:text-primary transition-colors" />
                                        <span className="text-xs text-muted-foreground group-hover:text-foreground/80">
                                            {formatSize(feature.size_mb)}
                                        </span>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>

                {/* Summary */}
                {selectedFeatures.size > 0 && (
                    <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg text-sm">
                        <span className="text-muted-foreground">
                            {selectedFeatures.size} feature{selectedFeatures.size !== 1 ? 's' : ''} selected
                        </span>
                        <span className="font-medium">
                            Total: {formatSize(selectedSize)}
                        </span>
                    </div>
                )}
            </div>

            {/* Footer */}
            <div className="p-6 border-t bg-muted/20 flex gap-3 shrink-0">
                <Button
                    variant="ghost"
                    onClick={handleSkipAttempt}
                    disabled={isInstalling}
                    className="h-12 px-6"
                >
                    Skip for now
                </Button>

                <div className="flex-1" />

                {selectedFeatures.size > 0 && !isInstalling && !allInstalled ? (
                    <Button
                        onClick={handleInstall}
                        className="gap-2 h-12 px-6 shadow-lg shadow-primary/20"
                    >
                        <Download className="w-4 h-4" />
                        Install Selected ({selectedFeatures.size})
                    </Button>
                ) : isInstalling ? (
                    <Button
                        disabled
                        className="gap-2 h-12 px-6 opacity-50"
                    >
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Installing...
                    </Button>
                ) : allInstalled ? (
                    <Button
                        onClick={handleContinue}
                        className="h-12 px-6 gap-2"
                    >
                        Continue to App
                        <ChevronRight className="w-4 h-4" />
                    </Button>
                ) : (
                    <Button
                        onClick={handleContinue}
                        className="h-12 px-6 gap-2"
                    >
                        Continue
                        <ChevronRight className="w-4 h-4" />
                    </Button>
                )}
            </div>
        </div>
    );
};
