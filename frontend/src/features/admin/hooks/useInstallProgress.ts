/**
 * useInstallProgress Hook
 * =======================
 * 
 * Custom hook for streaming installation progress via SSE.
 * Used by OptionalFeaturesManager and SetupWizard.
 */

import { useState, useCallback, useRef } from 'react';

export interface InstallProgress {
    featureId: string;
    featureName: string;
    phase: 'downloading' | 'installing' | 'verifying' | 'complete' | 'failed';
    progress: number; // 0-100
    message: string;
    current: number;
    total: number;
}

export interface UseInstallProgressReturn {
    /** Start installation with SSE progress tracking */
    startInstall: (featureIds: string[]) => void;
    /** Current progress for each feature */
    progress: Record<string, InstallProgress>;
    /** Whether installation is in progress */
    isInstalling: boolean;
    /** Stop the current installation (closes SSE connection) */
    stop: () => void;
    /** Error message if any */
    error: string | null;
}

export function useInstallProgress(
    onComplete?: () => void
): UseInstallProgressReturn {
    const [progress, setProgress] = useState<Record<string, InstallProgress>>({});
    const [isInstalling, setIsInstalling] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const eventSourceRef = useRef<EventSource | null>(null);

    const stop = useCallback(() => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
        }
        setIsInstalling(false);
    }, []);

    const startInstall = useCallback((featureIds: string[]) => {
        if (featureIds.length === 0) return;

        // Close any existing connection
        stop();

        setIsInstalling(true);
        setError(null);
        setProgress({});

        const apiKey = localStorage.getItem('api_key') || '';
        const idsParam = encodeURIComponent(featureIds.join(','));
        const url = `/api/v1/setup/install/events?feature_ids=${idsParam}&api_key=${encodeURIComponent(apiKey)}`;

        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        eventSource.addEventListener('progress', (event) => {
            try {
                const data = JSON.parse(event.data) as {
                    feature_id: string;
                    feature_name: string;
                    phase: InstallProgress['phase'];
                    progress: number;
                    message: string;
                    current: number;
                    total: number;
                };

                setProgress((prev) => ({
                    ...prev,
                    [data.feature_id]: {
                        featureId: data.feature_id,
                        featureName: data.feature_name,
                        phase: data.phase,
                        progress: data.progress,
                        message: data.message,
                        current: data.current,
                        total: data.total,
                    },
                }));
            } catch (e) {
                console.error('Failed to parse progress event:', e);
            }
        });

        eventSource.addEventListener('complete', () => {
            stop();
            onComplete?.();
        });

        eventSource.addEventListener('error', (event) => {
            console.error('SSE error:', event);
            try {
                // Try to parse error data if available
                const errorEvent = event as MessageEvent;
                if (errorEvent.data) {
                    const data = JSON.parse(errorEvent.data);
                    setError(data.error || 'Installation failed');
                }
            } catch {
                setError('Connection lost. Installation may still be running.');
            }
            stop();
        });

        eventSource.onerror = () => {
            // Only set error if we haven't already completed
            if (eventSourceRef.current) {
                setError('Connection lost. Check status and try again.');
                stop();
            }
        };
    }, [stop, onComplete]);

    return {
        startInstall,
        progress,
        isInstalling,
        stop,
        error,
    };
}

export default useInstallProgress;
