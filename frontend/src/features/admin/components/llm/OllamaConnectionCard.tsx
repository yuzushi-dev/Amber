import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { providersApi } from '@/lib/api-admin'
import { Server, CheckCircle, XCircle, RotateCcw, Save } from 'lucide-react'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

interface OllamaConnectionCardProps {
    isSuperAdmin: boolean
    ollamaBaseUrl: string
    onUrlChange: (url: string) => void
    onUrlSave: (url: string) => void
    saving: boolean
}

export function OllamaConnectionCard({
    isSuperAdmin,
    ollamaBaseUrl,
    onUrlChange,
    onUrlSave,
    saving,
}: OllamaConnectionCardProps) {
    const [testing, setTesting] = useState(false)
    const [testResult, setTestResult] = useState<{
        available: boolean
        label: string
        error: string | null
        llm_models: string[]
        embedding_models: string[]
    } | null>(null)

    const handleTest = async () => {
        if (!ollamaBaseUrl.trim()) {
            toast.error('Enter a URL first')
            return
        }
        try {
            setTesting(true)
            setTestResult(null)
            const result = await providersApi.testOllamaConnection(ollamaBaseUrl.trim())
            setTestResult(result)
            if (result.available) {
                const total = result.llm_models.length + result.embedding_models.length
                toast.success(`Connected to ${result.label} — ${total} model${total !== 1 ? 's' : ''} found`)
            } else {
                toast.error(result.error || 'Connection failed')
            }
        } catch {
            toast.error('Failed to test connection')
        } finally {
            setTesting(false)
        }
    }

    const handleSave = () => {
        onUrlSave(ollamaBaseUrl.trim())
    }

    return (
        <Card className="border-white/5 bg-background/40 backdrop-blur-md shadow-xl hover:bg-background/50 transition-[background-color,border-color,box-shadow] duration-500 ease-out overflow-hidden group">
            <CardHeader className="relative p-6 border-b border-white/5 bg-foreground/5">
                <div className="absolute inset-0 bg-gradient-to-br from-orange-500/5 to-transparent opacity-50" />
                <div className="relative z-10 space-y-1.5">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-orange-500/10 text-orange-500 ring-1 ring-orange-500/20">
                            <Server className="w-5 h-5" />
                        </div>
                        <CardTitle className="font-display text-2xl font-bold tracking-tight">Ollama Connection</CardTitle>
                        {testResult && (
                            <Badge
                                variant={testResult.available ? 'default' : 'destructive'}
                                className={cn(
                                    'ml-auto text-xs',
                                    testResult.available && 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                                )}
                            >
                                {testResult.available ? testResult.label : 'Unreachable'}
                            </Badge>
                        )}
                    </div>
                    <CardDescription className="text-muted-foreground/70 font-medium">
                        Set the Ollama server URL. Supports local and remote instances.
                    </CardDescription>
                </div>
            </CardHeader>
            <CardContent className="p-8 space-y-6">
                <div className="space-y-3">
                    <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                        OLLAMA BASE URL
                    </Label>
                    <div className="flex gap-2">
                        <Input
                            value={ollamaBaseUrl}
                            onChange={(e) => onUrlChange(e.target.value)}
                            placeholder="http://localhost:11434/v1"
                            disabled={!isSuperAdmin}
                            className="bg-foreground/5 border-border h-12 focus:ring-primary/50 hover:bg-foreground/10 transition-colors font-mono text-sm"
                        />
                        <Button
                            variant="outline"
                            size="icon"
                            className={cn(
                                "h-12 w-12 transition-colors shrink-0",
                                testing && "border-orange-500 text-orange-500"
                            )}
                            onClick={handleTest}
                            disabled={testing || !isSuperAdmin || !ollamaBaseUrl.trim()}
                            title="Test connection"
                        >
                            {testing ? (
                                <RotateCcw className="h-4 w-4 animate-spin" />
                            ) : testResult?.available ? (
                                <CheckCircle className="h-4 w-4 text-emerald-500" />
                            ) : testResult && !testResult.available ? (
                                <XCircle className="h-4 w-4 text-destructive" />
                            ) : (
                                <CheckCircle className="h-4 w-4 text-orange-500" />
                            )}
                        </Button>
                        <Button
                            variant="outline"
                            size="icon"
                            className="h-12 w-12 transition-colors shrink-0"
                            onClick={handleSave}
                            disabled={saving || !isSuperAdmin || !ollamaBaseUrl.trim()}
                            title="Save URL"
                        >
                            <Save className="h-4 w-4" />
                        </Button>
                    </div>
                    <p className="text-xs text-muted-foreground/50 ml-1">
                        Include the <code className="bg-muted/50 px-1 py-0.5 rounded">/v1</code> suffix for OpenAI-compatible API. Example: <code className="bg-muted/50 px-1 py-0.5 rounded">http://10.0.0.5:11434/v1</code>
                    </p>
                </div>

                {/* Test result: show discovered models */}
                {testResult?.available && (testResult.llm_models.length > 0 || testResult.embedding_models.length > 0) && (
                    <div className="space-y-4 pt-2 border-t border-white/5">
                        {testResult.llm_models.length > 0 && (
                            <div className="space-y-2">
                                <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                                    LLM MODELS ({testResult.llm_models.length})
                                </Label>
                                <div className="flex flex-wrap gap-1.5">
                                    {testResult.llm_models.map(m => (
                                        <Badge key={m} variant="secondary" className="text-xs font-mono bg-foreground/5 border border-white/5">
                                            {m}
                                        </Badge>
                                    ))}
                                </div>
                            </div>
                        )}
                        {testResult.embedding_models.length > 0 && (
                            <div className="space-y-2">
                                <Label className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/60 ml-1">
                                    EMBEDDING MODELS ({testResult.embedding_models.length})
                                </Label>
                                <div className="flex flex-wrap gap-1.5">
                                    {testResult.embedding_models.map(m => (
                                        <Badge key={m} variant="secondary" className="text-xs font-mono bg-foreground/5 border border-white/5">
                                            {m}
                                        </Badge>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* Error detail */}
                {testResult && !testResult.available && testResult.error && (
                    <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/5 border border-destructive/10 text-sm text-destructive">
                        <XCircle className="w-4 h-4 shrink-0 mt-0.5" />
                        {testResult.error}
                    </div>
                )}
            </CardContent>
        </Card>
    )
}
