import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { rulesApi, GlobalRule, CreateRuleRequest } from '@/lib/api-admin'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { BookOpen, Plus, Trash2, Upload, Loader2, Edit, Check, X, Info } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { FormatDate } from '@/components/ui/date-format'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '@/features/admin/components/PageSkeleton'

export default function RulesPage() {
    const queryClient = useQueryClient()
    const [editingRule, setEditingRule] = useState<GlobalRule | null>(null)
    const [editContent, setEditContent] = useState('')
    const [newRuleContent, setNewRuleContent] = useState('')
    const [showAddForm, setShowAddForm] = useState(false)
    const [showUploadDialog, setShowUploadDialog] = useState(false)
    const [uploadFile, setUploadFile] = useState<File | null>(null)

    // Query rules
    const { data: rules = [], isLoading } = useQuery({
        queryKey: ['admin', 'rules'],
        queryFn: () => rulesApi.list(true)
    })

    // Mutations
    const createMutation = useMutation({
        mutationFn: (data: CreateRuleRequest) => rulesApi.create(data),
        onSuccess: () => {
            toast.success('Rule created')
            queryClient.invalidateQueries({ queryKey: ['admin', 'rules'] })
            setNewRuleContent('')
            setShowAddForm(false)
        },
        onError: () => toast.error('Failed to create rule')
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, content }: { id: string; content: string }) =>
            rulesApi.update(id, { content }),
        onSuccess: () => {
            toast.success('Rule updated')
            queryClient.invalidateQueries({ queryKey: ['admin', 'rules'] })
            setEditingRule(null)
        },
        onError: () => toast.error('Failed to update rule')
    })

    const toggleMutation = useMutation({
        mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
            rulesApi.update(id, { is_active: isActive }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['admin', 'rules'] })
        },
        onError: () => toast.error('Failed to toggle rule')
    })

    const deleteMutation = useMutation({
        mutationFn: (id: string) => rulesApi.delete(id),
        onSuccess: () => {
            toast.success('Rule deleted')
            queryClient.invalidateQueries({ queryKey: ['admin', 'rules'] })
        },
        onError: () => toast.error('Failed to delete rule')
    })

    const uploadMutation = useMutation({
        mutationFn: (file: File) => rulesApi.uploadFile(file, false),
        onSuccess: (data) => {
            toast.success(`Uploaded ${data.created} rules from ${data.source}`)
            queryClient.invalidateQueries({ queryKey: ['admin', 'rules'] })
            setShowUploadDialog(false)
            setUploadFile(null)
        },
        onError: () => toast.error('Failed to upload rules file')
    })

    const handleCreate = () => {
        if (!newRuleContent.trim()) return
        createMutation.mutate({ content: newRuleContent.trim() })
    }

    const handleUpdate = () => {
        if (!editingRule || !editContent.trim()) return
        updateMutation.mutate({ id: editingRule.id, content: editContent.trim() })
    }

    const handleUpload = () => {
        if (!uploadFile) return
        uploadMutation.mutate(uploadFile)
    }

    const startEditing = (rule: GlobalRule) => {
        setEditingRule(rule)
        setEditContent(rule.content)
    }

    const activeRules = rules.filter(r => r.is_active)
    const inactiveRules = rules.filter(r => !r.is_active)

    if (isLoading) {
        return <PageSkeleton />
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="Global Rules"
                description="Define system-wide directives that guide AI reasoning and behavior across all interactions."
                actions={
                    <div className="flex items-center gap-3">
                        <Button
                            variant="outline"
                            onClick={() => setShowUploadDialog(true)}
                            className="h-9 text-xs font-medium"
                        >
                            <Upload className="h-3.5 w-3.5 mr-2" />
                            Import
                        </Button>
                        <Button
                            onClick={() => setShowAddForm(true)}
                            className="h-9 text-xs font-medium"
                        >
                            <Plus className="h-3.5 w-3.5 mr-2" />
                            Add Rule
                        </Button>
                    </div>
                }
            />

            {/* Stats Overview */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                    <Card className="p-4 flex items-center gap-4 hover:shadow-md transition-all duration-300">
                        <div className="p-3 bg-primary/10 rounded-xl">
                            <BookOpen className="h-5 w-5 text-primary" />
                        </div>
                        <div>
                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Total Rules</p>
                            <p className="text-3xl font-bold font-display tracking-tight text-foreground">{rules.length}</p>
                        </div>
                    </Card>
                </motion.div>
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
                    <Card className="p-4 flex items-center gap-4 hover:shadow-md transition-all duration-300">
                        <div className="p-3 bg-primary/10 rounded-xl">
                            <Check className="h-5 w-5 text-primary" />
                        </div>
                        <div>
                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Active</p>
                            <p className="text-3xl font-bold font-display tracking-tight text-foreground">{activeRules.length}</p>
                        </div>
                    </Card>
                </motion.div>
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
                    <Card className="p-4 flex items-center gap-4 hover:shadow-md transition-all duration-300">
                        <div className="p-3 bg-amber-500/10 rounded-xl">
                            <Info className="h-5 w-5 text-amber-500" />
                        </div>
                        <div>
                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Inactive</p>
                            <p className="text-3xl font-bold font-display tracking-tight text-foreground">{inactiveRules.length}</p>
                        </div>
                    </Card>
                </motion.div>
            </div>

            {/* Add Rule Form */}
            <AnimatePresence>
                {showAddForm && (
                    <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="overflow-hidden"
                    >
                        <Card className="p-6 border-primary/20 bg-primary/5 shadow-2xl relative overflow-hidden">
                            <div className="absolute top-0 right-0 p-4 opacity-10">
                                <Plus className="w-32 h-32 text-primary rotate-12" />
                            </div>
                            <div className="relative space-y-4">
                                <div className="flex items-center justify-between">
                                    <h3 className="text-lg font-display font-medium text-primary">Add New Rule</h3>
                                    <Button variant="ghost" size="sm" onClick={() => setShowAddForm(false)} className="h-8 w-8 p-0 rounded-full hover:bg-primary/10">
                                        <X className="w-4 h-4" />
                                    </Button>
                                </div>
                                <Textarea
                                    placeholder="E.g., 'When answering questions about code, always explain the reasoning behind the algorithm...'"
                                    value={newRuleContent}
                                    onChange={(e) => setNewRuleContent(e.target.value)}
                                    rows={4}
                                    className="bg-background/80 border-primary/10 focus:border-primary/30 resize-none text-base font-mono"
                                />
                                <div className="flex gap-3 justify-end pt-2">
                                    <Button
                                        variant="ghost"
                                        onClick={() => {
                                            setShowAddForm(false)
                                            setNewRuleContent('')
                                        }}
                                        className="hover:bg-primary/5"
                                    >
                                        Cancel
                                    </Button>
                                    <Button
                                        onClick={handleCreate}
                                        disabled={!newRuleContent.trim() || createMutation.isPending}
                                        className="shadow-lg shadow-primary/20"
                                    >
                                        {createMutation.isPending && (
                                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                        )}
                                        Create Rule
                                    </Button>
                                </div>
                            </div>
                        </Card>
                    </motion.div>
                )}
            </AnimatePresence>



            {/* Rules List */}

            <div className="grid grid-cols-1 gap-4">
                {rules.length === 0 ? (
                    <Card className="p-16 text-center border-dashed border-white/10 bg-transparent flex flex-col items-center gap-4">
                        <div className="p-4 rounded-full bg-muted/20">
                            <BookOpen className="h-8 w-8 text-muted-foreground/40" />
                        </div>
                        <div className="max-w-xs mx-auto space-y-1">
                            <p className="text-base font-medium text-foreground">No rules defined</p>
                            <p className="text-sm text-muted-foreground text-pretty">Start by adding your first global rule manually or import from a file.</p>
                        </div>
                        <Button
                            className="mt-2"
                            variant="outline"
                            onClick={() => setShowAddForm(true)}
                        >
                            <Plus className="h-4 w-4 mr-2" />
                            Create Rule
                        </Button>
                    </Card>
                ) : (
                    rules.map((rule, index) => (
                        <motion.div
                            key={rule.id}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: index * 0.05 }}
                        >
                            <Card className={cn(
                                "group relative overflow-hidden",
                                rule.is_active
                                    ? "hover:border-primary/20"
                                    : "opacity-70 hover:opacity-100 border-dashed"
                            )}>
                                {/* Status Indicator Bar */}
                                <div className={cn(
                                    "absolute left-0 top-0 bottom-0 w-1 transition-colors",
                                    rule.is_active ? "bg-primary/50 group-hover:bg-primary" : "bg-muted-foreground/20"
                                )} />

                                <div className="p-5 pl-7 flex items-start gap-6">
                                    <div className="flex-1 min-w-0 space-y-3">
                                        <p className={cn(
                                            "text-sm font-mono whitespace-pre-wrap leading-relaxed",
                                            rule.is_active ? "text-foreground/90" : "text-muted-foreground"
                                        )}>
                                            {rule.content}
                                        </p>
                                        <div className="flex items-center gap-4 text-xs font-medium text-muted-foreground/50">
                                            <div className="flex items-center gap-1.5 font-mono">
                                                <span className={cn(
                                                    "w-1.5 h-1.5 rounded-full transition-colors",
                                                    rule.is_active ? "bg-primary shadow-[0_0_8px_rgba(245,158,11,0.4)]" : "bg-current opacity-50"
                                                )} />
                                                ID: {rule.id.slice(0, 8)}
                                            </div>
                                            {rule.source && (
                                                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white/5 border border-white/5">
                                                    Source: {rule.source}
                                                </div>
                                            )}
                                            <FormatDate date={rule.created_at} mode="short" />
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-2 shrink-0 opacity-40 group-hover:opacity-100 transition-opacity duration-300">
                                        <div className="flex items-center gap-2 bg-muted/20 p-1 rounded-lg border border-white/5 mr-2">
                                            <Switch
                                                checked={rule.is_active}
                                                onCheckedChange={(checked) =>
                                                    toggleMutation.mutate({ id: rule.id, isActive: checked })
                                                }
                                                className="scale-75 data-[state=checked]:bg-primary"
                                            />
                                        </div>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-lg transition-colors"
                                            onClick={() => startEditing(rule)}
                                        >
                                            <Edit className="h-4 w-4" />
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                                            onClick={() => deleteMutation.mutate(rule.id)}
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </Button>
                                    </div>
                                </div>
                            </Card>
                        </motion.div>
                    ))
                )}
            </div>


            {/* Edit Dialog - Dark Glass Theme */}
            <Dialog open={!!editingRule} onOpenChange={(open) => !open && setEditingRule(null)}>
                <DialogContent className="bg-zinc-950 border-white/10 shadow-2xl p-0 gap-0 overflow-hidden sm:max-w-lg">
                    <DialogHeader className="p-6 border-b border-white/5 bg-white/[0.02]">
                        <DialogTitle className="font-display tracking-tight text-lg">Edit Rule Configuration</DialogTitle>
                    </DialogHeader>
                    <div className="p-6 space-y-4">
                        <Textarea
                            value={editContent}
                            onChange={(e) => setEditContent(e.target.value)}
                            rows={6}
                            className="bg-muted/10 border-white/10 resize-none font-mono text-sm leading-relaxed focus:bg-muted/20 transition-colors"
                        />
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <Info className="w-3.5 h-3.5" />
                            Changes will apply to new generations immediately.
                        </div>
                    </div>
                    <DialogFooter className="p-4 bg-muted/5 border-t border-white/5 gap-3">
                        <Button variant="ghost" onClick={() => setEditingRule(null)} className="hover:bg-white/5">
                            Cancel
                        </Button>
                        <Button
                            onClick={handleUpdate}
                            disabled={!editContent.trim() || updateMutation.isPending}
                            className="bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/20"
                        >
                            {updateMutation.isPending && (
                                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                            )}
                            Save Changes
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Upload Dialog - Dark Glass Theme */}
            <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
                <DialogContent className="bg-zinc-950 border-white/10 shadow-2xl p-0 gap-0 overflow-hidden sm:max-w-md">
                    <DialogHeader className="p-6 border-b border-white/5 bg-white/[0.02]">
                        <DialogTitle className="font-display tracking-tight text-lg">Import Rules</DialogTitle>
                    </DialogHeader>
                    <div className="p-8 space-y-6">
                        <div className="border-2 border-dashed border-white/10 rounded-xl p-8 flex flex-col items-center justify-center text-center hover:border-primary/30 hover:bg-primary/5 transition-all cursor-pointer group relative">
                            <Input
                                type="file"
                                accept=".txt,.md"
                                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                                className="absolute inset-0 opacity-0 cursor-pointer z-10"
                            />
                            <div className="p-4 bg-muted/20 rounded-full mb-3 group-hover:scale-110 transition-transform duration-300">
                                <Upload className="h-6 w-6 text-muted-foreground group-hover:text-primary transition-colors" />
                            </div>
                            <p className="text-sm font-medium text-foreground group-hover:text-primary transition-colors">
                                {uploadFile ? uploadFile.name : "Click to browse or drag file"}
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                                Supports .txt and .md files (one rule per line)
                            </p>
                        </div>
                    </div>
                    <DialogFooter className="p-4 bg-muted/5 border-t border-white/5 gap-3">
                        <Button variant="ghost" onClick={() => setShowUploadDialog(false)} className="hover:bg-white/5">
                            Cancel
                        </Button>
                        <Button
                            onClick={handleUpload}
                            disabled={!uploadFile || uploadMutation.isPending}
                            className="bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/20"
                        >
                            {uploadMutation.isPending && (
                                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                            )}
                            Import File
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
