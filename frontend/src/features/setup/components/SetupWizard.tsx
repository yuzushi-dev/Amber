/**
 * SetupWizard Component
 * 
 * Displayed on first launch when optional features haven't been installed.
 * Allows users to select which ML features to install (local embeddings,
 * reranking, community detection, document processing).
 * 
 * Features are selected by default to encourage installation.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Package, Download, Check, Loader2, AlertCircle, AlertTriangle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

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
    features: Feature[];
    summary: {
        total: number;
        installed: number;
        installing: number;
        not_installed: number;
    };
}

interface SetupWizardProps {
    onComplete: () => void;
    apiBaseUrl?: string;
}

export const SetupWizard: React.FC<SetupWizardProps> = ({
    onComplete,
    apiBaseUrl = ''
}) => {
    const [status, setStatus] = useState<SetupStatus | null>(null);
    const [selectedFeatures, setSelectedFeatures] = useState<Set<string>>(new Set());
    const [isInstalling, setIsInstalling] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [showConfirmSkip, setShowConfirmSkip] = useState(false);

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

            // Check if any features are installing
            const installing = data.features.some(f => f.status === 'installing');
            setIsInstalling(installing);

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

    // Poll during installation
    useEffect(() => {
        if (!isInstalling) return;

        const interval = setInterval(async () => {
            const data = await fetchStatus();
            if (data && !data.features.some(f => f.status === 'installing')) {
                setIsInstalling(false);
            }
        }, 2000);

        return () => clearInterval(interval);
    }, [isInstalling, fetchStatus]);

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

    const handleInstall = async () => {
        if (selectedFeatures.size === 0) return;

        setIsInstalling(true);
        setError(null);

        try {
            // 30 minute timeout for large downloads (2GB @ 10Mbps ~= 27 mins)
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30 * 60 * 1000);

            const response = await fetch(`${apiBaseUrl}/api/v1/setup/install`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-API-Key': localStorage.getItem('api_key') || ''
                },
                body: JSON.stringify({ feature_ids: Array.from(selectedFeatures) }),
                signal: controller.signal,
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.detail || 'Installation failed');
            }

            // Start polling
            await fetchStatus();
        } catch (err: unknown) {
            const isAbort = err instanceof Error && err.name === 'AbortError';
            const errorMessage = isAbort
                ? 'Installation timed out. It may still be running in the background.'
                : (err instanceof Error ? err.message : 'Installation failed');

            setError(errorMessage);
            setIsInstalling(false);
        }
    };

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
                    <Badge variant="info" className="gap-1">
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
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
                <div className="flex items-center gap-3 text-muted-foreground">
                    <Loader2 className="w-6 h-6 animate-spin" />
                    Loading setup status...
                </div>
            </div>
        );
    }

    // If all features installed or setup complete, show continue
    const allInstalled = status.summary.installed === status.summary.total;

    // Confirmation dialog
    if (showConfirmSkip) {
        return (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
                <div className="bg-card border shadow-2xl rounded-xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-300">
                    <header className="p-6 border-b bg-amber-50 dark:bg-amber-900/20">
                        <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                                <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                            </div>
                            <div>
                                <h2 className="text-xl font-bold">Are you sure?</h2>
                                <p className="text-sm text-muted-foreground">
                                    Some features won't work properly
                                </p>
                            </div>
                        </div>
                    </header>

                    <div className="p-6 space-y-4">
                        <p className="text-muted-foreground">
                            Without these optional features, Amber will have limited functionality:
                        </p>
                        <ul className="space-y-2 text-sm">
                            <li className="flex items-start gap-2">
                                <span className="text-amber-500 mt-0.5">•</span>
                                <span><strong>Document Processing</strong> – Can't extract text from PDFs and Office files</span>
                            </li>
                            <li className="flex items-start gap-2">
                                <span className="text-amber-500 mt-0.5">•</span>
                                <span><strong>Local Embeddings</strong> – Slower search, requires API calls</span>
                            </li>
                            <li className="flex items-start gap-2">
                                <span className="text-amber-500 mt-0.5">•</span>
                                <span><strong>Reranking</strong> – Less accurate search results</span>
                            </li>
                        </ul>
                        <p className="text-sm text-muted-foreground">
                            You can install these later from Admin → Tuning.
                        </p>
                    </div>

                    <div className="p-6 border-t bg-muted/30 flex gap-3">
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
            <div className="bg-card border shadow-2xl rounded-xl w-full max-w-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-300 max-h-[90vh] flex flex-col">
                {/* Header */}
                <header className="p-6 border-b bg-muted/30 shrink-0">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                            <Package className="w-5 h-5 text-primary" />
                        </div>
                        <div>
                            <h2 className="text-xl font-bold">Setup Optional Features</h2>
                            <p className="text-sm text-muted-foreground">
                                These features enhance Amber's capabilities
                            </p>
                        </div>
                    </div>
                </header>

                {/* Content */}
                <div className="p-6 space-y-4 overflow-y-auto flex-1">
                    {error && (
                        <Alert variant="destructive" dismissible onDismiss={() => setError(null)}>
                            <AlertDescription>{error}</AlertDescription>
                        </Alert>
                    )}

                    {/* Restart Warning Banner */}
                    <Alert variant="warning">
                        <div className="font-medium">System Restart Required</div>
                        <AlertDescription className="mt-1">
                            After installing new features, you must restart the system for them to take effect.
                        </AlertDescription>
                    </Alert>

                    <div className="space-y-3">
                        {status.features.map(feature => {
                            const isSelected = selectedFeatures.has(feature.id);
                            const isClickable = feature.status === 'not_installed' && !isInstalling;

                            return (
                                <div
                                    key={feature.id}
                                    onClick={() => isClickable && handleFeatureToggle(feature.id)}
                                    className={`
                                        flex items-center gap-4 p-4 border rounded-lg transition-all
                                        ${isClickable ? 'cursor-pointer hover:border-primary/50' : ''}
                                        ${isSelected ? 'border-primary bg-primary/5' : 'border-border'}
                                        ${feature.status === 'installed'
                                            ? 'bg-green-100/10 dark:bg-green-900/20 border-green-200/50 dark:border-green-800/50 opacity-100'
                                            : ''
                                        }
                                        ${feature.status === 'installing' ? 'bg-blue-50 dark:bg-blue-950/40 border-blue-200 dark:border-blue-800' : ''}
                                    `}
                                >
                                    {/* Checkbox */}
                                    <div className="shrink-0">
                                        {feature.status === 'not_installed' ? (
                                            <div className={`
                                                w-5 h-5 rounded border-2 flex items-center justify-center transition-colors
                                                ${isSelected
                                                    ? 'bg-primary border-primary'
                                                    : 'border-muted-foreground/30'
                                                }
                                            `}>
                                                {isSelected && <Check className="w-3 h-3 text-primary-foreground" />}
                                            </div>
                                        ) : feature.status === 'installed' ? (
                                            <div className="w-5 h-5 rounded-full bg-green-500 flex items-center justify-center">
                                                <Check className="w-3 h-3 text-white" />
                                            </div>
                                        ) : feature.status === 'installing' ? (
                                            <Loader2 className="w-5 h-5 animate-spin text-blue-500" />
                                        ) : (
                                            <AlertCircle className="w-5 h-5 text-red-500" />
                                        )}
                                    </div>

                                    {/* Content */}
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                            <h3 className={`font-medium ${feature.status === 'installing'
                                                ? 'text-blue-900 dark:text-blue-100'
                                                : 'text-foreground'
                                                }`}>
                                                {feature.name}
                                            </h3>
                                            {getStatusBadge(feature)}
                                        </div>
                                        <p className={`text-sm mt-0.5 ${feature.status === 'installing'
                                            ? 'text-blue-700 dark:text-blue-300'
                                            : 'text-muted-foreground'
                                            }`}>
                                            {feature.description}
                                        </p>
                                        {feature.packages && feature.packages.length > 0 && (
                                            <div className={`mt-2 text-xs ${feature.status === 'installing'
                                                ? 'text-blue-600/80 dark:text-blue-400/80'
                                                : 'text-muted-foreground/80'
                                                }`}>
                                                <span className="font-medium">Packages: </span>
                                                {feature.packages.join(', ')}
                                            </div>
                                        )}
                                    </div>

                                    {/* Size indicator */}
                                    {feature.status === 'not_installed' && (
                                        <div className="shrink-0 text-right">
                                            <Download className="w-4 h-4 text-muted-foreground mx-auto mb-1" />
                                            <span className="text-xs text-muted-foreground">
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
                <div className="p-6 border-t bg-muted/30 flex gap-3 shrink-0">
                    <Button
                        variant="outline"
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
                            className="gap-2 h-12 px-6"
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
                            className="h-12 px-6"
                        >
                            Continue to App →
                        </Button>
                    ) : (
                        <Button
                            onClick={handleContinue}
                            className="h-12 px-6"
                        >
                            Continue →
                        </Button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default SetupWizard;
