
import { useState } from 'react'
import { Trash2, Loader2, MessageSquare, Calendar, FolderClock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ConversationSummary, retentionApi } from '@/lib/api-admin'
import { toast } from 'sonner'
import { formatDistanceToNow } from 'date-fns'
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion"

interface SummariesTableProps {
    summaries: ConversationSummary[]
    isLoading: boolean
    onReload: () => void
}

export default function SummariesTable({ summaries, isLoading, onReload }: SummariesTableProps) {
    const [deletingId, setDeletingId] = useState<string | null>(null)

    const handleDelete = async (id: string, e: React.MouseEvent) => {
        e.stopPropagation()
        setDeletingId(id)
        try {
            await retentionApi.deleteSummary(id)
            toast.success("Summary deleted", {
                description: "Conversation history summary has been removed."
            })
            onReload()
        } catch (error) {
            console.error("Failed to delete summary:", error)
            toast.error("Failed to delete summary")
        } finally {
            setDeletingId(null)
        }
    }

    if (isLoading && summaries.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-muted-foreground">
                <Loader2 className="h-8 w-8 animate-spin mb-4" />
                <p>Retrieving archives...</p>
            </div>
        )
    }

    if (summaries.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-muted-foreground bg-muted/10 rounded-lg border border-dashed">
                <FolderClock className="h-12 w-12 mb-4 opacity-50" />
                <p className="text-lg font-medium">No archived conversations</p>
                <p className="text-sm">Summaries appear here after long conversations.</p>
            </div>
        )
    }

    return (
        <div className="rounded-md border bg-card">
            <Accordion type="single" collapsible className="w-full">
                {summaries.map((summary) => (
                    <AccordionItem key={summary.id} value={summary.id} className="border-b last:border-0">
                        <div className="flex items-center px-4 hover:bg-muted/5 transition-colors group">
                            <AccordionTrigger className="flex-1 hover:no-underline py-4">
                                <div className="flex items-center gap-4 text-left">
                                    <MessageSquare className="w-4 h-4 text-primary/70" />
                                    <div className="flex flex-col gap-1">
                                        <span className="font-medium text-sm line-clamp-1">{summary.title}</span>
                                        <span className="text-xs text-muted-foreground flex items-center gap-2">
                                            <Calendar className="w-3 h-3" />
                                            {formatDistanceToNow(new Date(summary.created_at), { addSuffix: true })}
                                            <span className="text-muted-foreground/30">•</span>
                                            ID: <span className="font-mono opacity-70">{summary.id.slice(0, 8)}</span>
                                        </span>
                                    </div>
                                </div>
                            </AccordionTrigger>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 transition-all ml-2"
                                onClick={(e) => handleDelete(summary.id, e)}
                                disabled={deletingId === summary.id}
                            >
                                {deletingId === summary.id ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    <Trash2 className="h-4 w-4" />
                                )}
                            </Button>
                        </div>
                        <AccordionContent className="px-4 pb-4 pt-0">
                            <div className="pl-8 text-sm text-foreground/80 leading-relaxed max-w-3xl">
                                {summary.summary}
                            </div>
                        </AccordionContent>
                    </AccordionItem>
                ))}
            </Accordion>
        </div>
    )
}
