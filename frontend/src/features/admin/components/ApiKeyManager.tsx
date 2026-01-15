/**
 * API Key Management Component
 * ============================
 * 
 * Displays current API key status and full management interface.
 */

import { useState, useEffect, useCallback } from 'react'
import { useAuth, maskApiKey } from '@/features/auth'
import ApiKeyModal from '@/features/auth/components/ApiKeyModal'
import { LogOut, Plus, Trash, Copy, Check, Shield, Crown } from 'lucide-react'
import { keysApi, ApiKeyResponse, CreatedKeyResponse } from '@/lib/api-admin'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { PageHeader } from './PageHeader'
import { PageSkeleton } from './PageSkeleton'

import TenantLinkingModal from './TenantLinkingModal'

export default function ApiKeyManager() {
    const { apiKey, clearApiKey } = useAuth()
    const [showKeyModal, setShowKeyModal] = useState(false)

    // Management State
    const [keys, setKeys] = useState<ApiKeyResponse[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [linkingKey, setLinkingKey] = useState<ApiKeyResponse | null>(null)

    const [newName, setNewName] = useState('')
    const [isSuperAdminToggle, setIsSuperAdminToggle] = useState(false)
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
            const scopes = ["admin", "active_user"]
            if (isSuperAdminToggle) {
                scopes.push("super_admin")
            }
            const result = await keysApi.create({ name: newName, scopes })
            setCreatedKey(result)
            setNewName('')
            setIsSuperAdminToggle(false)
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

    if (loading && keys.length === 0) {
        return <PageSkeleton />
    }

    return (
        <div className="space-y-8">
            <PageHeader
                title="API Key Management"
                description="Manage persistent access keys for API access."
            />

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
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setShowKeyModal(true)}
                    >
                        Switch Key
                    </Button>
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                            if (confirm('Are you sure you want to logout?')) {
                                clearApiKey()
                                window.location.reload()
                            }
                        }}
                        className="text-destructive hover:text-destructive hover:bg-destructive/10"
                    >
                        <LogOut className="w-3 h-3 mr-1" />
                        Logout
                    </Button>
                </div>
            </div>

            {error && (
                <Alert variant="destructive" dismissible onDismiss={() => setError(null)}>
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}

            {/* Create New Key */}
            <div className="bg-card border rounded-lg p-6 space-y-4">
                <h2 className="text-lg font-semibold">Generate New Key</h2>
                <form onSubmit={handleCreate} className="space-y-4">
                    <div className="flex gap-4 items-end">
                        <div className="flex-1 space-y-1">
                            <label className="text-sm font-medium">Key Name</label>
                            <Input
                                type="text"
                                value={newName}
                                onChange={(e) => setNewName(e.target.value)}
                                placeholder="e.g. CI/CD Pipeline, Python Script..."
                                className="px-3 py-2 bg-background focus-visible:ring-offset-0"
                                disabled={creating}
                            />
                        </div>
                        <Button
                            type="submit"
                            disabled={!newName.trim() || creating}
                        >
                            <Plus className="w-4 h-4 mr-2" />
                            {creating ? 'Generating...' : 'Generate Key'}
                        </Button>
                    </div>
                </form>

                {createdKey && (
                    <Alert variant="success" className="mt-4" dismissible onDismiss={() => setCreatedKey(null)}>
                        <div className="font-semibold flex items-center gap-2 mb-2">
                            <Check className="w-4 h-4" /> Key Created Successfully
                        </div>
                        <AlertDescription>
                            <p className="mb-3">Copy this key now. It will never be shown again.</p>
                            <div className="flex items-center gap-2">
                                <code className="flex-1 bg-background p-3 rounded border font-mono text-sm break-all">
                                    {createdKey.key}
                                </code>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={async () => {
                                        if (navigator.clipboard && navigator.clipboard.writeText) {
                                            await navigator.clipboard.writeText(createdKey.key);
                                        } else {
                                            const textArea = document.createElement("textarea");
                                            textArea.value = createdKey.key;
                                            document.body.appendChild(textArea);
                                            textArea.select();
                                            document.execCommand("copy");
                                            document.body.removeChild(textArea);
                                        }
                                    }}
                                    title="Copy to clipboard"
                                >
                                    <Copy className="w-4 h-4" />
                                </Button>
                            </div>
                        </AlertDescription>
                    </Alert>
                )}
            </div>

            {/* Active Keys List */}
            <div className="border rounded-lg overflow-hidden bg-card">
                <div className="px-6 py-4 border-b bg-muted/40">
                    <h2 className="font-semibold">Active API Keys</h2>
                </div>

                {keys.length === 0 ? (
                    <div className="p-8 text-center text-muted-foreground">
                        No persistent keys found. Create one above.
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-muted/50">
                                <tr>
                                    <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Name</th>
                                    <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Prefix</th>
                                    <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Tenants</th>
                                    <th className="text-left px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Created</th>
                                    <th className="text-right px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wide">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y">
                                {keys.map((key) => (
                                    <tr key={key.id} className="hover:bg-muted/40 transition-colors">
                                        <td className="px-6 py-4 font-medium">
                                            <div className="flex items-center gap-2">
                                                {key.name}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 font-mono text-xs">{key.prefix}...{key.last_chars}</td>
                                        <td className="px-6 py-4 text-sm">
                                            <div className="flex flex-wrap gap-1 items-center max-w-[250px]">
                                                {key.scopes.includes('super_admin') && (
                                                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 text-[10px] font-bold border border-amber-500/20 mr-1" title="System-wide access (Bypasses RLS)">
                                                        <Crown className="w-2.5 h-2.5" />
                                                        SUPER
                                                    </span>
                                                )}
                                                {key.tenants?.length > 0 ? (
                                                    <>
                                                        <span key={key.tenants[0].id} className="inline-flex items-center gap-1 bg-primary/10 text-primary text-[10px] font-medium rounded px-1.5 py-0.5" title={key.tenants[0].id}>
                                                            {key.tenants[0].name}
                                                        </span>
                                                        {key.tenants.length > 1 && (
                                                            <span className="inline-flex items-center bg-muted text-muted-foreground text-[10px] font-medium rounded px-1.5 py-0.5" title={key.tenants.slice(1).map(t => t.name).join(', ')}>
                                                                + {key.tenants.length - 1} more
                                                            </span>
                                                        )}
                                                    </>
                                                ) : !key.scopes.includes('super_admin') && (
                                                    <span className="text-muted-foreground italic text-xs" title="Has access to 'default' tenant only">Default</span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 text-muted-foreground text-sm">
                                            {new Date(key.created_at).toLocaleDateString()}
                                        </td>
                                        <td className="px-6 py-4 text-right flex justify-end gap-2">
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onClick={() => setLinkingKey(key)}
                                            >
                                                Manage Access
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                onClick={() => handleRevoke(key.id)}
                                                className="text-destructive hover:text-destructive hover:bg-destructive/10"
                                            >
                                                <Trash className="w-3 h-3" />
                                            </Button>
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

            {linkingKey && (
                <TenantLinkingModal
                    apiKey={linkingKey}
                    isOpen={!!linkingKey}
                    onClose={() => setLinkingKey(null)}
                    onSuccess={() => {
                        fetchKeys() // Refresh to show updated count
                    }}
                />
            )}
        </div>
    )
}
