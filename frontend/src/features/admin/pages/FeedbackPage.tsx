import { useState } from 'react'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { feedbackApi, FeedbackItem, contextGraphApi, GraphFeedbackItem } from '@/lib/api-admin'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { FormatDate } from '@/components/ui/date-format'
import { ThumbsUp, ThumbsDown, Check, X, Download, Loader2, MessageSquare, ChevronDown, Trash2, BookOpen, Network, Database } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'

export default function FeedbackPage() {
    const queryClient = useQueryClient()
    const [exporting, setExporting] = useState(false)
    const [selectedItem, setSelectedItem] = useState<FeedbackItem | null>(null)
    const [activeTab, setActiveTab] = useState('pending')

    // Query Pending Feedback
    const { data: pendingFeedback = [], isLoading: pendingLoading } = useQuery({
        queryKey: ['feedback', 'pending'],
        queryFn: () => feedbackApi.getPending({ limit: 100 })
    })

    // Query Approved Q&A Library
    const { data: approvedFeedback = [], isLoading: approvedLoading } = useQuery({
        queryKey: ['feedback', 'approved'],
        queryFn: () => feedbackApi.getApproved({ limit: 100 })
    })

    // Query Context Graph stats
    const { data: graphStats } = useQuery({
        queryKey: ['context-graph', 'stats'],
        queryFn: () => contextGraphApi.getStats()
    })

    // Query Context Graph feedback
    const { data: graphFeedback = [], isLoading: graphLoading } = useQuery({
        queryKey: ['context-graph', 'feedback'],
        queryFn: () => contextGraphApi.listFeedback(100)
    })

    // Mutations
    const verifyMutation = useMutation({
        mutationFn: feedbackApi.verify,
        onSuccess: () => {
            toast.success('Added to Q&A Library')
            queryClient.invalidateQueries({ queryKey: ['feedback'] })
            setSelectedItem(null)
        },
        onError: () => toast.error('Failed to verify feedback')
    })

    const rejectMutation = useMutation({
        mutationFn: feedbackApi.reject,
        onSuccess: () => {
            toast.success('Feedback rejected')
            queryClient.invalidateQueries({ queryKey: ['feedback'] })
            setSelectedItem(null)
        },
        onError: () => toast.error('Failed to reject feedback')
    })

    const toggleActiveMutation = useMutation({
        mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
            feedbackApi.toggleActive(id, isActive),
        onSuccess: (_, { isActive }) => {
            toast.success(isActive ? 'Q&A activated' : 'Q&A deactivated')
            queryClient.invalidateQueries({ queryKey: ['feedback', 'approved'] })
        },
        onError: () => toast.error('Failed to toggle status')
    })

    const deleteMutation = useMutation({
        mutationFn: feedbackApi.delete,
        onSuccess: () => {
            toast.success('Deleted from library')
            queryClient.invalidateQueries({ queryKey: ['feedback'] })
        },
        onError: () => toast.error('Failed to delete')
    })

    const deleteGraphFeedbackMutation = useMutation({
        mutationFn: contextGraphApi.deleteFeedback,
        onSuccess: () => {
            toast.success('Removed from Context Graph')
            queryClient.invalidateQueries({ queryKey: ['context-graph'] })
        },
        onError: () => toast.error('Failed to remove from graph')
    })

    const handleExport = async () => {
        setExporting(true)
        try {
            const response = await apiClient.get('/admin/feedback/export', {
                responseType: 'blob',
                params: { format: 'jsonl' }
            })
            const url = window.URL.createObjectURL(new Blob([response.data]))
            const link = document.createElement('a')
            link.href = url
            link.setAttribute('download', 'golden_dataset.jsonl')
            document.body.appendChild(link)
            link.click()
            link.remove()
            toast.success('Dataset exported successfully')
        } catch {
            toast.error('Failed to export dataset')
        } finally {
            setExporting(false)
        }
    }

    const renderPendingReviews = () => {
        if (pendingLoading) {
            return <PageSkeleton mode="default" />
        }

        if (pendingFeedback.length === 0) {
            return (
                <div className="flex flex-col items-center justify-center py-20 text-center space-y-6">
                    <div className="relative">
                        <div className="absolute inset-0 bg-primary/20 blur-3xl rounded-full opacity-20" />
                        <div className="relative p-6 bg-gradient-to-br from-background to-muted rounded-2xl border border-white/5 shadow-2xl ring-1 ring-white/10">
                            <Check className="h-10 w-10 text-primary/80" />
                        </div>
                    </div>
                    <div className="space-y-1">
                        <h3 className="text-xl font-display font-medium text-foreground tracking-tight">All Caught Up</h3>
                        <p className="text-sm text-muted-foreground/60 font-mono tracking-wide">No pending feedback tickets to review</p>
                    </div>
                </div>
            )
        }

        return (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {pendingFeedback.map((item: FeedbackItem, index: number) => (
                    <motion.div
                        key={item.id}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: index * 0.05 }}
                        onClick={() => setSelectedItem(item)}
                    >
                        <Card className="group relative p-5 transition-all duration-300 hover:shadow-lg cursor-pointer flex flex-col gap-4">
                            <div className="flex items-start justify-between">
                                <div className="space-y-1.5">
                                    <div className="flex items-center gap-2">
                                        <span className="text-[10px] font-mono text-primary/60 bg-primary/5 px-1.5 py-0.5 rounded border border-primary/10">
                                            {item.request_id.slice(0, 8)}
                                        </span>
                                        <FormatDate date={item.created_at} mode="short" className="text-[10px] text-muted-foreground/50" />
                                    </div>
                                    <h4 className="font-medium text-sm text-foreground/90 line-clamp-1 group-hover:text-primary transition-colors">
                                        {item.query || "No query text"}
                                    </h4>
                                </div>
                                <span className="flex-shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-full bg-green-500/10 text-green-500 ring-1 ring-green-500/20">
                                    <ThumbsUp className="w-3 h-3" />
                                </span>
                            </div>

                            <div className="flex-1">
                                <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">
                                    {item.answer || "No answer text"}
                                </p>
                            </div>

                            <div className="flex items-center justify-between pt-4 border-t border-white/5">
                                <div className="flex items-center gap-2">
                                    {item.comment && (
                                        <span className="flex items-center gap-1 text-[10px] text-muted-foreground/70 bg-muted/30 px-2 py-1 rounded-full">
                                            <MessageSquare className="w-3 h-3" /> Commented
                                        </span>
                                    )}
                                </div>

                                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity translate-y-1 group-hover:translate-y-0 duration-200">
                                    <Button
                                        size="icon"
                                        variant="ghost"
                                        className="h-7 w-7 text-destructive hover:text-destructive hover:bg-destructive/10 rounded-lg"
                                        onClick={(e) => { e.stopPropagation(); rejectMutation.mutate(item.id); }}
                                    >
                                        <X className="w-3.5 h-3.5" />
                                    </Button>
                                    <Button
                                        size="icon"
                                        variant="ghost"
                                        className="h-7 w-7 text-primary hover:text-primary hover:bg-primary/10 rounded-lg"
                                        onClick={(e) => { e.stopPropagation(); verifyMutation.mutate(item.id); }}
                                    >
                                        <Check className="w-3.5 h-3.5" />
                                    </Button>
                                </div>
                            </div>
                        </Card>
                    </motion.div>
                ))}
            </div>
        )
    }

    const renderQALibrary = () => {
        if (approvedLoading) {
            return (
                <div className="flex justify-center p-12">
                    <Loader2 className="h-6 w-6 animate-spin text-primary/50" />
                </div>
            )
        }

        if (approvedFeedback.length === 0) {
            return (
                <div className="flex flex-col items-center justify-center py-20 text-center space-y-6">
                    <div className="relative">
                        <div className="absolute inset-0 bg-muted-foreground/10 blur-3xl rounded-full opacity-20" />
                        <div className="relative p-6 bg-gradient-to-br from-background to-muted rounded-2xl border border-white/5 shadow-2xl ring-1 ring-white/10">
                            <BookOpen className="h-10 w-10 text-muted-foreground/50" />
                        </div>
                    </div>
                    <div className="space-y-1">
                        <h3 className="text-xl font-display font-medium text-foreground tracking-tight">Library Empty</h3>
                        <p className="text-sm text-muted-foreground/60 font-mono tracking-wide">Approved items will appear here</p>
                    </div>
                </div>
            )
        }

        return (
            <div className="grid grid-cols-1 gap-4">
                {approvedFeedback.map((item: FeedbackItem, index: number) => (
                    <motion.div
                        key={item.id}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: index * 0.05 }}
                    >
                        <Card className={cn(
                            "group border transition-all duration-300 overflow-hidden",
                            item.is_active ? "border-white/5 bg-card/50 hover:bg-card/80 hover:border-primary/20 hover:shadow-md" : "border-dashed border-white/5 bg-muted/10 opacity-60 hover:opacity-100"
                        )}>
                            <Collapsible>
                                <div className="p-5 flex items-start gap-5">
                                    <CollapsibleTrigger asChild>
                                        <div className="flex-1 min-w-0 space-y-3 cursor-pointer text-left group/trigger">
                                            <div className="flex items-center gap-3">
                                                <span className={cn(
                                                    "w-1.5 h-1.5 rounded-full transition-colors",
                                                    item.is_active ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.4)]" : "bg-muted-foreground/30"
                                                )} />
                                                <h4 className="font-medium text-foreground text-base truncate pr-4 group-hover/trigger:text-primary transition-colors">
                                                    {item.query || <span className="text-muted-foreground italic">No query available</span>}
                                                </h4>
                                            </div>

                                            <div className="flex items-center gap-4 text-xs text-muted-foreground/60 font-mono">
                                                <span>ID: {item.id.slice(0, 8)}</span>
                                                <span className="w-px h-3 bg-white/10" />
                                                <FormatDate date={item.created_at} mode="short" />
                                            </div>
                                        </div>
                                    </CollapsibleTrigger>

                                    <div className="flex items-center gap-4 shrink-0">
                                        <div className="flex items-center gap-2 bg-muted/20 p-1 rounded-lg border border-white/5">
                                            <Switch
                                                checked={item.is_active ?? true}
                                                onCheckedChange={(checked) => toggleActiveMutation.mutate({ id: item.id, isActive: checked })}
                                                className="scale-75 data-[state=checked]:bg-emerald-500"
                                            />
                                        </div>
                                        <Button
                                            size="icon"
                                            variant="ghost"
                                            className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                                            onClick={() => deleteMutation.mutate(item.id)}
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </Button>
                                        <CollapsibleTrigger asChild>
                                            <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg hover:bg-muted/50">
                                                <ChevronDown className="h-4 w-4 transition-transform duration-300 group-data-[state=open]:rotate-180" />
                                            </Button>
                                        </CollapsibleTrigger>
                                    </div>
                                </div>

                                <CollapsibleContent>
                                    <div className="px-5 pb-5 pt-0 pl-9">
                                        <div className="relative">
                                            <div className="absolute left-0 top-0 bottom-0 w-px bg-white/5" />
                                            <div className="pl-6 pt-2">
                                                <div className="p-4 bg-muted/30 rounded-xl border border-white/5 text-sm leading-relaxed text-muted-foreground">
                                                    {item.answer || <span className="text-muted-foreground italic">No answer available</span>}
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </CollapsibleContent>
                            </Collapsible>
                        </Card>
                    </motion.div>
                ))}
            </div>
        )
    }

    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8">
            <PageHeader
                title="Verified Q&A"
                description="Curate high-quality examples to improve the assistant's performance through few-shot prompting."
                actions={
                    <Button
                        onClick={handleExport}
                        disabled={exporting}
                        variant="outline"
                        className="h-9 text-xs font-medium"
                    >
                        {exporting ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-2 h-3.5 w-3.5" />}
                        Export JSONL
                    </Button>
                }
            />

            {/* Main Tabs Layout */}
            <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
                <TabsList className="bg-muted/30 border border-white/5 p-1">
                    <TabsTrigger value="pending" className="gap-2">
                        Pending Reviews
                        {pendingFeedback.length > 0 && (
                            <span className="flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-orange-500/10 text-orange-500 text-[10px] font-mono font-bold border border-orange-500/20">
                                {pendingFeedback.length}
                            </span>
                        )}
                    </TabsTrigger>
                    <TabsTrigger value="library" className="gap-2">
                        Known Library
                        <span className="flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-muted text-muted-foreground text-[10px] font-mono font-bold border border-white/10">
                            {approvedFeedback.length}
                        </span>
                    </TabsTrigger>
                    <TabsTrigger value="graph" className="gap-2">
                        <Network className="w-4 h-4" />
                        Context Graph
                        {(graphStats?.total_feedback ?? 0) > 0 && (
                            <span className="flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-blue-500/10 text-blue-500 text-[10px] font-mono font-bold border border-blue-500/20">
                                {graphStats?.total_feedback}
                            </span>
                        )}
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="pending" className="m-0 focus-visible:outline-none">
                    {renderPendingReviews()}
                </TabsContent>

                <TabsContent value="library" className="m-0 focus-visible:outline-none">
                    {renderQALibrary()}
                </TabsContent>

                <TabsContent value="graph" className="m-0 focus-visible:outline-none">
                    <div className="space-y-8">
                        {/* Stats Cards */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                                <Card className="p-4 border-white/5 bg-card/50 hover:bg-card/80 transition-all duration-300">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 bg-blue-500/10 rounded-xl border border-blue-500/10">
                                            <MessageSquare className="h-5 w-5 text-blue-500" />
                                        </div>
                                        <div>
                                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Conversations</p>
                                            <p className="text-3xl font-bold font-display tracking-tight text-foreground">{graphStats?.total_conversations ?? 0}</p>
                                        </div>
                                    </div>
                                </Card>
                            </motion.div>
                            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
                                <Card className="p-4 border-white/5 bg-card/50 hover:bg-card/80 transition-all duration-300">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 bg-purple-500/10 rounded-xl border border-purple-500/10">
                                            <Network className="h-5 w-5 text-purple-500" />
                                        </div>
                                        <div>
                                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Turns</p>
                                            <p className="text-3xl font-bold font-display tracking-tight text-foreground">{graphStats?.total_turns ?? 0}</p>
                                        </div>
                                    </div>
                                </Card>
                            </motion.div>
                            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
                                <Card className="p-4 border-white/5 bg-card/50 hover:bg-card/80 transition-all duration-300">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 bg-emerald-500/10 rounded-xl border border-emerald-500/10">
                                            <ThumbsUp className="h-5 w-5 text-emerald-500" />
                                        </div>
                                        <div>
                                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Positive</p>
                                            <p className="text-3xl font-bold font-display tracking-tight text-foreground">{graphStats?.positive_feedback ?? 0}</p>
                                        </div>
                                    </div>
                                </Card>
                            </motion.div>
                            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
                                <Card className="p-4 border-white/5 bg-card/50 hover:bg-card/80 transition-all duration-300">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 bg-red-500/10 rounded-xl border border-red-500/10">
                                            <ThumbsDown className="h-5 w-5 text-red-500" />
                                        </div>
                                        <div>
                                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Negative</p>
                                            <p className="text-3xl font-bold font-display tracking-tight text-foreground">{graphStats?.negative_feedback ?? 0}</p>
                                        </div>
                                    </div>
                                </Card>
                            </motion.div>
                        </div>

                        {/* Feedback List */}
                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <h3 className="text-lg font-display font-medium text-foreground tracking-tight flex items-center gap-2">
                                    <Network className="w-5 h-5 text-primary" />
                                    Graph Reinforcement History
                                </h3>
                            </div>

                            {graphLoading ? (
                                <div className="flex justify-center p-12">
                                    <Loader2 className="h-8 w-8 animate-spin text-primary/30" />
                                </div>
                            ) : graphFeedback.length === 0 ? (
                                <Card className="p-16 text-center border-dashed border-white/10 bg-transparent flex flex-col items-center gap-4">
                                    <div className="p-4 rounded-full bg-muted/20">
                                        <Database className="h-8 w-8 text-muted-foreground/40" />
                                    </div>
                                    <div className="max-w-xs mx-auto space-y-1">
                                        <p className="text-base font-medium text-foreground">No reinforcement data</p>
                                        <p className="text-sm text-muted-foreground text-pretty">User feedback on conversations will appear here.</p>
                                    </div>
                                </Card>
                            ) : (
                                <div className="grid gap-3">
                                    {graphFeedback.map((item: GraphFeedbackItem, index: number) => (
                                        <motion.div
                                            key={item.feedback_id}
                                            initial={{ opacity: 0, x: -10 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            transition={{ delay: index * 0.05 }}
                                        >
                                            <Card className={cn(
                                                "group border transition-all duration-300 relative overflow-hidden",
                                                "border-white/5 bg-card/40 hover:bg-card/70 hover:border-primary/20 hover:shadow-lg"
                                            )}>
                                                <div className={cn(
                                                    "absolute left-0 top-0 bottom-0 w-1 transition-colors",
                                                    item.is_positive ? "bg-emerald-500/50 group-hover:bg-emerald-500" : "bg-red-500/50 group-hover:bg-red-500"
                                                )} />

                                                <div className="p-4 pl-6 flex items-start gap-4">
                                                    <div className={cn(
                                                        "flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center border",
                                                        item.is_positive
                                                            ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
                                                            : "bg-red-500/10 text-red-500 border-red-500/20"
                                                    )}>
                                                        {item.is_positive ? <ThumbsUp className="w-4 h-4" /> : <ThumbsDown className="w-4 h-4" />}
                                                    </div>

                                                    <div className="flex-1 min-w-0 space-y-1.5">
                                                        <div className="flex items-center justify-between">
                                                            <p className="text-sm font-medium text-foreground/90 truncate pr-4">
                                                                {item.turn_query || <span className="text-muted-foreground italic">Query unavailable</span>}
                                                            </p>
                                                            <Button
                                                                size="icon"
                                                                variant="ghost"
                                                                onClick={() => {
                                                                    if (confirm('Remove this feedback from the Context Graph?')) {
                                                                        deleteGraphFeedbackMutation.mutate(item.feedback_id)
                                                                    }
                                                                }}
                                                                className="h-7 w-7 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
                                                            >
                                                                <Trash2 className="w-4 h-4" />
                                                            </Button>
                                                        </div>

                                                        <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                                                            {item.turn_answer || "Answer unavailable"}
                                                        </p>

                                                        <div className="flex items-center gap-3 pt-1">
                                                            {item.comment && (
                                                                <div className="flex items-center gap-1.5 text-xs text-amber-500/80 bg-amber-500/5 px-2 py-0.5 rounded border border-amber-500/10">
                                                                    <MessageSquare className="w-3 h-3" />
                                                                    <span className="italic">"{item.comment}"</span>
                                                                </div>
                                                            )}
                                                            {item.chunks_affected.length > 0 && (
                                                                <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground font-mono bg-muted/30 px-2 py-0.5 rounded">
                                                                    <Database className="w-3 h-3" />
                                                                    {item.chunks_affected.length} chunks linked
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            </Card>
                                        </motion.div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </TabsContent>
            </Tabs>

            {/* Detail Dialog */}
            <Dialog open={!!selectedItem} onOpenChange={(open) => !open && setSelectedItem(null)}>
                <DialogContent className="max-w-4xl max-h-[85vh] flex flex-col p-0 gap-0 overflow-hidden bg-zinc-950 border-white/10 shadow-2xl">
                    <DialogHeader className="p-6 border-b border-white/5 bg-white/[0.02]">
                        <div className="flex items-center justify-between pr-8">
                            <DialogTitle className="text-lg font-display tracking-tight">Review Candidate</DialogTitle>
                            <span className="font-mono text-[10px] text-muted-foreground bg-white/5 px-2 py-1 rounded border border-white/5">
                                {selectedItem?.request_id}
                            </span>
                        </div>
                    </DialogHeader>

                    <div className="flex-1 overflow-y-auto p-8 space-y-8">
                        {/* Q&A Section */}
                        <div className="space-y-6">
                            <div className="space-y-2">
                                <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
                                    <MessageSquare className="w-3 h-3" /> Question
                                </label>
                                <div className="text-lg font-medium text-foreground leading-relaxed">
                                    {selectedItem?.query}
                                </div>
                            </div>

                            <div className="relative pl-4 border-l-2 border-primary/20 space-y-2">

                                <div className="text-sm text-foreground/90 leading-relaxed whitespace-pre-wrap">
                                    {selectedItem?.answer}
                                </div>
                            </div>
                        </div>

                        {/* User Feedback */}
                        {(selectedItem?.comment) && (
                            <div className="bg-muted/10 rounded-xl p-5 border border-white/5 space-y-3">
                                <div className="flex items-center gap-2 text-amber-500/90">
                                    <MessageSquare className="w-4 h-4" />
                                    <span className="text-xs font-bold uppercase tracking-wide">User Comment</span>
                                </div>
                                <p className="text-sm text-muted-foreground italic">
                                    "{selectedItem.comment}"
                                </p>
                            </div>
                        )}
                    </div>

                    <DialogFooter className="p-6 border-t border-white/5 bg-white/[0.02] gap-3">
                        <Button
                            variant="ghost"
                            onClick={() => rejectMutation.mutate(selectedItem!.id)}
                            disabled={rejectMutation.isPending}
                            className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                        >
                            <X className="mr-2 h-4 w-4" />
                            Discard
                        </Button>
                        <Button
                            onClick={() => verifyMutation.mutate(selectedItem!.id)}
                            disabled={verifyMutation.isPending}
                            className="bg-primary text-primary-foreground hover:bg-primary/90"
                        >
                            {verifyMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}
                            Approve & Add to Library
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
