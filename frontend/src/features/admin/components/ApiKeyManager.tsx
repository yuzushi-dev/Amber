/**
 * API Key Management Component
 * ============================
 * 
 * Displays current API key status and full management interface.
 */

import { useState, useEffect, useCallback } from 'react'
import { useAuth, maskApiKey } from '@/features/auth'
import ApiKeyModal from '@/features/auth/components/ApiKeyModal'
import { Key, LogOut, Plus, Trash, Copy, Check, Shield, AlertTriangle } from 'lucide-react'
import { keysApi, ApiKeyResponse, CreatedKeyResponse } from '@/lib/api-admin'

export default function ApiKeyManager() {
    const { apiKey, clearApiKey } = useAuth()
    const [showKeyModal, setShowKeyModal] = useState(false)

    // Management State
    const [keys, setKeys] = useState<ApiKeyResponse[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    // Create State
    const [newName, setNewName] = useState('')
    const [creating, setCreating] = useState(false)
    const [createdKey, setCreatedKey] = useState<CreatedKeyResponse | null>(null)

    const fetchKeys = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const data = await keysApi.list()
            setKeys(data)
        } catch (err: unknown) {
            console.error(err)
            setError("Failed to load keys. You might not have admin permissions.")
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchKeys()
    }, [fetchKeys])

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!newName.trim()) return

        setCreating(true)
        setError(null)
        setCreatedKey(null)

        try {
            const result = await keysApi.create({ name: newName })
            setCreatedKey(result)
            setNewName('')
            fetchKeys() // Refresh list
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : "Failed to create key"
            setError(message)
        } finally {
            setCreating(false)
        }
    }

    const handleRevoke = async (id: string) => {
        if (!confirm("Are you sure you want to revoke this key? Any scripts using it will stop working.")) return;

        try {
            await keysApi.revoke(id)
            fetchKeys()
        } catch (err: unknown) {
            console.error(err)
            alert("Failed to revoke key")
        }
    }

    return (
        <div className="space-y-8">
            <div className="mb-6">
                <h1 className="text-2xl font-bold flex items-center gap-2">
                    <Key className="w-6 h-6" />
                    API Key Management
                </h1>
                <p className="text-muted-foreground">
                    Manage persistent access keys for API access.
                </p>
            </div>

            {/* Current Session */}
            <div className="flex items-center justify-between p-4 border rounded-lg bg-card/50">
                <div className="flex items-center gap-4">
                    <div className="p-2 bg-primary/10 rounded-full">
                        <Shield className="w-5 h-5 text-primary" />
                    </div>
                    <div>
                        <p className="text-sm font-medium">Current Session</p>
                        <code className="text-sm text-muted-foreground font-mono">
                            {apiKey ? maskApiKey(apiKey) : 'Not set'}
                        </code>
                    </div>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={() => setShowKeyModal(true)}
                        className="px-3 py-1.5 text-sm border rounded-md hover:bg-accent transition-colors"
                    >
                        Switch Key
                    </button>
                    <button
                        onClick={() => {
                            if (confirm('Are you sure you want to logout?')) {
                                clearApiKey()
                                window.location.reload()
                            }
                        }}
                        className="px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 rounded-md transition-colors flex items-center gap-1"
                    >
                        <LogOut className="w-3 h-3" />
                        Logout
                    </button>
                </div>
            </div>

            {error && (
                <div className="p-4 bg-red-500/10 text-red-600 border border-red-500/20 rounded-md flex justify-between items-center">
                    <div className="flex items-center gap-2">
                        <AlertTriangle className="w-4 h-4" />
                        <span>{error}</span>
                    </div>
                    <button onClick={() => setError(null)}>×</button>
                </div>
            )}

            {/* Create New Key */}
            <div className="bg-card border rounded-lg p-6 space-y-4">
                <h2 className="text-lg font-semibold">Generate New Key</h2>
                <form onSubmit={handleCreate} className="flex gap-4 items-end">
                    <div className="flex-1 space-y-1">
                        <label className="text-sm font-medium">Key Name</label>
                        <input
                            type="text"
                            value={newName}
                            onChange={(e) => setNewName(e.target.value)}
                            placeholder="e.g. CI/CD Pipeline, Python Script..."
                            className="w-full px-3 py-2 bg-background border rounded-md focus:outline-none focus:ring-2 focus:ring-primary/50"
                            disabled={creating}
                        />
                    </div>
                    <button
                        type="submit"
                        disabled={!newName.trim() || creating}
                        className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
                    >
                        <Plus className="w-4 h-4" />
                        {creating ? 'Generating...' : 'Generate Key'}
                    </button>
                </form>

                {createdKey && (
                    <div className="mt-4 p-4 bg-green-500/10 border border-green-500/20 rounded-md animate-in fade-in slide-in-from-top-2">
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-green-700 font-semibold flex items-center gap-2">
                                <Check className="w-4 h-4" /> Key Created Successfully
                            </h3>
                            <button
                                onClick={() => setCreatedKey(null)}
                                className="text-xs text-green-700 hover:underline"
                            >
                                Close
                            </button>
                        </div>
                        <p className="text-sm text-green-700/80 mb-3">
                            Copy this key now. It will never be shown again.
                        </p>
                        <div className="flex items-center gap-2">
                            <code className="flex-1 bg-background p-3 rounded border font-mono text-sm break-all">
                                {createdKey.key}
                            </code>
                            <button
                                onClick={() => navigator.clipboard.writeText(createdKey.key)}
                                className="p-2 text-green-700 hover:bg-green-500/10 rounded transition-colors"
                                title="Copy to clipboard"
                            >
                                <Copy className="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                )}
            </div>

            {/* Active Keys List */}
            <div className="border rounded-lg overflow-hidden bg-card">
                <div className="px-6 py-4 border-b bg-muted/40">
                    <h2 className="font-semibold">Active API Keys</h2>
                </div>

                {loading && keys.length === 0 ? (
                    <div className="p-8 text-center text-muted-foreground">Loading keys...</div>
                ) : keys.length === 0 ? (
                    <div className="p-8 text-center text-muted-foreground">
                        No persistent keys found. Create one above.
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                            <thead className="bg-muted/40 text-muted-foreground uppercase text-xs">
                                <tr>
                                    <th className="px-6 py-3">Name</th>
                                    <th className="px-6 py-3">Prefix</th>
                                    <th className="px-6 py-3">Ending</th>
                                    <th className="px-6 py-3">Created</th>
                                    <th className="px-6 py-3">Last Used</th>
                                    <th className="px-6 py-3 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y">
                                {keys.map((key) => (
                                    <tr key={key.id} className="hover:bg-muted/40 transition-colors">
                                        <td className="px-6 py-4 font-medium">{key.name}</td>
                                        <td className="px-6 py-4 font-mono text-xs">{key.prefix}</td>
                                        <td className="px-6 py-4 font-mono text-xs text-muted-foreground">...{key.last_chars}</td>
                                        <td className="px-6 py-4 text-muted-foreground">
                                            {new Date(key.created_at).toLocaleDateString()}
                                        </td>
                                        <td className="px-6 py-4 text-muted-foreground">
                                            {key.last_used_at ? new Date(key.last_used_at).toLocaleDateString() : 'Never'}
                                        </td>
                                        <td className="px-6 py-4 text-right">
                                            <button
                                                onClick={() => handleRevoke(key.id)}
                                                className="text-destructive hover:text-destructive/80 transition-colors inline-flex items-center gap-1 text-xs font-medium"
                                                title="Revoke Key"
                                            >
                                                <Trash className="w-3 h-3" /> Revoke
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {showKeyModal && (
                <ApiKeyModal
                    mode="change"
                    isOpen={showKeyModal}
                    onClose={() => setShowKeyModal(false)}
                    onSuccess={() => setShowKeyModal(false)}
                />
            )}
        </div>
    )
}
