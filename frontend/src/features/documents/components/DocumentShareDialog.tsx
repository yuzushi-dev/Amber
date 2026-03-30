import { useEffect, useState } from 'react'
import { Lock, Share2, Users } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { tenantsApi, type Tenant } from '@/lib/api-admin'
import { apiClient } from '@/lib/api-client'

interface DocumentShareTarget {
    tenant_id: string
    tenant_name: string | null
    share_mode: string
    created_at: string
}

interface DocumentSharesResponse {
    document_id: string
    owner_tenant_id: string
    shares: DocumentShareTarget[]
}

interface DocumentShareDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    documentId: string
    documentTitle: string
    onSaved?: () => void
}

const getErrorMessage = (error: unknown, fallback: string) => {
    if (error && typeof error === 'object') {
        const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
        if (detail) return detail

        const message = (error as { message?: string }).message
        if (message) return message
    }
    return fallback
}

export default function DocumentShareDialog({
    open,
    onOpenChange,
    documentId,
    documentTitle,
    onSaved,
}: DocumentShareDialogProps) {
    const [availableTenants, setAvailableTenants] = useState<Tenant[]>([])
    const [selectedTenantIds, setSelectedTenantIds] = useState<string[]>([])
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!open) return

        let cancelled = false

        const load = async () => {
            setLoading(true)
            setError(null)

            try {
                const [tenants, sharesResponse] = await Promise.all([
                    tenantsApi.list(),
                    apiClient.get<DocumentSharesResponse>(`/documents/${documentId}/shares`),
                ])

                if (cancelled) return

                setAvailableTenants(
                    tenants.filter((tenant) => tenant.id !== 'default' && tenant.is_active)
                )
                setSelectedTenantIds(
                    sharesResponse.data.shares.map((share) => share.tenant_id)
                )
            } catch (err) {
                if (cancelled) return
                setError(getErrorMessage(err, 'Failed to load document access settings.'))
                setAvailableTenants([])
                setSelectedTenantIds([])
            } finally {
                if (!cancelled) {
                    setLoading(false)
                }
            }
        }

        load()
        return () => {
            cancelled = true
        }
    }, [documentId, open])

    const handleToggleTenant = (tenantId: string, checked: boolean) => {
        setSelectedTenantIds((current) => {
            if (checked) {
                return current.includes(tenantId) ? current : [...current, tenantId]
            }
            return current.filter((candidate) => candidate !== tenantId)
        })
    }

    const handleSave = async () => {
        try {
            setSaving(true)
            setError(null)
            await apiClient.put(`/documents/${documentId}/shares`, {
                tenant_ids: selectedTenantIds,
            })
            onSaved?.()
            onOpenChange(false)
        } catch (err) {
            setError(getErrorMessage(err, 'Failed to update document access.'))
        } finally {
            setSaving(false)
        }
    }

    const selectedCount = selectedTenantIds.length

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Share2 className="h-5 w-5 text-primary" />
                        Manage Access
                    </DialogTitle>
                    <DialogDescription>
                        Choose which tenants can access <span className="font-medium text-foreground">{documentTitle}</span>.
                    </DialogDescription>
                </DialogHeader>

                <DialogBody className="space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/20 px-4 py-3">
                        <div className="space-y-1">
                            <p className="text-sm font-medium">Visibility</p>
                            <p className="text-xs text-muted-foreground">
                                If no tenant is selected, the document remains private to the default tenant.
                            </p>
                        </div>
                        <Badge variant={selectedCount > 0 ? 'secondary' : 'outline'}>
                            {selectedCount > 0
                                ? `Shared with ${selectedCount} tenant${selectedCount === 1 ? '' : 's'}`
                                : 'Private to default'}
                        </Badge>
                    </div>

                    {loading ? (
                        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                            Loading tenant access…
                        </div>
                    ) : availableTenants.length === 0 ? (
                        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                            <div className="mb-2 flex justify-center">
                                <Lock className="h-5 w-5" />
                            </div>
                            No additional active tenants are available.
                        </div>
                    ) : (
                        <div className="space-y-3">
                            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                <Users className="h-4 w-4" />
                                Tenant Access
                            </div>
                            <div className="grid gap-2 sm:grid-cols-2">
                                {availableTenants.map((tenant) => (
                                    <label
                                        key={tenant.id}
                                        className="flex items-center gap-3 rounded-lg border bg-background px-3 py-3 text-sm transition-colors hover:border-primary/40"
                                    >
                                        <Checkbox
                                            aria-label={tenant.name}
                                            checked={selectedTenantIds.includes(tenant.id)}
                                            onCheckedChange={(checked) => handleToggleTenant(tenant.id, checked)}
                                        />
                                        <div className="min-w-0">
                                            <div className="font-medium truncate">{tenant.name}</div>
                                            <div className="text-[11px] text-muted-foreground truncate">{tenant.id}</div>
                                        </div>
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}

                    {error && (
                        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                            {error}
                        </div>
                    )}
                </DialogBody>

                <DialogFooter>
                    <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
                        Cancel
                    </Button>
                    <Button onClick={handleSave} disabled={loading || saving}>
                        {saving ? 'Saving…' : 'Save Access'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
