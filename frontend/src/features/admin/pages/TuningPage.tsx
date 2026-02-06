/**
 * Tuning Page
 * ===========
 * 
 * RAG parameter tuning panel with sliders and toggles.
 */

import { useState, useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Save, RotateCcw, CheckCircle, Info } from 'lucide-react'
import { configApi, providersApi, ConfigSchema, TenantConfig, ConfigSchemaField, AvailableProviders, DefaultPrompts } from '@/lib/api-admin'
import { useAuth } from '@/features/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select"
import { toast } from "sonner"
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '@/features/admin/components/PageSkeleton'
import { EmbeddingMigrationDialog } from '../components/tuning/EmbeddingMigrationDialog'

const DEFAULT_TENANT_ID = 'default'  // TODO: Get from context

// Prompt field names for dynamic default lookup
const PROMPT_FIELDS = ['rag_system_prompt', 'rag_user_prompt', 'agent_system_prompt', 'community_summary_prompt', 'fact_extraction_prompt']
const LLM_FIELD_NAMES = new Set(['llm_provider', 'llm_model', 'temperature', 'seed', 'embedding_provider', 'embedding_model'])

export default function TuningPage() {
    const navigate = useNavigate()
    const { isSuperAdmin } = useAuth()
    const [schema, setSchema] = useState<ConfigSchema | null>(null)
    const [, setConfig] = useState<TenantConfig | null>(null)
    const [initialValues, setInitialValues] = useState<Record<string, unknown>>({})
    const [formValues, setFormValues] = useState<Record<string, unknown>>({})
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
    const [error, setError] = useState<string | null>(null)

    // Embedding migration state
    // Embedding migration state
    const [pendingEmbeddingChange, setPendingEmbeddingChange] = useState<string | null>(null)
    const [pendingEmbeddingProviderChange, setPendingEmbeddingProviderChange] = useState<string | null>(null)
    const [showMigrationDialog, setShowMigrationDialog] = useState(false)

    // Provider state
    const [availableProviders, setAvailableProviders] = useState<AvailableProviders | null>(null)
    const [validatingProvider, setValidatingProvider] = useState<string | null>(null)

    // Default prompts from backend
    const [defaultPrompts, setDefaultPrompts] = useState<DefaultPrompts | null>(null)

    useEffect(() => {
        loadData()
    }, [])

    const loadData = async () => {
        try {
            setLoading(true)
            const [schemaData, configData, providersData, promptsData] = await Promise.all([
                configApi.getSchema(),
                configApi.getTenant(DEFAULT_TENANT_ID),
                providersApi.getAvailable(),
                configApi.getDefaultPrompts()
            ])
            setSchema(schemaData)
            setConfig(configData)
            setAvailableProviders(providersData)
            setDefaultPrompts(promptsData)

            // Initialize form values from config
            const values: Record<string, unknown> = {}
            schemaData.fields.forEach(field => {
                if (field.name.includes('weight')) {
                    values[field.name] = configData.weights?.[field.name as keyof typeof configData.weights] ?? field.default
                } else {
                    values[field.name] = (configData as unknown as Record<string, unknown>)[field.name] ?? field.default
                }
            })

            const updatedFields = schemaData.fields.map(field => {
                const nextField = { ...field }

                if (field.name === 'llm_provider' && providersData.llm_providers) {
                    nextField.options = providersData.llm_providers.map(p => p.name)
                }

                if (field.name === 'embedding_provider' && providersData.embedding_providers) {
                    nextField.options = providersData.embedding_providers.map(p => p.name)
                }

                if (!isSuperAdmin && LLM_FIELD_NAMES.has(field.name)) {
                    nextField.read_only = true
                }

                return nextField
            })

            const updatedSchema = { ...schemaData, fields: updatedFields }

            setSchema(updatedSchema)
            setFormValues(values)
            setInitialValues(values)
            setError(null)
        } catch (err) {
            setError('Failed to load configuration')
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    const validateProvider = async (type: 'llm' | 'embedding', name: string) => {
        try {
            setValidatingProvider(name)
            const result = await providersApi.validate(type, name)
            if (result.available) {
                toast.success(`${name} is reachable and ready`)
                // Update specific provider models if needed
            } else {
                toast.error(`Connection failed: ${result.error}`)
            }
        } catch {
            toast.error(`Validation failed for ${name}`)
        } finally {
            setValidatingProvider(null)
        }
    }

    const handleChange = (name: string, value: unknown) => {
        // Special handling for embedding settings - trigger migration dialog
        if (name === 'embedding_model' && value !== initialValues.embedding_model) {
            setPendingEmbeddingChange(value as string)
            // If provider hasn't changed, keep current provider
            setPendingEmbeddingProviderChange(formValues.embedding_provider as string)
            setShowMigrationDialog(true)
            return
        }

        if (name === 'embedding_provider' && value !== initialValues.embedding_provider) {
            setPendingEmbeddingProviderChange(value as string)
            // Default to a model for this provider? Or let modal handle it
            // Let's pick the first available model for the new provider
            const prov = availableProviders?.embedding_providers.find(p => p.name === value)
            const defaultModel = prov?.models[0] || ''
            setPendingEmbeddingChange(defaultModel)
            setShowMigrationDialog(true)
            return
        }

        if (!isSuperAdmin && LLM_FIELD_NAMES.has(name)) {
            return
        }

        // LLM Provider Change - Reset Model
        if (name === 'llm_provider') {
            const prov = availableProviders?.llm_providers.find(p => p.name === value)
            // Automatically select first model if current is not valid for new provider
            // Or just select first model always for safety
            const firstModel = prov?.models[0] || ''
            setFormValues(prev => ({
                ...prev,
                [name]: value,
                llm_model: firstModel
            }))
            return
        }

        setFormValues(prev => ({ ...prev, [name]: value }))
        setSaveStatus('idle')
    }

    const handleConfirmEmbeddingChange = async () => {
        if (!pendingEmbeddingChange || !pendingEmbeddingProviderChange) return

        try {
            setSaving(true)

            // Save the embedding configuration
            await configApi.updateTenant(DEFAULT_TENANT_ID, {
                embedding_provider: pendingEmbeddingProviderChange,
                embedding_model: pendingEmbeddingChange
            } as Partial<TenantConfig>)

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

    const handleSave = async () => {
        try {
            setSaving(true)
            setSaveStatus('idle')

            // Build update payload
            const weights = ['vector_weight', 'graph_weight', 'rerank_weight']
            const weightValues: Record<string, number> = {}
            const configValues: Record<string, unknown> = {}

            Object.entries(formValues).forEach(([key, value]) => {
                if (weights.includes(key)) {
                    weightValues[key] = value as number
                } else {
                    configValues[key] = value
                }
            })

            if (Object.keys(weightValues).length > 0) {
                configValues.weights = weightValues
            }

            if (!isSuperAdmin) {
                LLM_FIELD_NAMES.forEach(key => {
                    delete configValues[key]
                })
                delete configValues.llm_steps
            }

            await configApi.updateTenant(DEFAULT_TENANT_ID, configValues as Partial<TenantConfig>)
            toast.success("Settings saved successfully")

            // Update initial values to match new saved state
            setInitialValues(formValues)
            setSaveStatus('idle')
        } catch (err) {
            console.error('Failed to save:', err)
            toast.error("Failed to save settings. Please try again.")
        } finally {
            setSaving(false)
        }
    }

    const handleReset = () => {
        if (!confirm('Discard unsaved changes?')) return
        setFormValues(initialValues)
        setSaveStatus('idle')
    }

    // Check if weights sum to approximately 1.0
    const weightsSum =
        (formValues.vector_weight as number || 0) +
        (formValues.graph_weight as number || 0) +
        (formValues.rerank_weight as number || 0)
    const weightsValid = Math.abs(weightsSum - 1.0) < 0.05

    // Check for changes
    const hasChanges = Object.keys(formValues).some(key => formValues[key] !== initialValues[key])
    const availableEmbeddingModels = availableProviders?.embedding_providers
        .find(p => p.name === pendingEmbeddingProviderChange)
        ?.models ?? []

    if (loading) {
        return <PageSkeleton />
    }

    if (error || !schema) {
        return (
            <div className="p-6">
                <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            </div>
        )
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="RAG Tuning"
                description="Fine-tune the retrieval and generation pipeline parameters."
                actions={
                    <div className="flex gap-2">
                        <Button
                            variant="outline"
                            onClick={handleReset}
                            disabled={saving || !hasChanges}
                        >
                            <RotateCcw className="w-4 h-4 mr-2" />
                            Reset
                        </Button>
                        <Button
                            onClick={handleSave}
                            disabled={saving || !hasChanges}
                        >
                            {saveStatus === 'success' ? (
                                <CheckCircle className="w-4 h-4 mr-2" />
                            ) : (
                                <Save className="w-4 h-4 mr-2" />
                            )}
                            {saving ? 'Saving...' : saveStatus === 'success' ? 'Saved!' : 'Save Changes'}
                        </Button>
                    </div>
                }
            />

            {!isSuperAdmin && (
                <Alert variant="info">
                    <AlertDescription>
                        LLM settings are managed by Super Admins in the LLMs page.
                        <Button
                            variant="link"
                            className="px-1"
                            onClick={() => navigate({ to: '/admin/settings/llms' })}
                        >
                            View LLM settings
                        </Button>
                    </AlertDescription>
                </Alert>
            )}

            {/* Weights Warning */}
            {!weightsValid && (
                <Alert variant="warning" className="border-warning/40 bg-warning-muted/40 text-warning">
                    <Info className="h-4 w-4" />
                    <AlertDescription>
                        Fusion weights sum to {weightsSum.toFixed(2)}. For optimal results, ensure they sum to 1.0.
                    </AlertDescription>
                </Alert>
            )}

            {/* Form Sections */}
            <div className="grid gap-6">
                {schema.groups
                    .filter(group => {
                        // Skip groups that only contain LLM fields (now managed in LLM Settings page)
                        const groupFields = schema.fields.filter(f => f.group === group && !LLM_FIELD_NAMES.has(f.name))
                        return groupFields.length > 0
                    })
                    .map(group => {
                        // Filter out LLM fields from this group
                        const visibleFields = schema.fields.filter(f => f.group === group && !LLM_FIELD_NAMES.has(f.name))
                        return (
                            <Card key={group} className="overflow-hidden shadow-sm">
                                <CardHeader className="bg-muted/50 pb-4 border-b">
                                    <CardTitle className="text-lg font-semibold capitalize flex items-center gap-2">
                                        {group.replace('_', ' ')}
                                        <Badge variant="outline" className="text-xs font-normal text-muted-foreground ml-auto">
                                            {visibleFields.length} settings
                                        </Badge>
                                    </CardTitle>
                                </CardHeader>
                                <CardContent className="p-6 grid gap-6">
                                    {(() => {
                                        const groupFields = visibleFields
                                        const renderedFields = new Set<string>()

                                        return groupFields.map(field => {
                                            // Skip if already rendered (e.g., model field captured by provider)
                                            if (renderedFields.has(field.name)) return null

                                            const renderFieldItem = (f: ConfigSchemaField) => {
                                                // Inject dynamic options for dependent fields
                                                const dynamicField = { ...f }
                                                if (f.name === 'embedding_model') {
                                                    const currentProvider = formValues['embedding_provider'] as string
                                                    const provDetails = availableProviders?.embedding_providers.find(p => p.name === currentProvider)
                                                    if (provDetails) dynamicField.options = provDetails.models
                                                }

                                                return (
                                                    <div key={f.name} className="flex gap-2 items-end">
                                                        <div className="flex-1">
                                                            <FieldInput
                                                                field={dynamicField}
                                                                value={formValues[f.name]}
                                                                onChange={(value) => handleChange(f.name, value)}
                                                                defaultPrompts={defaultPrompts}
                                                            />
                                                        </div>
                                                        {/* Validation Button for Providers */}
                                                        {(f.name === 'llm_provider' || f.name === 'embedding_provider') && (
                                                            <Button
                                                                variant="outline"
                                                                size="icon"
                                                                className={cn(
                                                                    "transition-colors",
                                                                    validatingProvider === formValues[f.name] && "border-primary text-primary"
                                                                )}
                                                                onClick={() => validateProvider(
                                                                    f.name === 'llm_provider' ? 'llm' : 'embedding',
                                                                    formValues[f.name] as string
                                                                )}
                                                                disabled={validatingProvider === formValues[f.name]}
                                                                title="Check connection"
                                                            >
                                                                {validatingProvider === formValues[f.name] ?
                                                                    <RotateCcw className="h-4 w-4 animate-spin" /> :
                                                                    <CheckCircle className="h-4 w-4 text-success" />
                                                                }
                                                            </Button>
                                                        )}
                                                    </div>
                                                )
                                            }

                                            // Check for Embedding Provider/Model Pairs
                                            if (field.name === 'embedding_provider') {
                                                const modelFieldName = 'embedding_model'
                                                const modelField = groupFields.find(f => f.name === modelFieldName)

                                                if (modelField) {
                                                    renderedFields.add(field.name)
                                                    renderedFields.add(modelFieldName)

                                                    return (
                                                        <div key={`${field.name}-group`} className="grid grid-cols-1 md:grid-cols-2 gap-6 p-4 bg-muted/20 rounded-lg border border-border/50">
                                                            {renderFieldItem(field)}
                                                            {renderFieldItem(modelField)}
                                                        </div>
                                                    )
                                                }
                                            }

                                            // Mark as rendered
                                            renderedFields.add(field.name)
                                            return renderFieldItem(field)
                                        })
                                    })()}
                                </CardContent>
                            </Card>
                        )
                    })}
            </div>

            <EmbeddingMigrationDialog
                open={showMigrationDialog}
                onOpenChange={setShowMigrationDialog}
                saving={saving}
                sourceProvider={String(initialValues.embedding_provider ?? '')}
                sourceModel={String(initialValues.embedding_model ?? '')}
                targetProvider={pendingEmbeddingProviderChange}
                targetModel={pendingEmbeddingChange}
                availableModels={availableEmbeddingModels}
                onModelChange={(model) => setPendingEmbeddingChange(model)}
                onCancel={handleCancelEmbeddingChange}
                onConfirm={handleConfirmEmbeddingChange}
            />
        </div>
    )
}

interface FieldInputProps {
    field: ConfigSchemaField
    value: unknown
    onChange: (value: unknown) => void
    defaultPrompts: DefaultPrompts | null
}

function LabelWithTooltip({ label, description }: { label: string, description: string }) {
    return (
        <div className="flex items-center gap-2 mb-2">
            <label className="font-medium text-sm text-foreground">{label}</label>
            <TooltipProvider>
                <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                        <Info className="w-3.5 h-3.5 text-muted-foreground hover:text-primary cursor-help transition-colors" />
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-[300px]">
                        <p>{description}</p>
                    </TooltipContent>
                </Tooltip>
            </TooltipProvider>
        </div>
    )
}

function FieldInput({ field, value, onChange, defaultPrompts }: FieldInputProps) {
    switch (field.type) {
        case 'number': {
            // If min/max are provided, use Slider. Otherwise use Input (e.g. seed)
            const isSlider = field.min !== undefined && field.max !== undefined

            return (
                <div>
                    <div className="flex items-center justify-between mb-2">
                        <LabelWithTooltip label={field.label} description={field.description} />
                        {isSlider && (
                            <span className="text-xs font-mono bg-primary/10 text-primary px-2 py-1 rounded">
                                {typeof value === 'number' ? value.toFixed(field.step && field.step < 1 ? 2 : 0) : String(value ?? '')}
                            </span>
                        )}
                    </div>
                    <div className="pt-2">
                        {isSlider ? (
                            <>
                                <Slider
                                    min={field.min ?? 0}
                                    max={field.max ?? 100}
                                    step={field.step ?? 1}
                                    value={[value as number ?? field.default as number]}
                                    onValueChange={(vals: number[]) => onChange(vals[0])}
                                    showValue={true}
                                    disabled={field.read_only}
                                />
                                <div className="flex justify-between text-xs text-muted-foreground mt-2 px-1">
                                    <span>{field.min}</span>
                                    <span>{field.max}</span>
                                </div>
                            </>
                        ) : (
                            <Input
                                type="number"
                                value={value !== null && value !== undefined ? String(value) : ''}
                                onChange={(e) => {
                                    const val = e.target.value === '' ? null : Number(e.target.value)
                                    onChange(val)
                                }}
                                disabled={field.read_only}
                                className="font-mono"
                                placeholder={field.default !== null ? String(field.default) : "Not set"}
                            />
                        )}
                    </div>
                </div>
            )
        }

        case 'boolean':
            return (
                <div className="flex items-center justify-between p-1">
                    <div className="flex items-center gap-2">
                        <label className="font-medium text-sm text-foreground">{field.label}</label>
                        <TooltipProvider>
                            <Tooltip delayDuration={300}>
                                <TooltipTrigger asChild>
                                    <Info className="w-3.5 h-3.5 text-muted-foreground hover:text-primary cursor-help transition-colors" />
                                </TooltipTrigger>
                                <TooltipContent side="right" className="max-w-[300px]">
                                    <p>{field.description}</p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                    <Switch
                        checked={value as boolean}
                        onCheckedChange={(checked) => onChange(checked)}
                        disabled={field.read_only}
                    />
                </div>
            )

        case 'select':
            return (
                <div>
                    <LabelWithTooltip label={field.label} description={field.description} />
                    <Select value={value as string} onValueChange={(val) => onChange(val)} disabled={field.read_only}>
                        <SelectTrigger>
                            <SelectValue placeholder="Select an option" />
                        </SelectTrigger>
                        <SelectContent>
                            {field.options?.map(opt => (
                                <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
            )

        case 'string': {
            // Check if this is a prompt field and get its default
            const isPromptField = PROMPT_FIELDS.includes(field.name)
            const defaultValue = isPromptField && defaultPrompts
                ? defaultPrompts[field.name as keyof DefaultPrompts]
                : ''
            // For prompt fields, use default if empty so user can directly edit it
            const displayValue = isPromptField && (value === '' || value === null || value === undefined)
                ? defaultValue
                : (value as string ?? '')
            return (
                <div>
                    <LabelWithTooltip label={field.label} description={field.description} />
                    <Textarea
                        value={displayValue}
                        onChange={(e) => onChange(e.target.value)}
                        disabled={field.read_only}
                        rows={isPromptField ? 12 : 3}
                        className="font-mono text-sm leading-relaxed"
                        placeholder={field.description}
                    />
                    {isPromptField && (value === '' || value === null || value === undefined) && (
                        <p className="text-xs text-muted-foreground mt-2">
                            Showing default prompt. Edit to customize.
                        </p>
                    )}
                </div>
            )
        }

        default:
            return null
    }
}
