/**
 * Tuning Page
 * ===========
 *
 * System prompt configuration. Other tuning options (weights, retrieval params,
 * LLM/embedding settings) are managed via the CLI.
 */

import { useState, useEffect } from 'react'
import { Save, RotateCcw, CheckCircle, Info } from 'lucide-react'
import { configApi, ConfigSchema, TenantConfig, ConfigSchemaField, DefaultPrompts } from '@/lib/api-admin'
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
import { Textarea } from "@/components/ui/textarea"
import { toast } from "sonner"
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '@/features/admin/components/PageSkeleton'

const DEFAULT_TENANT_ID = 'default'

// Whitelist: only prompt fields are editable in the UI.
const PROMPT_FIELDS = ['rag_system_prompt', 'rag_user_prompt', 'agent_system_prompt', 'community_summary_prompt', 'fact_extraction_prompt']

export default function TuningPage() {
    const [schema, setSchema] = useState<ConfigSchema | null>(null)
    const [initialValues, setInitialValues] = useState<Record<string, unknown>>({})
    const [formValues, setFormValues] = useState<Record<string, unknown>>({})
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle')
    const [error, setError] = useState<string | null>(null)
    const [defaultPrompts, setDefaultPrompts] = useState<DefaultPrompts | null>(null)

    useEffect(() => {
        loadData()
    }, [])

    const loadData = async () => {
        try {
            setLoading(true)
            const [schemaData, configData, promptsData] = await Promise.all([
                configApi.getSchema(),
                configApi.getTenant(DEFAULT_TENANT_ID),
                configApi.getDefaultPrompts()
            ])

            const promptFields = schemaData.fields.filter(f => PROMPT_FIELDS.includes(f.name))
            const promptGroups = Array.from(new Set(promptFields.map(f => f.group)))
            const filteredSchema: ConfigSchema = { ...schemaData, fields: promptFields, groups: promptGroups }

            const values: Record<string, unknown> = {}
            promptFields.forEach(field => {
                values[field.name] = (configData as unknown as Record<string, unknown>)[field.name] ?? field.default
            })

            setSchema(filteredSchema)
            setDefaultPrompts(promptsData)
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

            const payload: Record<string, unknown> = {}
            PROMPT_FIELDS.forEach(key => {
                if (key in formValues) payload[key] = formValues[key]
            })

            await configApi.updateTenant(DEFAULT_TENANT_ID, payload as Partial<TenantConfig>)
            toast.success("Prompts saved successfully")

            setInitialValues(formValues)
            setSaveStatus('idle')
        } catch (err) {
            console.error('Failed to save:', err)
            toast.error("Failed to save prompts. Please try again.")
        } finally {
            setSaving(false)
        }
    }

    const handleReset = () => {
        if (!confirm('Discard unsaved changes?')) return
        setFormValues(initialValues)
        setSaveStatus('idle')
    }

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
                title="System Prompts"
                description="Edit the system prompts used by the RAG and agent pipelines. Other tuning parameters are managed via the CLI."
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

            <div className="grid gap-6">
                {schema.groups.map(group => {
                    const visibleFields = schema.fields.filter(f => f.group === group)
                    if (visibleFields.length === 0) return null

                    return (
                        <Card key={group} className="overflow-hidden shadow-sm">
                            <CardHeader className="bg-muted/50 pb-4 border-b">
                                <CardTitle className="text-lg font-semibold capitalize">
                                    {group.replace(/_/g, ' ')}
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="p-6 grid gap-6">
                                {visibleFields.map(field => (
                                    <PromptField
                                        key={field.name}
                                        field={field}
                                        value={formValues[field.name]}
                                        onChange={(value) => handleChange(field.name, value)}
                                        defaultPrompts={defaultPrompts}
                                    />
                                ))}
                            </CardContent>
                        </Card>
                    )
                })}
            </div>
        </div>
    )
}

interface PromptFieldProps {
    field: ConfigSchemaField
    value: unknown
    onChange: (value: unknown) => void
    defaultPrompts: DefaultPrompts | null
}

function PromptField({ field, value, onChange, defaultPrompts }: PromptFieldProps) {
    const defaultValue = defaultPrompts
        ? defaultPrompts[field.name as keyof DefaultPrompts]
        : ''
    const isEmpty = value === '' || value === null || value === undefined
    const displayValue = isEmpty ? defaultValue : (value as string ?? '')

    return (
        <div>
            <div className="flex items-center gap-2 mb-2">
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
            <Textarea
                value={displayValue}
                onChange={(e) => onChange(e.target.value)}
                disabled={field.read_only}
                rows={12}
                className="font-mono text-sm leading-relaxed"
                placeholder={field.description}
            />
            {isEmpty && (
                <p className="text-xs text-muted-foreground mt-2">
                    Showing default prompt. Edit to customize.
                </p>
            )}
        </div>
    )
}
