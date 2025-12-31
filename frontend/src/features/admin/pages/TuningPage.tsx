/**
 * Tuning Page
 * ===========
 * 
 * RAG parameter tuning panel with sliders and toggles.
 */

import { useState, useEffect } from 'react'
import { Save, RotateCcw, AlertCircle, CheckCircle } from 'lucide-react'
import { configApi, ConfigSchema, TenantConfig, ConfigSchemaField } from '@/lib/api-admin'
import OptionalFeaturesManager from '../components/OptionalFeaturesManager'
import ApiKeyManager from '../components/ApiKeyManager'

const DEFAULT_TENANT_ID = 'default'  // TODO: Get from context

export default function TuningPage() {
    const [schema, setSchema] = useState<ConfigSchema | null>(null)
    const [, setConfig] = useState<TenantConfig | null>(null)
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
                    values[field.name] = (configData as any)[field.name] ?? field.default
                }
            })
            setFormValues(values)
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
            setSaveStatus('success')

            // Reset success after 3s
            setTimeout(() => setSaveStatus('idle'), 3000)
        } catch (err) {
            setSaveStatus('error')
            console.error('Failed to save:', err)
        } finally {
            setSaving(false)
        }
    }

    const handleReset = async () => {
        if (!confirm('Reset all settings to defaults? This cannot be undone.')) return

        try {
            setSaving(true)
            await configApi.resetTenant(DEFAULT_TENANT_ID)
            await loadData()
            setSaveStatus('success')
        } catch (err) {
            setSaveStatus('error')
            console.error('Failed to reset:', err)
        } finally {
            setSaving(false)
        }
    }

    // Check if weights sum to approximately 1.0
    const weightsSum =
        (formValues.vector_weight as number || 0) +
        (formValues.graph_weight as number || 0) +
        (formValues.rerank_weight as number || 0)
    const weightsValid = Math.abs(weightsSum - 1.0) < 0.05

    if (loading) {
        return (
            <div className="p-6 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
        )
    }

    if (error || !schema) {
        return (
            <div className="p-6">
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
                    <p className="text-red-800 dark:text-red-400">{error}</p>
                </div>
            </div>
        )
    }

    return (
        <div className="p-6 max-w-4xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">RAG Tuning</h1>
                    <p className="text-muted-foreground">
                        Adjust retrieval and generation parameters
                    </p>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={handleReset}
                        disabled={saving}
                        className="flex items-center gap-2 px-4 py-2 border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                    >
                        <RotateCcw className="w-4 h-4" />
                        Reset
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors disabled:opacity-50"
                    >
                        {saveStatus === 'success' ? (
                            <CheckCircle className="w-4 h-4" />
                        ) : (
                            <Save className="w-4 h-4" />
                        )}
                        {saving ? 'Saving...' : saveStatus === 'success' ? 'Saved!' : 'Save Changes'}
                    </button>
                </div>
            </div>

            {/* Weights Warning */}
            {!weightsValid && (
                <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 mb-6 flex items-center gap-3">
                    <AlertCircle className="w-5 h-5 text-yellow-600" />
                    <span className="text-yellow-800 dark:text-yellow-400">
                        Fusion weights sum to {weightsSum.toFixed(2)}. For best results, weights should sum to 1.0.
                    </span>
                </div>
            )}

            {/* Form Sections */}
            {schema.groups.map(group => (
                <div key={group} className="mb-8">
                    <h2 className="text-lg font-semibold mb-4 capitalize border-b pb-2">
                        {group.replace('_', ' ')}
                    </h2>
                    <div className="space-y-6">
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
                    </div>
                </div>
            ))}

            {/* Optional Features Section */}
            <div className="mb-8 pt-6 border-t">
                <OptionalFeaturesManager />
            </div>

            {/* API Key Section */}
            <div className="mb-8 pt-6 border-t">
                <ApiKeyManager />
            </div>
        </div>
    )
}

interface FieldInputProps {
    field: ConfigSchemaField
    value: unknown
    onChange: (value: unknown) => void
}

function FieldInput({ field, value, onChange }: FieldInputProps) {
    switch (field.type) {
        case 'number':
            return (
                <div className="space-y-2">
                    <div className="flex items-center justify-between">
                        <label className="font-medium">{field.label}</label>
                        <span className="text-sm font-mono bg-muted px-2 py-0.5 rounded">
                            {typeof value === 'number' ? value.toFixed(field.step && field.step < 1 ? 2 : 0) : String(value ?? '')}
                        </span>
                    </div>
                    <input
                        type="range"
                        min={field.min ?? 0}
                        max={field.max ?? 100}
                        step={field.step ?? 1}
                        value={value as number ?? field.default as number}
                        onChange={(e) => onChange(parseFloat(e.target.value))}
                        className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                    />
                    <p className="text-sm text-muted-foreground">{field.description}</p>
                </div>
            )

        case 'boolean':
            return (
                <div className="flex items-center justify-between">
                    <div>
                        <label className="font-medium">{field.label}</label>
                        <p className="text-sm text-muted-foreground">{field.description}</p>
                    </div>
                    <button
                        type="button"
                        role="switch"
                        aria-checked={value as boolean}
                        onClick={() => onChange(!value)}
                        className={`relative w-11 h-6 rounded-full transition-colors ${value ? 'bg-primary' : 'bg-muted'
                            }`}
                    >
                        <span
                            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${value ? 'translate-x-5' : 'translate-x-0'
                                }`}
                        />
                    </button>
                </div>
            )

        case 'select':
            return (
                <div className="space-y-2">
                    <label className="font-medium">{field.label}</label>
                    <select
                        value={value as string ?? field.default as string}
                        onChange={(e) => onChange(e.target.value)}
                        className="w-full px-3 py-2 bg-background border rounded-md"
                    >
                        {field.options?.map(opt => (
                            <option key={opt} value={opt}>{opt}</option>
                        ))}
                    </select>
                    <p className="text-sm text-muted-foreground">{field.description}</p>
                </div>
            )

        case 'string':
            return (
                <div className="space-y-2">
                    <label className="font-medium">{field.label}</label>
                    <textarea
                        value={value as string ?? ''}
                        onChange={(e) => onChange(e.target.value)}
                        rows={3}
                        className="w-full px-3 py-2 bg-background border rounded-md resize-y"
                        placeholder={field.description}
                    />
                    <p className="text-sm text-muted-foreground">{field.description}</p>
                </div>
            )

        default:
            return null
    }
}
