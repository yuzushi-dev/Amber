/**
 * SetupWizard Component
 * 
 * Orchestrates the application setup process:
 * 1. Database Initialization (System Core)
 * 2. Optional Feature Installation (Modules)
 */

import React, { useState } from 'react';
import { DatabaseSetup } from './DatabaseSetup';
import { FeatureSetup } from './FeatureSetup';
import { Loader2 } from 'lucide-react';

interface SetupWizardProps {
    onComplete: () => void;
    apiBaseUrl?: string;
}

type SetupStep = 'loading' | 'database' | 'features';

export const SetupWizard: React.FC<SetupWizardProps> = ({
    onComplete,
    apiBaseUrl = ''
}) => {
    const [step, setStep] = useState<SetupStep>('database');

    const handleDatabaseComplete = () => {
        setStep('features');
    };

    const handleFeaturesComplete = () => {
        onComplete();
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
            <div className="bg-card border shadow-2xl rounded-xl w-full max-w-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-300 h-[600px] flex flex-col relative">

                {step === 'loading' && (
                    <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                        <Loader2 className="w-8 h-8 animate-spin mb-4" />
                        <div>Initializing Wizard...</div>
                    </div>
                )}

                {step === 'database' && (
                    <DatabaseSetup
                        onComplete={handleDatabaseComplete}
                        apiBaseUrl={apiBaseUrl}
                    />
                )}

                {step === 'features' && (
                    <FeatureSetup
                        onComplete={handleFeaturesComplete}
                        apiBaseUrl={apiBaseUrl}
                    />
                )}
            </div>
        </div>
    );
};

export default SetupWizard;
