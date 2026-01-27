import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Badge } from '@/components/ui/badge'

import { LlmStepMeta, LlmStepOverride, AvailableProviders } from '@/lib/api-admin'
import { RotateCcw } from 'lucide-react'

interface StepConfigDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    step: LlmStepMeta | null
    override: LlmStepOverride
    defaultProvider: string
    defaultModel: string
    availableProviders: AvailableProviders | null
    isSuperAdmin: boolean
    onChange: (changes: LlmStepOverride) => void
    getModelsForProvider: (provider: string) => string[]
}

const INHERIT_VALUE = '__inherit__'

export function StepConfigDialog({
    open,
    onOpenChange,
    step,
    override,
    defaultProvider,
    defaultModel,
    availableProviders,
    isSuperAdmin,
    onChange,
    getModelsForProvider
}: StepConfigDialogProps) {
    if (!step) return null

    // Helper to handle partial updates
    const handleChange = (key: keyof LlmStepOverride, value: any) => {
        onChange({ [key]: value })
    }


    // Models available for the CURRENTLY SELECTED provider (if override) or default provider (if inherit)
    // Actually, if we select "Inherit", we don't show model selector usually, but if we select specific provider...

    // Logic:
    // 1. Provider Select: can be "Inherit Default" or specific provider.
    // 2. Model Select: dependent on selected provider.

    const selectedProviderValue = override.provider ?? INHERIT_VALUE
    const effectiveProvider = override.provider || defaultProvider
    const providerModels = getModelsForProvider(effectiveProvider)

    const stepTemperature = override.temperature ?? step.default_temperature ?? 1.0
    const stepSeed = override.seed ?? step.default_seed ?? 42

    const handleReset = () => {
        // Clear all overrides for this step
        onChange({ provider: null, model: null, temperature: null, seed: null })
    }

    const hasOverrides = override.provider !== null || override.model !== null || override.temperature !== null || override.seed !== null

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[500px] border-white/10 bg-background/95 backdrop-blur-xl shadow-2xl p-0 overflow-hidden">
                <DialogHeader className="p-6 pb-4 bg-white/5 border-b border-white/5">
                    <div className="flex items-center justify-between mb-1">
                        <DialogTitle className="font-display text-2xl font-bold tracking-tight">
                            Configure Step
                        </DialogTitle>
                        <Badge variant="outline" className="text-[10px] uppercase tracking-widest bg-white/5 text-muted-foreground border-white/10">
                            {step.feature}
                        </Badge>
                    </div>
                    <DialogDescription className="text-muted-foreground/80 font-medium">
                        {step.label}
                    </DialogDescription>
                    <p className="text-xs text-muted-foreground/60 mt-2 leading-relaxed italic">
                        {step.description}
                    </p>
                </DialogHeader>

                <div className="grid gap-6 p-6 pt-8">
                    {/* Provider Selection */}
                    <div className="space-y-3">
                        <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                            Provider
                        </Label>
                        <Select
                            value={selectedProviderValue}
                            onValueChange={(val) => {
                                const newVal = val === INHERIT_VALUE ? null : val
                                onChange({
                                    provider: newVal,
                                    // Reset model if provider changes to prevent invalid model for provider
                                    model: null
                                })
                            }}
                            disabled={!isSuperAdmin}
                        >
                            <SelectTrigger className="bg-white/5 border-white/10 h-11 focus:ring-amber-500/50 hover:bg-white/10 transition-colors">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent className="bg-background/95 backdrop-blur-xl border-white/10">
                                <SelectItem value={INHERIT_VALUE} className="focus:bg-amber-500/20">
                                    <div className="flex items-center gap-2">
                                        <span className="font-medium text-muted-foreground">Inherit Default</span>
                                        <Badge variant="outline" className="text-[8px] opacity-50 border-white/10">
                                            {defaultProvider}
                                        </Badge>
                                    </div>
                                </SelectItem>
                                {availableProviders?.llm_providers.map(p => (
                                    <SelectItem key={p.name} value={p.name} className="focus:bg-amber-500/20">
                                        {p.label || p.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    {/* Model Selection */}
                    <div className="space-y-3">
                        <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                            Model Selection
                        </Label>
                        <Select
                            value={override.model ?? INHERIT_VALUE}
                            onValueChange={(val) => handleChange('model', val === INHERIT_VALUE ? null : val)}
                            disabled={!isSuperAdmin}
                        >
                            <SelectTrigger className="bg-white/5 border-white/10 h-11 focus:ring-amber-500/50 hover:bg-white/10 transition-colors">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent className="bg-background/95 backdrop-blur-xl border-white/10">
                                <SelectItem value={INHERIT_VALUE} className="focus:bg-amber-500/20">
                                    <div className="flex items-center gap-2">
                                        <span className="font-medium text-muted-foreground">Inherit Default</span>
                                        {!override.provider && (
                                            <Badge variant="outline" className="text-[8px] opacity-50 border-white/10">
                                                {defaultModel}
                                            </Badge>
                                        )}
                                    </div>
                                </SelectItem>
                                {providerModels.map(m => (
                                    <SelectItem key={m} value={m} className="focus:bg-amber-500/20">
                                        {m}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="grid gap-8 py-4 border-t border-white/5 pt-8 mt-2">
                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                                    TEMPERATURE
                                </Label>
                                <span className="text-xs font-mono font-bold text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                                    {stepTemperature.toFixed(2)}
                                </span>
                            </div>
                            <Slider
                                value={[stepTemperature]}
                                min={0}
                                max={2}
                                step={0.01}
                                onValueChange={([val]) => handleChange('temperature', val)}
                                className="py-2"
                                disabled={!isSuperAdmin}
                            />
                        </div>

                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                                    RANDOM SEED
                                </Label>
                                <span className="text-xs font-mono font-bold text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
                                    {stepSeed}
                                </span>
                            </div>
                            <Slider
                                value={[stepSeed]}
                                min={0}
                                max={100}
                                step={1}
                                onValueChange={([val]) => handleChange('seed', val)}
                                className="py-2"
                                disabled={!isSuperAdmin}
                            />
                        </div>
                    </div>
                </div>

                <DialogFooter className="p-6 bg-white/5 border-t border-white/5 flex items-center !justify-between gap-4">
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={handleReset}
                        disabled={!hasOverrides || !isSuperAdmin}
                        className="text-muted-foreground hover:text-amber-500 hover:bg-amber-500/10 h-10 px-4 transition-all"
                    >
                        <RotateCcw className="w-4 h-4 mr-2" />
                        Reset All
                    </Button>
                    <Button
                        onClick={() => onOpenChange(false)}
                        className="bg-amber-500 hover:bg-amber-600 text-black font-bold h-10 px-8 shadow-lg shadow-amber-500/20 transition-all active:scale-95"
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
