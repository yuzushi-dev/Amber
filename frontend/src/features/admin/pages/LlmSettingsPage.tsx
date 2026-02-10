import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Save, AlertTriangle, Info } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/features/auth'
import { configApi, providersApi, AvailableProviders, LlmStepMeta, LlmStepOverride } from '@/lib/api-admin'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '@/features/admin/components/PageSkeleton'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/utils'
import { GlobalDefaultsCard } from '../components/llm/GlobalDefaultsCard'
import { EmbeddingCard } from '../components/llm/EmbeddingCard'
import { OllamaConnectionCard } from '../components/llm/OllamaConnectionCard'
import { LlmStepRow } from '../components/llm/LlmStepRow'
import { StepConfigDialog } from '../components/llm/StepConfigDialog'

const DEFAULT_TENANT_ID = 'default'

type StepOverrides = Record<string, LlmStepOverride>
type ApplySelection = Record<string, boolean>

export default function LlmSettingsPage() {
    const navigate = useNavigate()
    const { isSuperAdmin } = useAuth()
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [availableProviders, setAvailableProviders] = useState<AvailableProviders | null>(null)
    const [steps, setSteps] = useState<LlmStepMeta[]>([])

    const [defaultProvider, setDefaultProvider] = useState('')
    const [defaultModel, setDefaultModel] = useState('')
    const [defaultTemperature, setDefaultTemperature] = useState<number | null>(null)
    const [defaultSeed, setDefaultSeed] = useState<number | null>(null)
    const [stepOverrides, setStepOverrides] = useState<StepOverrides>({})
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

    // Bulk apply dialog state
    const [showApplyDialog, setShowApplyDialog] = useState(false)
    const [pendingDefaults, setPendingDefaults] = useState<{ provider: string; model: string } | null>(null)
    const [applySelection, setApplySelection] = useState<ApplySelection>({})

    // Single step edit dialog state
    const [editingStepId, setEditingStepId] = useState<string | null>(null)

    useEffect(() => {
        loadData()
    }, [])

    const loadData = async () => {
        try {
            setLoading(true)
            const [config, providers, stepData] = await Promise.all([
                configApi.getTenant(DEFAULT_TENANT_ID),
                providersApi.getAvailable(),
                configApi.getLlmSteps(),
            ])

            setAvailableProviders(providers)
            setSteps(stepData.steps)
            setDefaultProvider(config.llm_provider)
            setDefaultModel(config.llm_model)
            setDefaultTemperature(config.temperature ?? null)
            setDefaultSeed(config.seed ?? null)
            setStepOverrides(config.llm_steps ?? {})
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
                stepOverrides: config.llm_steps ?? {},
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
        return JSON.stringify({ defaultProvider, defaultModel, defaultTemperature, defaultSeed, stepOverrides, embeddingProvider, embeddingModel }) !== initialState
    }, [defaultProvider, defaultModel, defaultTemperature, defaultSeed, stepOverrides, embeddingProvider, embeddingModel, initialState])

    const featureGroups = useMemo(() => {
        const groups: Record<string, LlmStepMeta[]> = {}
        steps.forEach(step => {
            if (!groups[step.feature]) groups[step.feature] = []
            groups[step.feature].push(step)
        })
        return groups
    }, [steps])

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
        // Trigger migration dialog
        setPendingEmbeddingProviderChange(provider)
        setPendingEmbeddingChange(model)
        setShowMigrationDialog(true)
    }

    const handleEmbeddingModelChange = (model: string) => {
        // Trigger migration dialog if model changed from initial
        setPendingEmbeddingProviderChange(embeddingProvider)
        setPendingEmbeddingChange(model)
        setShowMigrationDialog(true)
    }

    const handleConfirmEmbeddingChange = async () => {
        if (!pendingEmbeddingChange || !pendingEmbeddingProviderChange) return

        try {
            setSaving(true)

            // Save the embedding configuration
            await configApi.updateTenant(DEFAULT_TENANT_ID, {
                embedding_provider: pendingEmbeddingProviderChange,
                embedding_model: pendingEmbeddingChange
            })

            toast.success('Embedding configuration updated. Redirecting to migration...')
            setShowMigrationDialog(false)
            setPendingEmbeddingChange(null)
            setPendingEmbeddingProviderChange(null)

            // Navigate to Vector Store with autoMigrate flag
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

    const openApplyDialog = (provider: string, model: string) => {
        const selection: ApplySelection = {}
        steps.forEach(step => {
            const override = stepOverrides[step.id]
            selection[step.id] = Boolean(override?.provider || override?.model)
        })
        setApplySelection(selection)
        setPendingDefaults({ provider, model })
        setShowApplyDialog(true)
    }

    const handleDefaultProviderChange = (provider: string) => {
        const models = getModelsForProvider(provider)
        const model = models[0] || ''
        setDefaultProvider(provider)
        setDefaultModel(model)
        openApplyDialog(provider, model)
    }

    const handleDefaultModelChange = (model: string) => {
        setDefaultModel(model)
        openApplyDialog(defaultProvider, model)
    }

    const handleApplyDefaults = () => {
        if (!pendingDefaults) return
        setStepOverrides(prev => {
            const next: StepOverrides = { ...prev }
            Object.entries(applySelection).forEach(([stepId, checked]) => {
                if (!checked) return
                const existing = next[stepId] ?? {}
                next[stepId] = {
                    ...existing,
                    provider: pendingDefaults.provider,
                    model: pendingDefaults.model,
                }
            })
            return next
        })
        setShowApplyDialog(false)
    }

    const handleStepChange = (stepId: string, changes: LlmStepOverride) => {
        setStepOverrides(prev => ({
            ...prev,
            [stepId]: { ...prev[stepId], ...changes }
        }))
    }

    const pruneOverrides = (overrides: StepOverrides) => {
        const pruned: StepOverrides = {}
        Object.entries(overrides).forEach(([stepId, override]) => {
            const hasValue = Object.values(override).some(v => v !== null && v !== undefined && v !== '')
            if (hasValue) pruned[stepId] = override
        })
        return pruned
    }

    const handleSave = async () => {
        try {
            setSaving(true)
            await configApi.updateTenant(DEFAULT_TENANT_ID, {
                llm_provider: defaultProvider,
                llm_model: defaultModel,
                temperature: defaultTemperature,
                seed: defaultSeed,
                llm_steps: pruneOverrides(stepOverrides),
                embedding_provider: embeddingProvider,
                embedding_model: embeddingModel,
            })
            toast.success('LLM settings saved')
            setInitialState(JSON.stringify({
                defaultProvider,
                defaultModel,
                defaultTemperature,
                defaultSeed,
                stepOverrides: pruneOverrides(stepOverrides),
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

            <div className="space-y-6">
                <GlobalDefaultsCard
                    isSuperAdmin={isSuperAdmin}
                    availableProviders={availableProviders}
                    defaultProvider={defaultProvider}
                    defaultModel={defaultModel}
                    defaultTemperature={defaultTemperature}
                    defaultSeed={defaultSeed}
                    onProviderChange={handleDefaultProviderChange}
                    onModelChange={handleDefaultModelChange}
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
                            // Reload providers to reflect new URL and models
                            const providers = await providersApi.getAvailable()
                            setAvailableProviders(providers)

                            // Auto-reconcile LLM model if current provider is ollama
                            if (defaultProvider === 'ollama') {
                                const ollamaLlm = providers.llm_providers.find(p => p.name === 'ollama')
                                const llmModels = ollamaLlm?.models ?? []
                                if (llmModels.length > 0 && !llmModels.includes(defaultModel)) {
                                    setDefaultModel(llmModels[0])
                                }
                            }

                            // Auto-reconcile embedding model if current provider is ollama
                            if (embeddingProvider === 'ollama') {
                                const ollamaEmbed = providers.embedding_providers.find(p => p.name === 'ollama')
                                const embedModels = ollamaEmbed?.models ?? []
                                if (embedModels.length > 0 && !embedModels.includes(embeddingModel)) {
                                    // Only update the local display — do NOT trigger migration here.
                                    // Migration is triggered when the user explicitly saves or changes model via dropdown.
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

            <div className="space-y-8">
                {Object.entries(featureGroups).map(([feature, featureSteps]) => (
                    <div key={feature} className="space-y-3">
                        <div className="flex items-center justify-between px-1">
                            <h3 className="text-sm font-bold uppercase tracking-[0.15em] text-muted-foreground/70">
                                {feature.replace('_', ' ')}
                            </h3>
                            <span className="text-[10px] font-medium text-muted-foreground/40 uppercase tracking-widest">
                                {featureSteps.length} steps
                            </span>
                        </div>

                        <div className="grid gap-3 md:grid-cols-2">
                            {featureSteps.map(step => (
                                <LlmStepRow
                                    key={step.id}
                                    step={step}
                                    override={stepOverrides[step.id]}
                                    defaultProvider={defaultProvider}
                                    defaultModel={defaultModel}
                                    onEdit={setEditingStepId}
                                />
                            ))}
                        </div>
                    </div>
                ))}
            </div>

            {/* Bulk Apply Dialog (Triggered when default provider changes) */}
            <Dialog open={showApplyDialog} onOpenChange={setShowApplyDialog}>
                <DialogContent className="max-w-xl">
                    <DialogHeader>
                        <DialogTitle>Update Overrides?</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4">
                        <p className="text-sm text-muted-foreground">
                            You changed the default provider. Some steps have valid overrides that might now use a different provider schema.
                            Select the steps you want to reset to use the new defaults.
                        </p>
                        <div className="bg-muted/30 border rounded-md p-2 grid gap-2 max-h-72 overflow-y-auto">
                            {steps.map(step => (
                                <label key={step.id} className="flex items-center gap-3 p-2 rounded hover:bg-muted/50 transition-colors cursor-pointer">
                                    <Checkbox
                                        checked={applySelection[step.id] ?? false}
                                        onCheckedChange={(checked) =>
                                            setApplySelection(prev => ({ ...prev, [step.id]: Boolean(checked) }))
                                        }
                                    />
                                    <div className="flex-1 min-w-0">
                                        <div className="font-medium text-sm truncate">{step.label}</div>
                                        <div className="text-xs text-muted-foreground truncate">{step.feature}</div>
                                    </div>
                                    {stepOverrides[step.id]?.provider && (
                                        <Badge variant="outline" className="text-[10px]">Overridden</Badge>
                                    )}
                                </label>
                            ))}
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="ghost" onClick={() => setShowApplyDialog(false)}>
                            Keep Custom Overrides
                        </Button>
                        <Button onClick={handleApplyDefaults} disabled={!isSuperAdmin}>
                            Apply Defaults to Selected
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Single Step Config Dialog */}
            <StepConfigDialog
                open={!!editingStepId}
                onOpenChange={(open) => !open && setEditingStepId(null)}
                step={editingStepId ? steps.find(s => s.id === editingStepId) ?? null : null}
                override={editingStepId ? (stepOverrides[editingStepId] ?? {}) : {}}
                defaultProvider={defaultProvider}
                defaultModel={defaultModel}
                availableProviders={availableProviders}
                isSuperAdmin={isSuperAdmin}
                onChange={(changes) => editingStepId && handleStepChange(editingStepId, changes)}
                getModelsForProvider={getModelsForProvider}
            />

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
                        {/* Model Change Selection */}
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

                        {/* Warning Box */}
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
