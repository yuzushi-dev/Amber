
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Trash2, Loader2, User, Calendar, BrainCircuit } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import { UserFact, retentionApi } from '@/lib/api-admin'
import { toast } from 'sonner'
import { formatDistanceToNow } from 'date-fns'

interface FactsTableProps {
    facts: UserFact[]
    isLoading: boolean
    onReload: () => void
}

export default function FactsTable({ facts, isLoading, onReload }: FactsTableProps) {
    const [deletingId, setDeletingId] = useState<string | null>(null)

    const handleDelete = async (id: string) => {
        setDeletingId(id)
        try {
            await retentionApi.deleteFact(id)
            toast.success("Fact deleted", {
                description: "Memory has been removed permanently."
            })
            onReload()
        } catch (error) {
            console.error("Failed to delete fact:", error)
            toast.error("Failed to delete fact")
        } finally {
            setDeletingId(null)
        }
    }

    if (isLoading && facts.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-muted-foreground">
                <Loader2 className="h-8 w-8 animate-spin mb-4" />
                <p>Retrieving memories...</p>
            </div>
        )
    }

    if (facts.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-muted-foreground bg-muted/10 rounded-lg border border-dashed">
                <BrainCircuit className="h-12 w-12 mb-4 opacity-50" />
                <p className="text-lg font-medium">No facts learned yet</p>
                <p className="text-sm">As you chat, I will learn your preferences.</p>
            </div>
        )
    }

    return (
        <div className="rounded-md border bg-card">
            <Table>
                <TableHeader>
                    <TableRow className="bg-muted/50">
                        <TableHead className="w-[180px]">User</TableHead>
                        <TableHead>Fact (Memory)</TableHead>
                        <TableHead className="w-[100px]">Importance</TableHead>
                        <TableHead className="w-[150px]">Learned</TableHead>
                        <TableHead className="w-[80px]"></TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <AnimatePresence mode='popLayout'>
                        {facts.map((fact) => (
                            <motion.tr
                                key={fact.id}
                                layout
                                initial={{ opacity: 0, x: -20 }}
                                animate={{ opacity: 1, x: 0 }}
                                exit={{ opacity: 0, x: 20, backgroundColor: "var(--destructive-transparent)" }}
                                className="group hover:bg-muted/5 transition-colors border-b last:border-0"
                            >
                                <TableCell className="font-mono text-xs text-muted-foreground">
                                    <div className="flex items-center gap-2">
                                        <User className="w-3 h-3" />
                                        {fact.user_id}
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <div className="font-medium text-sm">
                                        {fact.content}
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <Badge variant="secondary" className="bg-primary/5 hover:bg-primary/10 text-primary border-primary/20">
                                        {(fact.importance * 100).toFixed(0)}%
                                    </Badge>
                                </TableCell>
                                <TableCell className="text-muted-foreground text-xs">
                                    <div className="flex items-center gap-2">
                                        <Calendar className="w-3 h-3" />
                                        {formatDistanceToNow(new Date(fact.created_at), { addSuffix: true })}
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 transition-all"
                                        onClick={() => handleDelete(fact.id)}
                                        disabled={deletingId === fact.id}
                                    >
                                        {deletingId === fact.id ? (
                                            <Loader2 className="h-4 w-4 animate-spin" />
                                        ) : (
                                            <Trash2 className="h-4 w-4" />
                                        )}
                                    </Button>
                                </TableCell>
                            </motion.tr>
                        ))}
                    </AnimatePresence>
                </TableBody>
            </Table>
        </div>
    )
}
