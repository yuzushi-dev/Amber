import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { feedbackApi, FeedbackItem } from '@/lib/api-admin'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import {
    Dialog,
    DialogContent,
    DialogDescription,
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
import { ThumbsUp, ThumbsDown, Check, X, Download, Loader2, Eye, MessageSquare, ChevronDown, Trash2, Power } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'

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
            return (
                <div className="flex justify-center p-12">
                    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
            )
        }

        if (pendingFeedback.length === 0) {
            return (
                <div className="flex flex-col items-center justify-center p-24 text-center text-muted-foreground space-y-4">
                    <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center">
                        <Check className="h-8 w-8 text-green-500" />
                    </div>
                    <div>
                        <p className="text-xl font-medium text-foreground">All caught up!</p>
                        <p className="text-sm">No pending feedback to review.</p>
                    </div>
                </div>
            )
        }

        return (
            <div className="flex flex-col h-full">
                <div className="grid grid-cols-[180px_1fr_120px_150px] bg-muted/60 border-b border-border flex-shrink-0">
                    <div className="h-12 px-4 pl-6 flex items-center text-sm font-medium text-muted-foreground">Date</div>
                    <div className="h-12 px-4 flex items-center text-sm font-medium text-muted-foreground">Request ID</div>
                    <div className="h-12 px-4 flex items-center text-sm font-medium text-muted-foreground">Score</div>
                    <div className="h-12 px-4 pr-6 flex items-center justify-end text-sm font-medium text-muted-foreground">Actions</div>
                </div>
                <div className="flex-1 overflow-y-auto min-h-0">
                    {pendingFeedback.map((item) => (
                        <div
                            key={item.id}
                            className="grid grid-cols-[180px_1fr_120px_150px] border-b border-border cursor-pointer hover:bg-muted/50 transition-colors group"
                            onClick={() => setSelectedItem(item)}
                        >
                            <div className="p-4 pl-6 font-medium">
                                <FormatDate date={item.created_at} mode="short" />
                            </div>
                            <div className="p-4 font-mono text-xs text-muted-foreground flex items-center">
                                {item.request_id}
                            </div>
                            <div className="p-4 flex items-center">
                                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary border border-primary/20">
                                    <ThumbsUp className="h-3 w-3" /> {item.score}
                                </span>
                            </div>
                            <div className="p-4 pr-6 flex items-center justify-end">
                                <div className="flex gap-1 opacity-60 group-hover:opacity-100 transition-opacity" onClick={(e) => e.stopPropagation()}>
                                    <Button size="sm" variant="ghost" className="h-8 w-8 p-0" onClick={() => setSelectedItem(item)}>
                                        <Eye className="h-4 w-4" />
                                    </Button>
                                    <div className="w-px h-4 bg-border my-auto mx-1" />
                                    <Button size="sm" variant="ghost" className="h-8 w-8 p-0 hover:text-destructive hover:bg-destructive/10" onClick={() => rejectMutation.mutate(item.id)}>
                                        <X className="h-4 w-4" />
                                    </Button>
                                    <Button size="sm" variant="ghost" className="h-8 w-8 p-0 hover:text-primary hover:bg-primary/10" onClick={() => verifyMutation.mutate(item.id)}>
                                        <Check className="h-4 w-4" />
                                    </Button>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        )
    }

    const renderQALibrary = () => {
        if (approvedLoading) {
            return (
                <div className="flex justify-center p-12">
                    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
            )
        }

        if (approvedFeedback.length === 0) {
            return (
                <div className="flex flex-col items-center justify-center p-24 text-center text-muted-foreground space-y-4">
                    <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center">
                        <MessageSquare className="h-8 w-8" />
                    </div>
                    <div>
                        <p className="text-xl font-medium text-foreground">No Q&A pairs yet</p>
                        <p className="text-sm">Approve pending feedback to add items here.</p>
                    </div>
                </div>
            )
        }

        return (
            <div className="p-4 space-y-3 overflow-y-auto">
                {approvedFeedback.map((item) => (
                    <Card key={item.id} className={cn(
                        "border transition-all",
                        item.is_active ? "border-border" : "border-dashed border-muted-foreground/30 opacity-60"
                    )}>
                        <Collapsible>
                            <div className="p-4">
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-2">
                                            <span className="text-xs font-medium text-muted-foreground">Question</span>
                                            <FormatDate date={item.created_at} mode="short" className="text-xs text-muted-foreground" />
                                        </div>
                                        <p className="font-medium text-foreground truncate">
                                            {item.query || <span className="text-muted-foreground italic">No query available</span>}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-3">
                                        <div className="flex items-center gap-2">
                                            <Switch
                                                checked={item.is_active ?? true}
                                                onCheckedChange={(checked) => toggleActiveMutation.mutate({ id: item.id, isActive: checked })}
                                            />
                                        </div>
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            className="h-8 w-8 p-0 hover:text-destructive hover:bg-destructive/10"
                                            onClick={() => deleteMutation.mutate(item.id)}
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </Button>
                                    </div>
                                </div>

                                <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mt-3 group">
                                    <ChevronDown className="h-3 w-3 transition-transform group-data-[state=open]:rotate-180" />
                                    View Answer
                                </CollapsibleTrigger>
                            </div>

                            <CollapsibleContent>
                                <div className="px-4 pb-4 pt-0">
                                    <div className="bg-muted/50 rounded-lg p-4 text-sm">
                                        <span className="text-xs font-medium text-muted-foreground block mb-2">Answer</span>
                                        <p className="text-foreground whitespace-pre-wrap">
                                            {item.answer || <span className="text-muted-foreground italic">No answer available</span>}
                                        </p>
                                    </div>
                                </div>
                            </CollapsibleContent>
                        </Collapsible>
                    </Card>
                ))}
            </div>
        )
    }

    return (
        <div className="flex flex-col space-y-6 p-8 h-[calc(100vh-4rem)] overflow-hidden">
            <div className="flex justify-between items-start">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight text-foreground">
                        Feedback & Q&A Library
                    </h2>
                    <p className="text-muted-foreground mt-2 text-lg">
                        Review feedback and manage verified Q&A examples.
                    </p>
                </div>
                <Button
                    onClick={handleExport}
                    disabled={exporting}
                    variant="default"
                    className="shadow-md"
                >
                    {exporting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
                    Export Dataset
                </Button>
            </div>

            <Card className="flex-1 flex flex-col min-h-0 overflow-hidden border-border bg-card shadow-sm">
                <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-col h-full">
                    <div className="px-6 py-3 border-b border-border bg-muted/40 flex-shrink-0">
                        <TabsList className="bg-transparent gap-4 h-auto p-0">
                            <TabsTrigger
                                value="pending"
                                className="data-[state=active]:bg-background data-[state=active]:shadow-sm rounded-md px-4 py-2"
                            >
                                Pending Reviews
                                <span className="ml-2 px-2 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-mono font-bold">
                                    {pendingFeedback.length}
                                </span>
                            </TabsTrigger>
                            <TabsTrigger
                                value="library"
                                className="data-[state=active]:bg-background data-[state=active]:shadow-sm rounded-md px-4 py-2"
                            >
                                Q&A Library
                                <span className="ml-2 px-2 py-0.5 rounded-full bg-muted text-muted-foreground text-xs font-mono font-bold">
                                    {approvedFeedback.length}
                                </span>
                            </TabsTrigger>
                        </TabsList>
                    </div>

                    <TabsContent value="pending" className="flex-1 overflow-hidden m-0">
                        <CardContent className="p-0 h-full overflow-y-auto">
                            {renderPendingReviews()}
                        </CardContent>
                    </TabsContent>

                    <TabsContent value="library" className="flex-1 overflow-hidden m-0">
                        <CardContent className="p-0 h-full overflow-y-auto">
                            {renderQALibrary()}
                        </CardContent>
                    </TabsContent>
                </Tabs>
            </Card>

            {/* Detail Dialog */}
            <Dialog open={!!selectedItem} onOpenChange={(open) => !open && setSelectedItem(null)}>
                <DialogContent className="max-w-5xl max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
                    <DialogHeader className="p-6 border-b bg-muted/30 relative">
                        <Button
                            variant="ghost"
                            size="icon"
                            className="absolute right-4 top-4 h-8 w-8 rounded-full"
                            onClick={() => setSelectedItem(null)}
                        >
                            <X className="h-4 w-4" />
                            <span className="sr-only">Close</span>
                        </Button>
                        <DialogTitle className="text-lg">Review Feedback</DialogTitle>
                        <DialogDescription>
                            Request: <span className="font-mono text-xs">{selectedItem?.request_id}</span>
                        </DialogDescription>
                        <div className="mt-3">
                            <span className={cn(
                                "inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold",
                                "bg-primary/10 text-primary border border-primary/30"
                            )}>
                                <ThumbsUp className="h-3 w-3" /> Positive Feedback
                            </span>
                        </div>
                    </DialogHeader>

                    <div className="flex-1 overflow-y-auto p-6 space-y-6">
                        <div className="space-y-2">
                            <h4 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                                <MessageSquare className="h-4 w-4" /> User Query
                            </h4>
                            <div className="bg-muted/50 rounded-lg p-4">
                                <p className="text-foreground">
                                    {selectedItem?.query || <span className="text-muted-foreground italic">No query context available</span>}
                                </p>
                            </div>
                        </div>

                        <div className="space-y-2">
                            <h4 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                                <MessageSquare className="h-4 w-4" /> Assistant Response
                            </h4>
                            <div className="bg-muted/50 rounded-lg p-4 max-h-[300px] overflow-y-auto">
                                <p className="text-foreground whitespace-pre-wrap text-sm">
                                    {selectedItem?.answer || <span className="text-muted-foreground italic">No response context available</span>}
                                </p>
                            </div>
                        </div>

                        {selectedItem?.comment && (
                            <div className="space-y-2">
                                <h4 className="text-sm font-medium text-muted-foreground">User Comment</h4>
                                <div className="bg-primary/5 border border-primary/10 rounded-lg p-4">
                                    <p className="text-foreground italic">&ldquo;{selectedItem.comment}&rdquo;</p>
                                </div>
                            </div>
                        )}
                    </div>

                    <DialogFooter className="p-6 border-t bg-muted/30 gap-3">
                        <Button
                            variant="outline"
                            onClick={() => rejectMutation.mutate(selectedItem!.id)}
                            disabled={rejectMutation.isPending}
                            className="border-destructive/30 text-destructive hover:bg-destructive/10"
                        >
                            <X className="mr-2 h-4 w-4" />
                            Reject
                        </Button>
                        <Button
                            onClick={() => verifyMutation.mutate(selectedItem!.id)}
                            disabled={verifyMutation.isPending}
                        >
                            {verifyMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}
                            Add to Q&A Library
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
