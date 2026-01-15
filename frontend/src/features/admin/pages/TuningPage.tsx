/**
 * Tuning Page
 * ===========
 * 
 * RAG parameter tuning panel with sliders and toggles.
 */

import { useState, useEffect } from 'react'
import { Save, RotateCcw, CheckCircle, Info } from 'lucide-react'
import { configApi, ConfigSchema, TenantConfig, ConfigSchemaField } from '@/lib/api-admin'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip"
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

const DEFAULT_TENANT_ID = 'default'  // TODO: Get from context

// Synced with backend src/core/generation/prompts.py
const DEFAULT_SYSTEM_PROMPT = `You are Amber, a sophisticated AI analyst designed to provide accurate, grounded answers based on document collections.

CRITICAL INSTRUCTIONS:
1. Grounding: Answer ONLY using the provided [Source ID] context. If the information isn't there, say: "I'm sorry, but I don't have enough information in the provided sources to answer that."
2. Citations: Every claim must be cited. Use [1], [2], etc., immediately after the relevant sentence.
3. Formatting: Use markdown for structure (headers, lists, bolding).
4. Tone: Professional, objective, and analytical.
5. Entity Mentions: When mentioning entities extracted from the graph, use their canonical names.`

export default function TuningPage() {
    const [schema, setSchema] = useState<ConfigSchema | null>(null)
    const [, setConfig] = useState<TenantConfig | null>(null)
    const [initialValues, setInitialValues] = useState<Record<string, unknown>>({})
    const [formValues, setFormValues] = useState<Record<string, unknown>>({})
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        loadData()
    }, [])

    const loadData = async () => {
        try {
            setLoading(true)
            const [schemaData, configData] = await Promise.all([
                configApi.getSchema(),
                configApi.getTenant(DEFAULT_TENANT_ID)
            ])
            setSchema(schemaData)
            setConfig(configData)

            // Initialize form values from config
            const values: Record<string, unknown> = {}
            schemaData.fields.forEach(field => {
                if (field.name.includes('weight')) {
                    values[field.name] = configData.weights?.[field.name as keyof typeof configData.weights] ?? field.default
                } else {
                    values[field.name] = (configData as unknown as Record<string, unknown>)[field.name] ?? field.default
                }
            })
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

    const handleChange = (name: string, value: unknown) => {
        setFormValues(prev => ({ ...prev, [name]: value }))
        setSaveStatus('idle')
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

            {/* Weights Warning */}
            {!weightsValid && (
                <Alert variant="warning" className="border-yellow-500/50 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400">
                    <Info className="h-4 w-4" />
                    <AlertDescription>
                        Fusion weights sum to {weightsSum.toFixed(2)}. For optimal results, ensure they sum to 1.0.
                    </AlertDescription>
                </Alert>
            )}

            {/* Form Sections */}
            <div className="grid gap-6">
                {schema.groups.map(group => (
                    <Card key={group} className="overflow-hidden border-border/50 shadow-sm">
                        <CardHeader className="bg-muted/30 pb-4 border-b border-border/50">
                            <CardTitle className="text-lg font-semibold capitalize flex items-center gap-2">
                                {group.replace('_', ' ')}
                                <Badge variant="outline" className="text-xs font-normal text-muted-foreground">
                                    {schema.fields.filter(f => f.group === group).length} settings
                                </Badge>
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="p-6 grid gap-6">
                            {schema.fields
                                .filter(field => field.group === group)
                                .map(field => (
                                    <FieldInput
                                        key={field.name}
                                        field={field}
                                        value={formValues[field.name]}
                                        onChange={(value) => handleChange(field.name, value)}
                                    />
                                ))}
                        </CardContent>
                    </Card>
                ))}
            </div>
        </div>
    )
}

interface FieldInputProps {
    field: ConfigSchemaField
    value: unknown
    onChange: (value: unknown) => void
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

function FieldInput({ field, value, onChange }: FieldInputProps) {
    switch (field.type) {
        case 'number':
            return (
                <div>
                    <div className="flex items-center justify-between mb-2">
                        <LabelWithTooltip label={field.label} description={field.description} />
                        <span className="text-xs font-mono bg-primary/10 text-primary px-2 py-1 rounded">
                            {typeof value === 'number' ? value.toFixed(field.step && field.step < 1 ? 2 : 0) : String(value ?? '')}
                        </span>
                    </div>
                    <div className="pt-2">
                        <Slider
                            min={field.min ?? 0}
                            max={field.max ?? 100}
                            step={field.step ?? 1}
                            value={[value as number ?? field.default as number]}
                            onValueChange={(vals: number[]) => onChange(vals[0])}
                            showValue={true}
                        />
                        <div className="flex justify-between text-xs text-muted-foreground mt-2 px-1">
                            <span>{field.min}</span>
                            <span>{field.max}</span>
                        </div>
                    </div>
                </div>
            )

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
                    />
                </div>
            )

        case 'select':
            return (
                <div>
                    <LabelWithTooltip label={field.label} description={field.description} />
                    <Select value={value as string} onValueChange={(val) => onChange(val)}>
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
            const isSystemPrompt = field.name === 'system_prompt_override';
            return (
                <div>
                    <LabelWithTooltip label={field.label} description={field.description} />
                    <Textarea
                        value={value as string ?? ''}
                        onChange={(e) => onChange(e.target.value)}
                        rows={isSystemPrompt ? 12 : 3}
                        className="font-mono"
                        placeholder={isSystemPrompt ? DEFAULT_SYSTEM_PROMPT : field.description}
                    />
                    {isSystemPrompt && (value === '' || value === null) && (
                        <p className="text-xs text-muted-foreground mt-2">
                            Using default system prompt (shown as placeholder).
                        </p>
                    )}
                </div>
            )
        }

        default:
            return null
    }
}
