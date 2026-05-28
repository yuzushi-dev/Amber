import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Save, AlertTriangle, Info } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/features/auth'
import { configApi, providersApi, AvailableProviders } from '@/lib/api-admin'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '@/features/admin/components/PageSkeleton'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { GlobalDefaultsCard } from '../components/llm/GlobalDefaultsCard'
import { EmbeddingCard } from '../components/llm/EmbeddingCard'
import { OllamaConnectionCard } from '../components/llm/OllamaConnectionCard'

const DEFAULT_TENANT_ID = 'default'

export default function LlmSettingsPage() {
    const navigate = useNavigate()
    const { isSuperAdmin } = useAuth()
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [availableProviders, setAvailableProviders] = useState<AvailableProviders | null>(null)

    const [defaultProvider, setDefaultProvider] = useState('')
    const [defaultModel, setDefaultModel] = useState('')
    const [defaultTemperature, setDefaultTemperature] = useState<number | null>(null)
    const [defaultSeed, setDefaultSeed] = useState<number | null>(null)
    const [initialState, setInitialState] = useState<string>('')

    // Embedding state
    const [embeddingProvider, setEmbeddingProvider] = useState('')
    const [embeddingModel, setEmbeddingModel] = useState('')
    const [validatingEmbedding, setValidatingEmbedding] = useState(false)
    const [initialEmbeddingProvider, setInitialEmbeddingProvider] = useState('')
    const [initialEmbeddingModel, setInitialEmbeddingModel] = useState('')

    // Ollama URL state
    const [ollamaBaseUrl, setOllamaBaseUrl] = useState('')
    const [savingOllamaUrl, setSavingOllamaUrl] = useState(false)

    // Embedding migration state
    const [pendingEmbeddingChange, setPendingEmbeddingChange] = useState<string | null>(null)
    const [pendingEmbeddingProviderChange, setPendingEmbeddingProviderChange] = useState<string | null>(null)
    const [showMigrationDialog, setShowMigrationDialog] = useState(false)

    useEffect(() => {
        loadData()
    }, [])

    const loadData = async () => {
        try {
            setLoading(true)
            const [config, providers] = await Promise.all([
                configApi.getTenant(DEFAULT_TENANT_ID),
                providersApi.getAvailable(),
            ])

            setAvailableProviders(providers)
            setDefaultProvider(config.llm_provider)
            setDefaultModel(config.llm_model)
            setDefaultTemperature(config.temperature ?? null)
            setDefaultSeed(config.seed ?? null)
            setEmbeddingProvider(config.embedding_provider ?? '')
            setEmbeddingModel(config.embedding_model ?? '')
            setInitialEmbeddingProvider(config.embedding_provider ?? '')
            setInitialEmbeddingModel(config.embedding_model ?? '')
            setOllamaBaseUrl(config.ollama_base_url ?? '')
            setInitialState(JSON.stringify({
                defaultProvider: config.llm_provider,
                defaultModel: config.llm_model,
                defaultTemperature: config.temperature ?? null,
                defaultSeed: config.seed ?? null,
                embeddingProvider: config.embedding_provider ?? '',
                embeddingModel: config.embedding_model ?? '',
            }))
        } catch (err) {
            console.error(err)
            toast.error('Failed to load LLM settings')
        } finally {
            setLoading(false)
        }
    }

    const isDirty = useMemo(() => {
        if (!initialState) return false
        return JSON.stringify({ defaultProvider, defaultModel, defaultTemperature, defaultSeed, embeddingProvider, embeddingModel }) !== initialState
    }, [defaultProvider, defaultModel, defaultTemperature, defaultSeed, embeddingProvider, embeddingModel, initialState])

    const getModelsForProvider = (providerName: string) => {
        if (!availableProviders?.llm_providers) return []
        const provider = availableProviders.llm_providers.find(p => p.name === providerName)
        return provider?.models ?? []
    }

    const getEmbeddingModelsForProvider = (providerName: string) => {
        if (!availableProviders?.embedding_providers) return []
        const provider = availableProviders.embedding_providers.find(p => p.name === providerName)
        return provider?.models ?? []
    }

    const handleEmbeddingProviderChange = (provider: string) => {
        const models = getEmbeddingModelsForProvider(provider)
        const model = models[0] || ''
        setPendingEmbeddingProviderChange(provider)
        setPendingEmbeddingChange(model)
        setShowMigrationDialog(true)
    }

    const handleEmbeddingModelChange = (model: string) => {
        setPendingEmbeddingProviderChange(embeddingProvider)
        setPendingEmbeddingChange(model)
        setShowMigrationDialog(true)
    }

    const handleConfirmEmbeddingChange = async () => {
        if (!pendingEmbeddingChange || !pendingEmbeddingProviderChange) return

        try {
            setSaving(true)

            await configApi.updateTenant(DEFAULT_TENANT_ID, {
                embedding_provider: pendingEmbeddingProviderChange,
                embedding_model: pendingEmbeddingChange
            })

            toast.success('Embedding configuration updated. Redirecting to migration...')
            setShowMigrationDialog(false)
            setPendingEmbeddingChange(null)
            setPendingEmbeddingProviderChange(null)

            navigate({
                to: '/admin/data/vectors',
                search: { autoMigrate: 'true', tenantId: DEFAULT_TENANT_ID }
            })
        } catch (err) {
            console.error('Failed to update embedding config:', err)
            toast.error('Failed to update embedding configuration')
        } finally {
            setSaving(false)
        }
    }

    const handleCancelEmbeddingChange = () => {
        setPendingEmbeddingChange(null)
        setPendingEmbeddingProviderChange(null)
        setShowMigrationDialog(false)
    }

    const validateEmbeddingProvider = async () => {
        try {
            setValidatingEmbedding(true)
            const result = await providersApi.validate('embedding', embeddingProvider)
            if (result.available) {
                toast.success(`${embeddingProvider} is reachable and ready`)
            } else {
                toast.error(`Connection failed: ${result.error}`)
            }
        } catch {
            toast.error(`Validation failed for ${embeddingProvider}`)
        } finally {
            setValidatingEmbedding(false)
        }
    }

    const handleDefaultProviderChange = (provider: string) => {
        const models = getModelsForProvider(provider)
        const model = models[0] || ''
        setDefaultProvider(provider)
        setDefaultModel(model)
    }

    const handleSave = async () => {
        try {
            setSaving(true)
            await configApi.updateTenant(DEFAULT_TENANT_ID, {
                llm_provider: defaultProvider,
                llm_model: defaultModel,
                temperature: defaultTemperature,
                seed: defaultSeed,
                embedding_provider: embeddingProvider,
                embedding_model: embeddingModel,
            })
            toast.success('LLM settings saved')
            setInitialState(JSON.stringify({
                defaultProvider,
                defaultModel,
                defaultTemperature,
                defaultSeed,
                embeddingProvider,
                embeddingModel,
            }))
        } catch (err) {
            console.error(err)
            toast.error('Failed to save LLM settings')
        } finally {
            setSaving(false)
        }
    }

    if (loading) {
        return <PageSkeleton />
    }

    return (
        <div className="p-8 pb-32 max-w-7xl mx-auto space-y-10 animate-in fade-in duration-500">
            <PageHeader
                title="LLM Settings"
                description="Configure AI provider settings and model parameters."
                actions={(
                    <div className="flex items-center gap-3">
                        <div className={cn("text-xs text-muted-foreground mr-2 transition-opacity", isDirty ? "opacity-100" : "opacity-0")}>
                            Unsaved changes
                        </div>
                        <Button
                            onClick={handleSave}
                            disabled={!isSuperAdmin || !isDirty || saving}
                            className={cn("transition-[box-shadow,transform,opacity] duration-300 ease-out", isDirty ? "shadow-md translate-y-0" : "translate-y-0 opacity-50")}
                        >
                            <Save className="h-4 w-4 mr-2" />
                            {saving ? 'Saving…' : 'Save Changes'}
                        </Button>
                    </div>
                )}
            />

            {!isSuperAdmin && (
                <Alert variant="warning" className="border-warning/40 bg-warning-muted/40 text-warning">
                    <AlertDescription>
                        Super Admin privileges are required to edit LLM settings.
                    </AlertDescription>
                </Alert>
            )}

            <Alert variant="info">
                <AlertDescription>
                    Per-step LLM overrides are managed via the CLI. This page covers only Ollama, Embeddings, and Global Defaults.
                </AlertDescription>
            </Alert>

            <div className="space-y-6">
                <GlobalDefaultsCard
                    isSuperAdmin={isSuperAdmin}
                    availableProviders={availableProviders}
                    defaultProvider={defaultProvider}
                    defaultModel={defaultModel}
                    defaultTemperature={defaultTemperature}
                    defaultSeed={defaultSeed}
                    onProviderChange={handleDefaultProviderChange}
                    onModelChange={setDefaultModel}
                    onTemperatureChange={setDefaultTemperature}
                    onSeedChange={setDefaultSeed}
                    getModelsForProvider={getModelsForProvider}
                />

                <EmbeddingCard
                    isSuperAdmin={isSuperAdmin}
                    availableProviders={availableProviders}
                    embeddingProvider={embeddingProvider}
                    embeddingModel={embeddingModel}
                    onProviderChange={handleEmbeddingProviderChange}
                    onModelChange={handleEmbeddingModelChange}
                    onValidate={validateEmbeddingProvider}
                    validating={validatingEmbedding}
                    getModelsForProvider={getEmbeddingModelsForProvider}
                />

                <OllamaConnectionCard
                    isSuperAdmin={isSuperAdmin}
                    ollamaBaseUrl={ollamaBaseUrl}
                    onUrlChange={setOllamaBaseUrl}
                    onUrlSave={async (url) => {
                        try {
                            setSavingOllamaUrl(true)
                            await configApi.updateTenant(DEFAULT_TENANT_ID, {
                                ollama_base_url: url
                            })
                            toast.success('Ollama URL saved')
                            const providers = await providersApi.getAvailable()
                            setAvailableProviders(providers)

                            if (defaultProvider === 'ollama') {
                                const ollamaLlm = providers.llm_providers.find(p => p.name === 'ollama')
                                const llmModels = ollamaLlm?.models ?? []
                                if (llmModels.length > 0 && !llmModels.includes(defaultModel)) {
                                    setDefaultModel(llmModels[0])
                                }
                            }

                            if (embeddingProvider === 'ollama') {
                                const ollamaEmbed = providers.embedding_providers.find(p => p.name === 'ollama')
                                const embedModels = ollamaEmbed?.models ?? []
                                if (embedModels.length > 0 && !embedModels.includes(embeddingModel)) {
                                    setEmbeddingModel(embedModels[0])
                                }
                            }

                            toast.info('Provider models refreshed')
                        } catch (err) {
                            console.error(err)
                            toast.error('Failed to save Ollama URL')
                        } finally {
                            setSavingOllamaUrl(false)
                        }
                    }}
                    saving={savingOllamaUrl}
                />
            </div>

            {/* Embedding Migration Confirmation Dialog */}
            <Dialog open={showMigrationDialog} onOpenChange={setShowMigrationDialog}>
                <DialogContent className="p-0 gap-0 overflow-hidden sm:max-w-md">
                    <DialogHeader className="p-6 border-b border-white/5 bg-foreground/[0.02]">
                        <DialogTitle className="font-display tracking-tight text-lg flex items-center gap-3">
                            <div className="p-2 rounded-lg bg-warning-muted">
                                <AlertTriangle className="h-5 w-5 text-warning" />
                            </div>
                            Embedding Model Change
                        </DialogTitle>
                    </DialogHeader>

                    <div className="p-6 space-y-5">
                        <div className="p-4 rounded-lg bg-muted/10 border border-white/5 space-y-4">
                            <div className="space-y-1">
                                <label className="text-sm font-medium text-foreground">Target Model</label>
                                <Select
                                    value={pendingEmbeddingChange || ''}
                                    onValueChange={setPendingEmbeddingChange}
                                >
                                    <SelectTrigger>
                                        <SelectValue placeholder="Select model" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {availableProviders?.embedding_providers
                                            .find(p => p.name === pendingEmbeddingProviderChange)
                                            ?.models.map(model => (
                                                <SelectItem key={model} value={model}>{model}</SelectItem>
                                            ))
                                        }
                                    </SelectContent>
                                </Select>
                            </div>

                            <p className="text-sm text-muted-foreground leading-relaxed">
                                You are migrating from{' '}
                                <span className="font-mono text-foreground bg-muted/50 px-1.5 py-0.5 rounded">
                                    {initialEmbeddingProvider}/{initialEmbeddingModel}
                                </span>{' '}
                                to{' '}
                                <span className="font-mono text-primary bg-primary/10 px-1.5 py-0.5 rounded">
                                    {pendingEmbeddingProviderChange}/{pendingEmbeddingChange}
                                </span>
                            </p>
                        </div>

                        <div className="flex items-start gap-3 p-4 rounded-lg bg-destructive/5 border border-destructive/10">
                            <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
                            <div className="space-y-2">
                                <p className="text-sm font-medium text-destructive">This action requires a full data migration</p>
                                <ul className="text-xs text-destructive/80 space-y-1 list-disc list-inside">
                                    <li>All existing vector embeddings will be deleted</li>
                                    <li>Documents will be queued for re-processing</li>
                                    <li>Search may be limited until complete</li>
                                </ul>
                            </div>
                        </div>

                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <Info className="w-3.5 h-3.5" />
                            You'll be redirected to monitor the migration progress.
                        </div>
                    </div>

                    <DialogFooter className="p-4 bg-muted/5 border-t border-white/5 gap-3">
                        <Button
                            variant="ghost"
                            onClick={handleCancelEmbeddingChange}
                            disabled={saving}
                            className="hover:bg-foreground/5"
                        >
                            Cancel
                        </Button>
                        <Button
                            onClick={handleConfirmEmbeddingChange}
                            disabled={saving}
                            className="bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/20"
                        >
                            {saving ? 'Processing...' : 'Proceed with Migration'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
