import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { AvailableProviders } from '@/lib/api-admin'
import { Sparkles } from 'lucide-react'

interface GlobalDefaultsCardProps {
    isSuperAdmin: boolean
    availableProviders: AvailableProviders | null
    defaultProvider: string
    defaultModel: string
    defaultTemperature: number | null
    defaultSeed: number | null
    onProviderChange: (val: string) => void
    onModelChange: (val: string) => void
    onTemperatureChange: (val: number | null) => void
    onSeedChange: (val: number | null) => void
    getModelsForProvider: (provider: string) => string[]
}

export function GlobalDefaultsCard({
    isSuperAdmin,
    availableProviders,
    defaultProvider,
    defaultModel,
    defaultTemperature,
    defaultSeed,
    onProviderChange,
    onModelChange,
    onTemperatureChange,
    onSeedChange,
    getModelsForProvider,
}: GlobalDefaultsCardProps) {
    const defaultProviderModels = getModelsForProvider(defaultProvider)

    // List of providers from API
    const providersForSelect = availableProviders?.llm_providers || []

    // Models available for current default provider
    const modelsForSelect = defaultProviderModels || []

    // Convert defaultTemperature and defaultSeed to non-null for Slider, providing defaults if null
    const temperatureValue = defaultTemperature ?? 0.5; // Default temperature if null
    const seedValue = defaultSeed ?? 0; // Default seed if null

    return (
        <Card className="border-white/5 bg-background/40 backdrop-blur-md shadow-xl hover:bg-background/50 transition-all duration-500 overflow-hidden group">
            <CardHeader className="relative p-6 border-b border-white/5 bg-white/5">
                <div className="absolute inset-0 bg-gradient-to-br from-amber-500/5 to-transparent opacity-50" />
                <div className="relative z-10 space-y-1.5">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-amber-500/10 text-amber-500 ring-1 ring-amber-500/20">
                            <Sparkles className="w-5 h-5" />
                        </div>
                        <CardTitle className="font-display text-2xl font-bold tracking-tight">Global Defaults</CardTitle>
                    </div>
                    <CardDescription className="text-muted-foreground/70 font-medium">
                        Apply these settings to all steps unless specifically overridden.
                    </CardDescription>
                </div>
            </CardHeader>
            <CardContent className="p-8 space-y-8">
                <div className="grid gap-8 md:grid-cols-2">
                    <div className="space-y-3">
                        <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                            PROVIDER
                        </Label>
                        <Select
                            value={defaultProvider}
                            onValueChange={onProviderChange}
                            disabled={!isSuperAdmin}
                        >
                            <SelectTrigger className="bg-white/5 border-white/10 h-12 focus:ring-amber-500/50 hover:bg-white/10 transition-colors">
                                <SelectValue placeholder="Select Provider" />
                            </SelectTrigger>
                            <SelectContent className="bg-background/95 backdrop-blur-xl border-white/10">
                                {providersForSelect.map(p => (
                                    <SelectItem key={p.name} value={p.name} className="focus:bg-amber-500/20">
                                        {p.label || p.name}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="space-y-3">
                        <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                            MODEL
                        </Label>
                        <Select
                            value={defaultModel}
                            onValueChange={onModelChange}
                            disabled={!isSuperAdmin || !defaultProvider}
                        >
                            <SelectTrigger className="bg-white/5 border-white/10 h-12 focus:ring-amber-500/50 hover:bg-white/10 transition-colors">
                                <SelectValue placeholder="Select Model" />
                            </SelectTrigger>
                            <SelectContent className="bg-background/95 backdrop-blur-xl border-white/10">
                                {modelsForSelect.map(m => (
                                    <SelectItem key={m} value={m} className="focus:bg-amber-500/20">{m}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </div>

                <div className="grid gap-12 md:grid-cols-2 pt-4 border-t border-white/5 pt-8">
                    <div className="space-y-5">
                        <div className="flex items-center justify-between">
                            <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                                TEMPERATURE
                            </Label>
                            <span className="text-xs font-mono font-bold text-amber-500 bg-amber-500/10 px-2.5 py-1 rounded border border-amber-500/20 shadow-[0_0_10px_rgba(245,158,11,0.1)]">
                                {temperatureValue.toFixed(2)}
                            </span>
                        </div>
                        <Slider
                            value={[temperatureValue]}
                            min={0}
                            max={2}
                            step={0.01}
                            onValueChange={([val]) => onTemperatureChange(val)}
                            className="py-2"
                            disabled={!isSuperAdmin}
                        />
                    </div>

                    <div className="space-y-5">
                        <div className="flex items-center justify-between">
                            <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                                RANDOM SEED
                            </Label>
                            <span className="text-xs font-mono font-bold text-amber-500 bg-amber-500/10 px-2.5 py-1 rounded border border-amber-500/20 shadow-[0_0_10px_rgba(245,158,11,0.1)]">
                                {seedValue}
                            </span>
                        </div>
                        <Slider
                            value={[seedValue]}
                            min={0}
                            max={100000}
                            step={1}
                            onValueChange={([val]) => onSeedChange(val)}
                            className="py-2"
                            disabled={!isSuperAdmin}
                        />
                    </div>
                </div>
            </CardContent>
        </Card>
    )
}
