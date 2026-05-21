
import { useState, useEffect, useCallback } from 'react'
import {
    groupsApi, keysApi,
    Group, GroupMemberItem, GroupFolderItem, ApiKeyResponse,
} from '@/lib/api-admin'
import { folderApi, Folder } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
    ConfirmDialog,
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogBody, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import {
    Users, Plus, Trash, RefreshCw, FolderOpen, Key, Settings2, ShieldOff, Shield,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { PageHeader } from './PageHeader'
import { PageSkeleton } from './PageSkeleton'

// ─── Detail Dialog ────────────────────────────────────────────────────────────

interface GroupDetailDialogProps {
    group: Group
    allKeys: ApiKeyResponse[]
    allFolders: Folder[]
    onClose: () => void
}

function GroupDetailDialog({ group, allKeys, allFolders, onClose }: GroupDetailDialogProps) {
    const [members, setMembers] = useState<GroupMemberItem[]>([])
    const [folders, setFolders] = useState<GroupFolderItem[]>([])
    const [loadingMembers, setLoadingMembers] = useState(false)
    const [loadingFolders, setLoadingFolders] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const [selectedKeyIds, setSelectedKeyIds] = useState<Set<string>>(new Set())
    const [selectedFolderIds, setSelectedFolderIds] = useState<Set<string>>(new Set())
    const [keySearch, setKeySearch] = useState('')
    const [folderSearch, setFolderSearch] = useState('')
    const [addingMember, setAddingMember] = useState(false)
    const [addingFolder, setAddingFolder] = useState(false)

    const fetchMembers = useCallback(async () => {
        setLoadingMembers(true)
        try {
            setMembers(await groupsApi.listMembers(group.id))
        } catch {
            setError('Failed to load members')
        } finally {
            setLoadingMembers(false)
        }
    }, [group.id])

    const fetchFolders = useCallback(async () => {
        setLoadingFolders(true)
        try {
            setFolders(await groupsApi.listFolders(group.id))
        } catch {
            setError('Failed to load folders')
        } finally {
            setLoadingFolders(false)
        }
    }, [group.id])

    useEffect(() => {
        fetchMembers()
        fetchFolders()
    }, [fetchMembers, fetchFolders])

    const handleAddMembers = async () => {
        if (selectedKeyIds.size === 0) return
        setAddingMember(true)
        setError(null)
        try {
            await Promise.all([...selectedKeyIds].map(kid => groupsApi.addMember(group.id, kid)))
            setSelectedKeyIds(new Set())
            await fetchMembers()
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : 'Failed to add members')
        } finally {
            setAddingMember(false)
        }
    }

    const toggleKeySelection = (keyId: string) => {
        setSelectedKeyIds(prev => {
            const next = new Set(prev)
            if (next.has(keyId)) next.delete(keyId)
            else next.add(keyId)
            return next
        })
    }

    const handleRemoveMember = async (apiKeyId: string) => {
        setError(null)
        try {
            await groupsApi.removeMember(group.id, apiKeyId)
            await fetchMembers()
        } catch {
            setError('Failed to remove member')
        }
    }

    const handleGrantFolders = async () => {
        if (selectedFolderIds.size === 0) return
        setAddingFolder(true)
        setError(null)
        try {
            await Promise.all([...selectedFolderIds].map(fid => groupsApi.grantFolder(group.id, fid)))
            setSelectedFolderIds(new Set())
            await fetchFolders()
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : 'Failed to grant folders')
        } finally {
            setAddingFolder(false)
        }
    }

    const toggleFolderSelection = (folderId: string) => {
        setSelectedFolderIds(prev => {
            const next = new Set(prev)
            if (next.has(folderId)) next.delete(folderId)
            else next.add(folderId)
            return next
        })
    }

    const handleRevokeFolder = async (folderId: string) => {
        setError(null)
        try {
            await groupsApi.revokeFolder(group.id, folderId)
            await fetchFolders()
        } catch {
            setError('Failed to revoke folder')
        }
    }

    const memberKeyIds = new Set(members.map(m => m.api_key_id))
    const grantedFolderIds = new Set(folders.map(f => f.folder_id))

    const availableKeys = allKeys
        .filter(k => !memberKeyIds.has(k.id))
        .filter(k => k.name.toLowerCase().includes(keySearch.toLowerCase()))
    const availableFolders = allFolders
        .filter(f => !grantedFolderIds.has(f.id))
        .filter(f => f.name.toLowerCase().includes(folderSearch.toLowerCase()))

    const keyName = (id: string) => allKeys.find(k => k.id === id)?.name ?? id
    const folderName = (id: string) => allFolders.find(f => f.id === id)?.name ?? id

    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <div className="flex items-center justify-between">
                        <div>
                            <DialogTitle>{group.name}</DialogTitle>
                            {group.description && (
                                <p className="text-sm text-muted-foreground mt-1">{group.description}</p>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            <span className={cn(
                                "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border",
                                group.is_active
                                    ? "bg-success-muted text-success border-success/20"
                                    : "bg-destructive/10 text-destructive border-destructive/20"
                            )}>
                                <div className={cn("w-1.5 h-1.5 rounded-full", group.is_active ? "bg-success" : "bg-destructive")} />
                                {group.is_active ? 'Active' : 'Inactive'}
                            </span>
                            <DialogClose onClose={onClose} />
                        </div>
                    </div>
                </DialogHeader>

                <DialogBody>
                    {error && (
                        <Alert variant="destructive" dismissible onDismiss={() => setError(null)} className="mb-4">
                            <AlertDescription>{error}</AlertDescription>
                        </Alert>
                    )}

                    {/* Members Section */}
                    <div className="space-y-3">
                        <h3 className="text-sm font-semibold flex items-center gap-2">
                            <Key className="w-4 h-4 text-muted-foreground" />
                            API Keys
                            <span className="ml-auto bg-muted px-1.5 py-0.5 rounded text-xs text-foreground font-mono">
                                {loadingMembers ? '…' : members.length}
                            </span>
                        </h3>

                        <div className="space-y-1.5">
                            {members.length === 0 && !loadingMembers && (
                                <p className="text-xs text-muted-foreground italic">No members yet</p>
                            )}
                            {members.map(m => (
                                <div key={m.api_key_id} className="flex items-center justify-between text-sm p-2 rounded-lg bg-muted/40 border">
                                    <div className="flex items-center gap-2">
                                        <div className="w-1.5 h-1.5 rounded-full bg-primary" />
                                        <span className="font-medium">{keyName(m.api_key_id)}</span>
                                        <span className="text-[10px] font-mono text-muted-foreground">{m.role}</span>
                                    </div>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-6 w-6 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                        onClick={() => handleRemoveMember(m.api_key_id)}
                                    >
                                        <Trash className="w-3.5 h-3.5" />
                                    </Button>
                                </div>
                            ))}
                        </div>

                        {(availableKeys.length > 0 || keySearch) && (
                            <div className="mt-3 space-y-2">
                                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                                    Add members
                                </p>
                                <Input
                                    placeholder="Search API keys…"
                                    value={keySearch}
                                    onChange={e => setKeySearch(e.target.value)}
                                    className="h-8 text-sm"
                                />
                                <div className="rounded-lg border divide-y max-h-48 overflow-y-auto">
                                    {availableKeys.length === 0 ? (
                                        <p className="text-xs text-muted-foreground italic px-3 py-2">No results</p>
                                    ) : availableKeys.map(k => (
                                        <label
                                            key={k.id}
                                            className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-muted/40 transition-colors"
                                        >
                                            <input
                                                type="checkbox"
                                                checked={selectedKeyIds.has(k.id)}
                                                onChange={() => toggleKeySelection(k.id)}
                                                className="accent-primary w-4 h-4 shrink-0"
                                            />
                                            <div className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
                                            <span className="text-sm">{k.name}</span>
                                        </label>
                                    ))}
                                </div>
                                <Button
                                    size="sm"
                                    onClick={handleAddMembers}
                                    disabled={selectedKeyIds.size === 0 || addingMember}
                                    className="w-full"
                                >
                                    {addingMember
                                        ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-2" />
                                        : <Plus className="w-3.5 h-3.5 mr-2" />
                                    }
                                    {selectedKeyIds.size > 0
                                        ? `Add ${selectedKeyIds.size} member${selectedKeyIds.size > 1 ? 's' : ''}`
                                        : 'Select members to add'
                                    }
                                </Button>
                            </div>
                        )}
                    </div>

                    <div className="border-t my-5" />

                    {/* Folders Section */}
                    <div className="space-y-3">
                        <h3 className="text-sm font-semibold flex items-center gap-2">
                            <FolderOpen className="w-4 h-4 text-muted-foreground" />
                            Folder Access
                            <span className="ml-auto bg-muted px-1.5 py-0.5 rounded text-xs text-foreground font-mono">
                                {loadingFolders ? '…' : folders.length}
                            </span>
                        </h3>

                        {/* Granted folders */}
                        <div className="space-y-1.5">
                            {folders.length === 0 && !loadingFolders && (
                                <p className="text-xs text-muted-foreground italic">No folders granted</p>
                            )}
                            {folders.map(f => (
                                <div key={f.folder_id} className="flex items-center justify-between text-sm p-2 rounded-lg bg-muted/40 border">
                                    <div className="flex items-center gap-2">
                                        <FolderOpen className="w-3.5 h-3.5 text-muted-foreground" />
                                        <span className="font-medium">{folderName(f.folder_id)}</span>
                                        <span className="text-[10px] font-mono text-muted-foreground">{f.access_mode}</span>
                                    </div>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-6 w-6 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                        onClick={() => handleRevokeFolder(f.folder_id)}
                                    >
                                        <Trash className="w-3.5 h-3.5" />
                                    </Button>
                                </div>
                            ))}
                        </div>

                        {/* Available folders — checkbox list */}
                        {(availableFolders.length > 0 || folderSearch) && (
                            <div className="mt-3 space-y-2">
                                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                                    Add folders
                                </p>
                                <Input
                                    placeholder="Search folders…"
                                    value={folderSearch}
                                    onChange={e => setFolderSearch(e.target.value)}
                                    className="h-8 text-sm"
                                />
                                <div className="rounded-lg border divide-y max-h-48 overflow-y-auto">
                                    {availableFolders.length === 0 ? (
                                        <p className="text-xs text-muted-foreground italic px-3 py-2">No results</p>
                                    ) : availableFolders.map(f => (
                                        <label
                                            key={f.id}
                                            className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-muted/40 transition-colors"
                                        >
                                            <input
                                                type="checkbox"
                                                checked={selectedFolderIds.has(f.id)}
                                                onChange={() => toggleFolderSelection(f.id)}
                                                className="accent-primary w-4 h-4 shrink-0"
                                            />
                                            <FolderOpen className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                                            <span className="text-sm">{f.name}</span>
                                        </label>
                                    ))}
                                </div>
                                <Button
                                    size="sm"
                                    onClick={handleGrantFolders}
                                    disabled={selectedFolderIds.size === 0 || addingFolder}
                                    className="w-full"
                                >
                                    {addingFolder
                                        ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-2" />
                                        : <Plus className="w-3.5 h-3.5 mr-2" />
                                    }
                                    {selectedFolderIds.size > 0
                                        ? `Grant ${selectedFolderIds.size} folder${selectedFolderIds.size > 1 ? 's' : ''}`
                                        : 'Select folders to grant'
                                    }
                                </Button>
                            </div>
                        )}
                    </div>
                </DialogBody>

                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>Close</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function GroupManager() {
    const [groups, setGroups] = useState<Group[]>([])
    const [allKeys, setAllKeys] = useState<ApiKeyResponse[]>([])
    const [allFolders, setAllFolders] = useState<Folder[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const [newName, setNewName] = useState('')
    const [newDesc, setNewDesc] = useState('')
    const [creating, setCreating] = useState(false)

    const [groupToDelete, setGroupToDelete] = useState<{ id: string; name: string } | null>(null)
    const [selectedGroup, setSelectedGroup] = useState<Group | null>(null)

    const fetchAll = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const [groupData, keyData, folderData] = await Promise.all([
                groupsApi.list(),
                keysApi.list(),
                folderApi.list(),
            ])
            setGroups(groupData)
            setAllKeys(keyData)
            setAllFolders(folderData)
        } catch (err: unknown) {
            console.error(err)
            setError('Failed to load groups.')
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchAll()
    }, [fetchAll])

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!newName.trim()) return
        setCreating(true)
        setError(null)
        try {
            await groupsApi.create({ name: newName.trim(), description: newDesc.trim() || undefined })
            setNewName('')
            setNewDesc('')
            fetchAll()
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Failed to create group')
        } finally {
            setCreating(false)
        }
    }

    const handleConfirmDelete = async () => {
        if (!groupToDelete) return
        try {
            await groupsApi.delete(groupToDelete.id)
            fetchAll()
        } catch {
            setError('Failed to delete group')
        } finally {
            setGroupToDelete(null)
        }
    }

    if (loading && groups.length === 0) {
        return <PageSkeleton />
    }

    return (
        <div className="space-y-12">
            <PageHeader
                title="Groups"
                description="Manage intra-tenant groups for selective document access. Each group controls which folders and documents its API keys can see."
                actions={
                    <div className="flex items-center gap-4">
                        <div className="text-right hidden md:block border-l pl-4 my-1">
                            <div className="text-2xl font-bold font-mono text-foreground leading-none">{groups.length}</div>
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

            {/* Create Hero */}
            <div className="relative overflow-hidden rounded-2xl border border-border/50 bg-gradient-to-br from-card to-background shadow-lg">
                <div className="absolute inset-0 bg-primary/5 opacity-50" />
                <div className="relative p-8">
                    <div className="flex flex-col md:flex-row gap-8 items-start">
                        <div className="flex-1 space-y-2">
                            <h2 className="text-2xl font-bold">New Group</h2>
                            <p className="text-muted-foreground">
                                Create a group, then assign API keys and folder access from the group card.
                            </p>
                        </div>

                        <form onSubmit={handleCreate} className="w-full md:w-auto flex flex-col sm:flex-row gap-3 items-end bg-background/50 p-4 rounded-xl border backdrop-blur-sm">
                            <div className="space-y-1.5 w-full sm:w-48">
                                <label className="text-xs font-semibold text-foreground/80 ml-1">Group Name</label>
                                <Input
                                    type="text"
                                    value={newName}
                                    onChange={e => setNewName(e.target.value)}
                                    placeholder="Engineering"
                                    className="px-4 py-2.5 bg-background focus-visible:ring-offset-0"
                                    disabled={creating}
                                />
                            </div>
                            <div className="space-y-1.5 w-full sm:w-56">
                                <label className="text-xs font-semibold text-foreground/80 ml-1">Description (Opt)</label>
                                <Input
                                    type="text"
                                    value={newDesc}
                                    onChange={e => setNewDesc(e.target.value)}
                                    placeholder="Has access to internal guides"
                                    className="px-4 py-2.5 bg-background focus-visible:ring-offset-0"
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

            {/* Group Grid */}
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold flex items-center gap-2">
                        <Users className="w-5 h-5 text-muted-foreground" />
                        Group Directory
                    </h3>
                    <Button variant="ghost" size="sm" onClick={fetchAll} disabled={loading} className="text-muted-foreground hover:text-foreground">
                        <RefreshCw className={cn("w-4 h-4 mr-2", loading && "animate-spin")} />
                        Refresh
                    </Button>
                </div>

                {groups.length === 0 ? (
                    <div className="border-2 border-dashed rounded-xl p-12 text-center text-muted-foreground">
                        <Users className="w-12 h-12 mx-auto mb-4 opacity-20" />
                        <h3 className="text-lg font-medium mb-1">No Groups</h3>
                        <p>Create a group to start controlling document visibility.</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {groups.map((group, index) => (
                            <GroupCard
                                key={group.id}
                                group={group}
                                index={index}
                                onManage={() => setSelectedGroup(group)}
                                onDelete={() => setGroupToDelete({ id: group.id, name: group.name })}
                            />
                        ))}
                    </div>
                )}
            </div>

            {/* Detail Dialog */}
            {selectedGroup && (
                <GroupDetailDialog
                    group={selectedGroup}
                    allKeys={allKeys}
                    allFolders={allFolders}
                    onClose={() => setSelectedGroup(null)}
                />
            )}

            <ConfirmDialog
                open={!!groupToDelete}
                onOpenChange={open => !open && setGroupToDelete(null)}
                title="Delete Group"
                description={`Delete group "${groupToDelete?.name}"? Members and folder grants are removed. This cannot be undone.`}
                confirmText="Delete Group"
                variant="destructive"
                onConfirm={handleConfirmDelete}
            />
        </div>
    )
}

// ─── Group Card ───────────────────────────────────────────────────────────────

interface GroupCardProps {
    group: Group
    index: number
    onManage: () => void
    onDelete: () => void
}

function GroupCard({ group, index, onManage, onDelete }: GroupCardProps) {
    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05 }}
            className="group relative bg-card hover:bg-card/80 border rounded-xl p-6 shadow-sm hover:shadow-md transition-[background-color,box-shadow] duration-300 ease-out cursor-pointer"
            onClick={onManage}
        >
            {/* Delete button */}
            <div className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity z-10 flex gap-1">
                <Button
                    variant="ghost"
                    size="icon"
                    onClick={e => { e.stopPropagation(); onManage() }}
                    className="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted"
                    aria-label={`Manage ${group.name}`}
                >
                    <Settings2 className="w-4 h-4" />
                </Button>
                <Button
                    variant="ghost"
                    size="icon"
                    onClick={e => { e.stopPropagation(); onDelete() }}
                    className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                    aria-label={`Delete ${group.name}`}
                >
                    <Trash className="w-4 h-4" />
                </Button>
            </div>

            <div className="space-y-4">
                <div className="flex items-start justify-between">
                    <div className="space-y-1 pr-16">
                        <h4 className="font-bold text-lg leading-none">{group.name}</h4>
                        {group.description && (
                            <p className="text-xs text-muted-foreground line-clamp-2">{group.description}</p>
                        )}
                    </div>
                </div>

                <div className="flex flex-wrap gap-2 pt-1">
                    <span className={cn(
                        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border",
                        group.is_active
                            ? "bg-success-muted text-success border-success/20"
                            : "bg-destructive/10 text-destructive border-destructive/20"
                    )}>
                        <div className={cn("w-1.5 h-1.5 rounded-full", group.is_active ? "bg-success" : "bg-destructive")} />
                        {group.is_active ? 'Active' : 'Inactive'}
                    </span>
                    {!group.is_active && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border bg-muted text-muted-foreground border-muted">
                            <ShieldOff className="w-3 h-3" />
                            Enforcement off
                        </span>
                    )}
                </div>

                <div className="pt-4 mt-2 border-t flex justify-end items-center text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                        <Shield className="w-3 h-3" />
                        Click to manage members &amp; folders
                    </span>
                </div>
            </div>
        </motion.div>
    )
}
