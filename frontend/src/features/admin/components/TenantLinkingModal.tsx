
import { useState, useEffect } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { keysApi, tenantsApi, Tenant, ApiKeyResponse } from '@/lib/api-admin'
import { Plus, Shield, X, Crown } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/lib/utils'

interface TenantLinkingModalProps {
    apiKey: ApiKeyResponse
    isOpen: boolean
    onClose: () => void
    onSuccess: () => void
}

export default function TenantLinkingModal({ apiKey: initialApiKey, isOpen, onClose, onSuccess }: TenantLinkingModalProps) {
    const [allTenants, setAllTenants] = useState<Tenant[]>([])
    const [apiKey, setApiKey] = useState<ApiKeyResponse>(initialApiKey)
    const [selectedTenantId, setSelectedTenantId] = useState<string>('')
    const [loading, setLoading] = useState(false)

    // Sync local state when prop changes (e.g. if modal is closed and reopened with another key)
    useEffect(() => {
        setApiKey(initialApiKey)
    }, [initialApiKey])

    useEffect(() => {
        if (isOpen) {
            loadTenants()
        }
    }, [isOpen])

    const loadTenants = async () => {
        try {
            const data = await tenantsApi.list()
            setAllTenants(data)
        } catch (err) {
            console.error(err)
        }
    }

    const handleAdd = async () => {
        if (!selectedTenantId) return
        setLoading(true)
        try {
            await keysApi.linkTenant(apiKey.id, selectedTenantId, 'user')
            // Optimistic/Local refresh: Find the tenant object and add it to state
            const linkedTenant = allTenants.find(t => t.id === selectedTenantId)
            if (linkedTenant) {
                setApiKey(prev => ({
                    ...prev,
                    tenants: [...prev.tenants, { id: linkedTenant.id, name: linkedTenant.name }]
                }))
            }
            onSuccess()
            setSelectedTenantId('')
        } catch (err) {
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    const handleRemove = async (tenantId: string) => {
        setLoading(true)
        try {
            await keysApi.unlinkTenant(apiKey.id, tenantId)
            setApiKey(prev => ({
                ...prev,
                tenants: prev.tenants.filter(t => t.id !== tenantId)
            }))
            onSuccess()
        } catch (err) {
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    const toggleSuperAdmin = async (enabled: boolean) => {
        setLoading(true)
        try {
            const currentScopes = new Set(apiKey.scopes)
            if (enabled) {
                currentScopes.add('super_admin')
            } else {
                currentScopes.delete('super_admin')
            }
            const updated = await keysApi.update(apiKey.id, { scopes: Array.from(currentScopes) })
            setApiKey(updated)
            onSuccess()
        } catch (err) {
            console.error(err)
        } finally {
            setLoading(false)
        }
    }

    // Filter out already linked tenants
    const availableTenants = allTenants.filter(t =>
        !apiKey.tenants.some(linked => linked.id === t.id)
    )

    return (
        <Dialog open={isOpen} onOpenChange={onClose}>
            <DialogContent className="sm:max-w-[550px] p-0 gap-0 overflow-hidden bg-background/95 backdrop-blur-xl border-border/40 shadow-2xl">

                {/* Header */}
                <div className="p-6 border-b bg-muted/10">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-3 text-xl">
                            <div className="p-2 rounded-lg bg-primary/10 text-primary">
                                <Shield className="w-5 h-5" />
                            </div>
                            <div>
                                Manage Access
                                <div className="text-sm font-normal text-muted-foreground mt-0.5">
                                    {apiKey.name}
                                </div>
                            </div>
                        </DialogTitle>
                    </DialogHeader>
                </div>

                <div className="p-6 space-y-8">
                    {/* Super Admin Status */}
                    <div className="p-4 rounded-xl bg-amber-500/5 border border-amber-500/10 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className={cn(
                                "p-2 rounded-lg transition-colors",
                                apiKey.scopes.includes('super_admin') ? "bg-amber-500/20 text-amber-500" : "bg-muted text-muted-foreground"
                            )}>
                                <Crown className="w-5 h-5" />
                            </div>
                            <div>
                                <p className="text-sm font-bold text-amber-500 uppercase tracking-tight">Global Access</p>
                                <p className="text-xs text-muted-foreground">Bypasses isolation to access all tenants</p>
                            </div>
                        </div>
                        <Button
                            variant={apiKey.scopes.includes('super_admin') ? "default" : "outline"}
                            size="sm"
                            onClick={() => toggleSuperAdmin(!apiKey.scopes.includes('super_admin'))}
                            disabled={loading}
                            className={cn(
                                "h-8 border-amber-500/20",
                                apiKey.scopes.includes('super_admin')
                                    ? "bg-amber-500 hover:bg-amber-600 text-white border-none"
                                    : "text-amber-500 hover:bg-amber-500/10"
                            )}
                        >
                            {apiKey.scopes.includes('super_admin') ? 'Disable' : 'Enable'}
                        </Button>
                    </div>

                    {/* Access Granting Section */}
                    <div className="space-y-3">
                        <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            Grant Access
                        </label>
                        <div className="flex gap-2">
                            <Select value={selectedTenantId} onValueChange={setSelectedTenantId}>
                                <SelectTrigger className="flex-1 bg-background border-muted hover:border-primary/50 transition-colors h-11">
                                    <SelectValue placeholder="Select a tenant to link..." />
                                </SelectTrigger>
                                <SelectContent>
                                    {availableTenants.length === 0 ? (
                                        <div className="p-2 text-sm text-center text-muted-foreground">No available tenants</div>
                                    ) : (
                                        availableTenants.map(t => (
                                            <SelectItem key={t.id} value={t.id} className="cursor-pointer">
                                                {t.name}
                                            </SelectItem>
                                        ))
                                    )}
                                </SelectContent>
                            </Select>
                            <Button
                                onClick={handleAdd}
                                disabled={!selectedTenantId || loading}
                                className="h-11 px-6 font-medium shadow-none"
                            >
                                <Plus className="w-4 h-4 mr-2" />
                                Add
                            </Button>
                        </div>
                    </div>

                    {/* Active Links - Pill Grid */}
                    <div className="space-y-3">
                        <div className="flex justify-between items-center">
                            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                Authorized Tenants
                            </label>
                            <span className="text-xs text-muted-foreground bg-muted/50 px-2 py-0.5 rounded-full">
                                {apiKey.tenants.length}
                            </span>
                        </div>

                        <div className="min-h-[100px] bg-muted/5 rounded-xl border border-dashed border-muted/50 p-4">
                            {apiKey.tenants.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-muted-foreground/50 gap-2 py-4">
                                    <Shield className="w-8 h-8 opacity-20" />
                                    <p className="text-sm">No tenants specifically authorized.</p>
                                    <p className="text-xs italic opacity-70">Check system defaults.</p>
                                </div>
                            ) : (
                                <div className="flex flex-wrap gap-2">
                                    <AnimatePresence mode="popLayout">
                                        {apiKey.tenants.map(t => (
                                            <motion.div
                                                layout
                                                key={t.id}
                                                initial={{ opacity: 0, scale: 0.8 }}
                                                animate={{ opacity: 1, scale: 1 }}
                                                exit={{ opacity: 0, scale: 0.8 }}
                                                className={cn(
                                                    "group flex items-center gap-2 pl-3 pr-1 py-1.5",
                                                    "bg-background border rounded-full shadow-sm hover:border-destructive/30 hover:shadow-md transition-all",
                                                    "cursor-default select-none"
                                                )}
                                            >
                                                <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
                                                <span className="text-sm font-medium">{t.name}</span>
                                                <button
                                                    onClick={() => handleRemove(t.id)}
                                                    disabled={loading}
                                                    className={cn(
                                                        "ml-1 p-1 rounded-full text-muted-foreground/50",
                                                        "hover:bg-destructive hover:text-destructive-foreground transition-all duration-200"
                                                    )}
                                                >
                                                    <X className="w-3 h-3" />
                                                </button>
                                            </motion.div>
                                        ))}
                                    </AnimatePresence>
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                <DialogFooter className="p-4 border-t bg-muted/10">
                    <Button variant="ghost" onClick={onClose}>Done</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
