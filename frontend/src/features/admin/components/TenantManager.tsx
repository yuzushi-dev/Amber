
import { useState, useEffect, useCallback } from 'react'
import { tenantsApi, Tenant, keysApi, ApiKeyResponse } from '@/lib/api-admin'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Building2, Plus, Trash, RefreshCw, Layers, Key, Crown, Shield } from 'lucide-react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { useAuth } from '@/features/auth'
import { PageHeader } from './PageHeader'
import { PageSkeleton } from './PageSkeleton'

export default function TenantManager() {
    const { isSuperAdmin } = useAuth()
    const [tenants, setTenants] = useState<Tenant[]>([])
    const [superAdminKeys, setSuperAdminKeys] = useState<ApiKeyResponse[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    // Create State
    const [newName, setNewName] = useState('')
    const [newPrefix, setNewPrefix] = useState('')
    const [creating, setCreating] = useState(false)

    const fetchTenants = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const [tenantData, keyData] = await Promise.all([
                tenantsApi.list(),
                isSuperAdmin ? keysApi.list() : Promise.resolve([])
            ])
            setTenants(tenantData)
            setSuperAdminKeys(keyData.filter(k => k.scopes.includes('super_admin')))
        } catch (err: unknown) {
            console.error(err)
            setError("Failed to load tenants.")
        } finally {
            setLoading(false)
        }
    }, [isSuperAdmin])

    useEffect(() => {
        fetchTenants()
    }, [fetchTenants])

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!newName.trim()) return

        setCreating(true)
        setError(null)

        try {
            await tenantsApi.create({
                name: newName,
                api_key_prefix: newPrefix.trim() || undefined
            })
            setNewName('')
            setNewPrefix('')
            fetchTenants()
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : "Failed to create tenant"
            setError(message)
        } finally {
            setCreating(false)
        }
    }

    const handleDelete = async (id: string, name: string) => {
        if (!window.confirm(`Are you sure you want to delete tenant "${name}"? This action cannot be undone.`)) return;

        try {
            await tenantsApi.delete(id)
            fetchTenants()
        } catch (err: unknown) {
            console.error(err)
            alert("Failed to delete tenant")
        }
    }

    if (loading && tenants.length === 0) {
        return <PageSkeleton />
    }

    return (
        <div className="space-y-12">
            {/* Header Section */}
            <PageHeader
                title="Tenants"
                description="Manage usage isolation silos. Each tenant has isolated documents, chunks, and logs."
                actions={
                    <div className="flex items-center gap-4">
                        <div className="text-right hidden md:block border-l pl-4 my-1">
                            <div className="text-2xl font-bold font-mono text-foreground leading-none">{tenants.length}</div>
                            <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Active</div>
                        </div>
                    </div>
                }
            />

            {error && (
                <Alert variant="destructive" dismissible onDismiss={() => setError(null)}>
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}

            {/* Create Hero Section */}
            <div className="relative overflow-hidden rounded-2xl border border-border/50 bg-gradient-to-br from-card to-background shadow-lg">
                <div className="absolute inset-0 bg-primary/5 opacity-50" />
                <div className="relative p-8">
                    <div className="flex flex-col md:flex-row gap-8 items-start">
                        <div className="flex-1 space-y-2">
                            <h2 className="text-2xl font-bold">New Tenant</h2>
                            <p className="text-muted-foreground">
                                Create a new isolated environment (tenant).
                            </p>
                        </div>

                        <form onSubmit={handleCreate} className="w-full md:w-auto flex flex-col sm:flex-row gap-3 items-end bg-background/50 p-4 rounded-xl border backdrop-blur-sm">
                            <div className="space-y-1.5 w-full sm:w-64">
                                <label className="text-xs font-semibold text-foreground/80 ml-1">Tenant Name</label>
                                <Input
                                    type="text"
                                    value={newName}
                                    onChange={(e) => setNewName(e.target.value)}
                                    placeholder="Acme Corp"
                                    className="px-4 py-2.5 bg-background focus-visible:ring-offset-0"
                                    disabled={creating}
                                />
                            </div>
                            <div className="space-y-1.5 w-full sm:w-40">
                                <label className="text-xs font-semibold text-foreground/80 ml-1">Prefix (Opt)</label>
                                <Input
                                    type="text"
                                    value={newPrefix}
                                    onChange={(e) => setNewPrefix(e.target.value)}
                                    placeholder="acme"
                                    className="px-4 py-2.5 bg-background font-mono text-sm focus-visible:ring-offset-0"
                                    disabled={creating}
                                />
                            </div>
                            <Button
                                type="submit"
                                disabled={!newName.trim() || creating}
                                size="lg"
                                className="w-full sm:w-auto text-primary-foreground font-semibold"
                            >
                                {creating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Plus className="w-5 h-5 mr-1" />}
                                {creating ? '' : 'Create'}
                            </Button>
                        </form>
                    </div>
                </div>
            </div>

            {/* Content Grid */}
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold flex items-center gap-2">
                        <Layers className="w-5 h-5 text-muted-foreground" />
                        Infrastructure Map
                    </h3>
                    <Button variant="ghost" size="sm" onClick={fetchTenants} disabled={loading} className="text-muted-foreground hover:text-foreground">
                        <RefreshCw className={cn("w-4 h-4 mr-2", loading && "animate-spin")} />
                        Refresh
                    </Button>
                </div>

                {tenants.length === 0 && !isSuperAdmin ? (
                    <div className="border-2 border-dashed rounded-xl p-12 text-center text-muted-foreground">
                        <Building2 className="w-12 h-12 mx-auto mb-4 opacity-20" />
                        <h3 className="text-lg font-medium mb-1">No Infrastructure Deployed</h3>
                        <p>Create your first tenant to get started.</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {isSuperAdmin && (
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="group relative bg-amber-500/5 hover:bg-amber-500/10 border border-amber-500/20 rounded-xl p-6 shadow-sm hover:shadow-md transition-all duration-300 ring-1 ring-amber-500/10"
                            >
                                <div className="space-y-4">
                                    <div className="flex items-start justify-between">
                                        <div className="space-y-1">
                                            <div className="flex items-center gap-2">
                                                <h4 className="font-bold text-lg leading-none text-amber-500">Global Admin</h4>

                                            </div>
                                            <div className="text-xs font-mono text-amber-600/70">
                                                System-wide Privilege
                                            </div>
                                        </div>
                                    </div>

                                    <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 space-y-3">
                                        <div className="text-[10px] font-bold uppercase tracking-tight text-amber-600/70">
                                            Authorized Keys ({superAdminKeys.length})
                                        </div>
                                        <div className="space-y-1.5">
                                            {superAdminKeys.length === 0 ? (
                                                <div className="text-xs text-amber-600/50 italic">No global keys configured</div>
                                            ) : (
                                                superAdminKeys.map(key => (
                                                    <div key={key.id} className="flex items-center justify-between text-xs p-1.5 rounded bg-background/50 border border-amber-500/10">
                                                        <div className="flex items-center gap-2">
                                                            <div className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                                                            <span className="font-medium text-amber-900 dark:text-amber-100">{key.name}</span>
                                                        </div>
                                                        <code className="text-[10px] text-amber-600/70 font-mono">{key.prefix}...{key.last_chars}</code>
                                                    </div>
                                                ))
                                            )}
                                        </div>
                                    </div>

                                    <div className="pt-2 text-[11px] text-amber-600/70 flex items-center gap-2">
                                        <Shield className="w-3.5 h-3.5" />
                                        <span>Bypasses Row-Level Security</span>
                                    </div>
                                </div>
                            </motion.div>
                        )}
                        {tenants.map((tenant, index) => (
                            <motion.div
                                key={tenant.id}
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: index * 0.05 }}
                                className="group relative bg-card hover:bg-card/80 border rounded-xl p-6 shadow-sm hover:shadow-md transition-all duration-300"
                            >
                                <div className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity z-10">
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleDelete(tenant.id, tenant.name);
                                        }}
                                        className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                    >
                                        <Trash className="w-4 h-4" />
                                    </Button>
                                </div>

                                <div className="space-y-4">
                                    <div className="flex items-start justify-between">
                                        <div className="space-y-1">
                                            <h4 className="font-bold text-lg leading-none">{tenant.name}</h4>
                                            <div className="text-xs font-mono text-muted-foreground truncate max-w-[150px]" title={tenant.id}>
                                                {tenant.id}
                                            </div>
                                        </div>
                                    </div>

                                    <div className="flex flex-wrap gap-2 pt-2">
                                        <div className={cn(
                                            "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border",
                                            tenant.is_active
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-red-500/10 text-red-500 border-red-500/20"
                                        )}>
                                            <div className={cn("w-1.5 h-1.5 rounded-full", tenant.is_active ? "bg-green-500" : "bg-red-500")} />
                                            {tenant.is_active ? 'Active' : 'Inactive'}
                                        </div>

                                        {tenant.api_key_prefix && (
                                            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-secondary text-secondary-foreground border border-secondary" title="Key Prefix">
                                                <Key className="w-3 h-3" />
                                                <span className="font-mono">{tenant.api_key_prefix}_</span>
                                            </div>
                                        )}
                                    </div>

                                    {/* Linked Keys Section */}
                                    <div className="pt-3">
                                        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5 flex items-center justify-between">
                                            <span>Access Keys</span>
                                            <span className="bg-muted px-1.5 py-0.5 rounded text-foreground">{tenant.api_keys.length}</span>
                                        </div>
                                        <div className="space-y-1">
                                            {tenant.api_keys.length === 0 ? (
                                                <div className="text-xs text-muted-foreground italic">No keys directly linked</div>
                                            ) : (
                                                <div className="flex flex-wrap gap-1.5">
                                                    {tenant.api_keys.slice(0, 3).map(key => (
                                                        <div key={key.id} className="text-xs border rounded px-1.5 py-0.5 bg-background flex items-center gap-1" title={`${key.prefix}...${key.last_chars}`}>
                                                            <div className={cn("w-1 h-1 rounded-full", key.is_active ? "bg-green-500" : "bg-muted-foreground")} />
                                                            <span className="max-w-[80px] truncate">{key.name}</span>
                                                            {key.scopes?.includes('super_admin') && (
                                                                <Crown className="w-2.5 h-2.5 text-amber-500" />
                                                            )}
                                                        </div>
                                                    ))}
                                                    {tenant.api_keys.length > 3 && (
                                                        <div className="text-xs text-muted-foreground px-1 py-0.5">+ {tenant.api_keys.length - 3} more</div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    <div className="pt-4 mt-2 border-t flex justify-end items-center text-xs text-muted-foreground">
                                        <div title="Total documents ingested for this tenant">
                                            {tenant.document_count} Documents
                                        </div>
                                    </div>
                                </div>
                            </motion.div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
