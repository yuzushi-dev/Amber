import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { AvailableProviders } from '@/lib/api-admin'
import { Layers, CheckCircle, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'

interface EmbeddingCardProps {
    isSuperAdmin: boolean
    availableProviders: AvailableProviders | null
    embeddingProvider: string
    embeddingModel: string
    onProviderChange: (val: string) => void
    onModelChange: (val: string) => void
    onValidate: () => void
    validating: boolean
    getModelsForProvider: (provider: string) => string[]
}

export function EmbeddingCard({
    isSuperAdmin,
    availableProviders,
    embeddingProvider,
    embeddingModel,
    onProviderChange,
    onModelChange,
    onValidate,
    validating,
    getModelsForProvider,
}: EmbeddingCardProps) {
    const embeddingProviderModels = getModelsForProvider(embeddingProvider)

    // List of providers from API
    const providersForSelect = availableProviders?.embedding_providers || []

    // Models available for current embedding provider
    const modelsForSelect = embeddingProviderModels || []

    return (
        <Card className="border-white/5 bg-background/40 backdrop-blur-md shadow-xl hover:bg-background/50 transition-[background-color,border-color,box-shadow] duration-500 ease-out overflow-hidden group">
            <CardHeader className="relative p-6 border-b border-white/5 bg-foreground/5">
                <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-50" />
                <div className="relative z-10 space-y-1.5">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-primary/10 text-primary ring-1 ring-primary/20">
                            <Layers className="w-5 h-5" />
                        </div>
                        <CardTitle className="font-display text-2xl font-bold tracking-tight">Embedding Settings</CardTitle>
                    </div>
                    <CardDescription className="text-muted-foreground/70 font-medium">
                        Configure the embedding provider and model for vector generation.
                    </CardDescription>
                </div>
            </CardHeader>
            <CardContent className="p-8 space-y-8">
                <div className="grid gap-8 md:grid-cols-2">
                    <div className="space-y-3">
                        <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                            EMBEDDING PROVIDER
                        </Label>
                        <div className="flex gap-2">
                            <Select
                                value={embeddingProvider}
                                onValueChange={onProviderChange}
                                disabled={!isSuperAdmin}
                            >
                            <SelectTrigger className="bg-foreground/5 border-border h-12 focus:ring-primary/50 hover:bg-foreground/10 transition-colors">
                                <SelectValue placeholder="Select Provider" />
                            </SelectTrigger>
                            <SelectContent className="bg-background/95 backdrop-blur-xl border-border">
                                    {providersForSelect.map(p => (
                                        <SelectItem key={p.name} value={p.name} className="focus:bg-primary/20">
                                            {p.label || p.name}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                            <Button
                                variant="outline"
                                size="icon"
                                className={cn(
                                    "h-12 w-12 transition-colors shrink-0",
                                    validating && "border-primary text-primary"
                                )}
                                onClick={onValidate}
                                disabled={validating || !isSuperAdmin}
                                title="Check connection"
                            >
                                {validating ? (
                                    <RotateCcw className="h-4 w-4 animate-spin" />
                                ) : (
                                    <CheckCircle className="h-4 w-4 text-primary" />
                                )}
                            </Button>
                        </div>
                    </div>

                    <div className="space-y-3">
                        <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                            EMBEDDING MODEL
                        </Label>
                        <Select
                            value={embeddingModel}
                            onValueChange={onModelChange}
                            disabled={!isSuperAdmin || !embeddingProvider}
                        >
                            <SelectTrigger className="bg-foreground/5 border-border h-12 focus:ring-primary/50 hover:bg-foreground/10 transition-colors">
                                <SelectValue placeholder="Select Model" />
                            </SelectTrigger>
                            <SelectContent className="bg-background/95 backdrop-blur-xl border-border">
                                {modelsForSelect.map(m => (
                                    <SelectItem key={m} value={m} className="focus:bg-primary/20">{m}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </div>
            </CardContent>
        </Card>
    )
}
