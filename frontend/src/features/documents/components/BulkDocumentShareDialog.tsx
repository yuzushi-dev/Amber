import { useEffect, useState } from 'react'
import { Lock, Share2, UserMinus, UserPlus, Users } from 'lucide-react'

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
import { ScrollArea } from '@/components/ui/scroll-area'
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

interface BulkDocumentShareDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    documentIds: string[]
    documentTitles: string[]
    onSaved?: () => void
}

type BulkShareMode = 'grant' | 'revoke'

const getErrorMessage = (error: unknown, fallback: string) => {
    if (error && typeof error === 'object') {
        const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
        if (detail) return detail

        const message = (error as { message?: string }).message
        if (message) return message
    }
    return fallback
}

const mergeTenantIds = (currentTenantIds: string[], selectedTenantIds: string[]) => {
    const next = [...currentTenantIds]
    for (const tenantId of selectedTenantIds) {
        if (!next.includes(tenantId)) {
            next.push(tenantId)
        }
    }
    return next
}

const removeTenantIds = (currentTenantIds: string[], selectedTenantIds: string[]) =>
    currentTenantIds.filter((tenantId) => !selectedTenantIds.includes(tenantId))

const haveSameTenantIds = (left: string[], right: string[]) =>
    left.length === right.length && left.every((tenantId) => right.includes(tenantId))

export default function BulkDocumentShareDialog({
    open,
    onOpenChange,
    documentIds,
    documentTitles,
    onSaved,
}: BulkDocumentShareDialogProps) {
    const [availableTenants, setAvailableTenants] = useState<Tenant[]>([])
    const [selectedTenantIds, setSelectedTenantIds] = useState<string[]>([])
    const [mode, setMode] = useState<BulkShareMode>('grant')
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [completedCount, setCompletedCount] = useState(0)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!open) return

        let cancelled = false

        const load = async () => {
            setLoading(true)
            setError(null)
            setSelectedTenantIds([])
            setMode('grant')
            setCompletedCount(0)

            try {
                const tenants = await tenantsApi.list()

                if (cancelled) return

                setAvailableTenants(
                    tenants.filter((tenant) => tenant.id !== 'default' && tenant.is_active)
                )
            } catch (err) {
                if (cancelled) return
                setError(getErrorMessage(err, 'Failed to load tenant access options.'))
                setAvailableTenants([])
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
    }, [open])

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
            setCompletedCount(0)
            setError(null)

            const failedDocumentIds: string[] = []

            for (let index = 0; index < documentIds.length; index += 1) {
                const documentId = documentIds[index]

                try {
                    const sharesResponse = await apiClient.get<DocumentSharesResponse>(`/documents/${documentId}/shares`)
                    const currentTenantIds = sharesResponse.data.shares.map((share) => share.tenant_id)
                    const nextTenantIds =
                        mode === 'grant'
                            ? mergeTenantIds(currentTenantIds, selectedTenantIds)
                            : removeTenantIds(currentTenantIds, selectedTenantIds)

                    if (!haveSameTenantIds(currentTenantIds, nextTenantIds)) {
                        await apiClient.put(`/documents/${documentId}/shares`, {
                            tenant_ids: nextTenantIds,
                        })
                    }
                } catch {
                    failedDocumentIds.push(documentId)
                } finally {
                    setCompletedCount(index + 1)
                }
            }

            if (failedDocumentIds.length > 0) {
                setError(
                    failedDocumentIds.length === documentIds.length
                        ? getErrorMessage(null, 'Failed to update access for the selected documents.')
                        : `Updated ${documentIds.length - failedDocumentIds.length} of ${documentIds.length} documents. Review and retry the remaining items.`
                )
                return
            }

            onSaved?.()
            onOpenChange(false)
        } catch (err) {
            setError(getErrorMessage(err, 'Failed to update access for the selected documents.'))
        } finally {
            setSaving(false)
        }
    }

    const actionLabel = mode === 'grant' ? 'Grant Access' : 'Remove Access'
    const selectedCount = selectedTenantIds.length
    const previewTitles = documentTitles.slice(0, 5)
    const remainingTitles = Math.max(0, documentTitles.length - previewTitles.length)

    return (
        <Dialog open={open} onOpenChange={(nextOpen) => !saving && onOpenChange(nextOpen)}>
            <DialogContent className="max-w-3xl">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Share2 className="h-5 w-5 text-primary" />
                        Bulk Access Management
                    </DialogTitle>
                    <DialogDescription>
                        Apply tenant access changes to {documentIds.length} selected document{documentIds.length === 1 ? '' : 's'}.
                    </DialogDescription>
                </DialogHeader>

                <DialogBody className="space-y-4">
                    <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
                        <div className="rounded-lg border bg-muted/20 px-4 py-3">
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <div>
                                    <p className="text-sm font-medium">Selected Documents</p>
                                    <p className="text-xs text-muted-foreground">
                                        Existing shares are preserved unless you explicitly remove them.
                                    </p>
                                </div>
                                <Badge variant="secondary">{documentIds.length} documents selected</Badge>
                            </div>
                            <ScrollArea className="h-[144px] pr-2">
                                <ul className="space-y-2">
                                    {previewTitles.map((title) => (
                                        <li key={title} className="truncate rounded-md border bg-background px-3 py-2 text-sm">
                                            {title}
                                        </li>
                                    ))}
                                    {remainingTitles > 0 && (
                                        <li className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
                                            +{remainingTitles} more document{remainingTitles === 1 ? '' : 's'}
                                        </li>
                                    )}
                                </ul>
                            </ScrollArea>
                        </div>

                        <div className="rounded-lg border bg-muted/20 px-4 py-3">
                            <div className="mb-3">
                                <p className="text-sm font-medium">Batch Action</p>
                                <p className="text-xs text-muted-foreground">
                                    Choose whether to add or remove tenant access without replacing unrelated shares.
                                </p>
                            </div>
                            <div className="grid gap-2">
                                <Button
                                    type="button"
                                    variant={mode === 'grant' ? 'default' : 'outline'}
                                    className="justify-start"
                                    onClick={() => setMode('grant')}
                                >
                                    <UserPlus className="mr-2 h-4 w-4" />
                                    Add access
                                </Button>
                                <Button
                                    type="button"
                                    variant={mode === 'revoke' ? 'destructive' : 'outline'}
                                    className="justify-start"
                                    onClick={() => setMode('revoke')}
                                >
                                    <UserMinus className="mr-2 h-4 w-4" />
                                    Remove access
                                </Button>
                            </div>
                            <div className="mt-4 rounded-lg border bg-background px-3 py-3">
                                <div className="flex items-center justify-between gap-3">
                                    <div>
                                        <p className="text-sm font-medium">Tenant selection</p>
                                        <p className="text-xs text-muted-foreground">
                                            {mode === 'grant'
                                                ? 'Selected tenants will be added to every selected document.'
                                                : 'Selected tenants will be removed from every selected document.'}
                                        </p>
                                    </div>
                                    <Badge variant={selectedCount > 0 ? 'secondary' : 'outline'}>
                                        {selectedCount} tenant{selectedCount === 1 ? '' : 's'}
                                    </Badge>
                                </div>
                            </div>
                        </div>
                    </div>

                    {loading ? (
                        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
                            Loading tenant access options…
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

                    {saving && (
                        <div className="rounded-lg border bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
                            Updating access… {completedCount} / {documentIds.length}
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
                    <Button onClick={handleSave} disabled={loading || saving || selectedTenantIds.length === 0}>
                        {saving ? `Applying… ${completedCount}/${documentIds.length}` : actionLabel}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
