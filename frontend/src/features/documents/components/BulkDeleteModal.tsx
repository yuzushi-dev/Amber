import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Trash2, Folder, FileText, CheckCircle2, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogTitle,
    DialogClose,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { folderApi, apiClient } from '@/lib/api-client'
import { toast } from 'sonner'

export type BulkDeleteItem = {
    id: string
    title: string
    type: 'folder' | 'document'
}

interface BulkDeleteModalProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    items: BulkDeleteItem[]
    onComplete?: () => void
}

export function BulkDeleteModal({
    open,
    onOpenChange,
    items,
    onComplete
}: BulkDeleteModalProps) {
    const [isDeleting, setIsDeleting] = useState(false)
    const [progress, setProgress] = useState(0)
    const [completedItems, setCompletedItems] = useState<Set<string>>(new Set())
    const [failedItems, setFailedItems] = useState<Set<string>>(new Set())

    // Reset state when opening
    useEffect(() => {
        if (open) {
            setIsDeleting(false)
            setProgress(0)
            setCompletedItems(new Set())
            setFailedItems(new Set())
        }
    }, [open, items])

    const handleConfirm = async () => {
        setIsDeleting(true)
        setProgress(0)
        const total = items.length
        let completed = 0

        // Process in chunks or sequentially to show progress
        // We use sequential here for clear visual feedback, but could be parallelized
        for (const item of items) {
            try {
                if (item.type === 'folder') {
                    // Delete folder and its contents
                    await folderApi.delete(item.id, true)
                } else {
                    // Delete document
                    await apiClient.delete(`/documents/${item.id}`)
                }

                setCompletedItems(prev => new Set(prev).add(item.id))
            } catch (error) {
                console.error(`Failed to delete ${item.type} ${item.id}`, error)
                setFailedItems(prev => new Set(prev).add(item.id))
            } finally {
                completed++
                setProgress((completed / total) * 100)
            }
        }

        // Slight delay before closing if all success
        if (completed === total) {
            setTimeout(() => {
                onOpenChange(false)
                onComplete?.()
                toast.success(`Deleted ${items.length} items`)
            }, 500)
        } else {
            // If there were failures, keep open to show status
            setIsDeleting(false)
            toast.warning(`Completed with some errors`)
        }
    }

    const typeLabel = items.every(i => i.type === 'folder') ? 'Folders'
        : items.every(i => i.type === 'document') ? 'Documents'
            : 'Items'

    return (
        <Dialog open={open} onOpenChange={(val) => !isDeleting && onOpenChange(val)}>
            <DialogContent className="max-w-md p-0 overflow-hidden border-0 bg-transparent shadow-none sm:rounded-xl">
                <AnimatePresence mode="wait">
                    {open && (
                        <motion.div
                            initial={{ opacity: 0, scale: 0.95, y: 10 }}
                            animate={{ opacity: 1, scale: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.95, y: 10 }}
                            transition={{ type: "spring", damping: 25, stiffness: 300 }}
                            className={cn(
                                "relative flex flex-col w-full overflow-hidden",
                                "bg-background border border-border rounded-xl shadow-2xl",
                                "before:absolute before:inset-0 before:bg-gradient-to-b before:from-foreground/10 before:to-transparent before:pointer-events-none"
                            )}
                        >
                            {/* Header */}
                            <div className="bg-destructive/5 px-6 py-6 border-b border-destructive/10">
                                <div className="flex items-center gap-3 text-destructive">
                                    <div className="p-2 bg-destructive/10 rounded-full border border-destructive/10">
                                        <Trash2 className="h-5 w-5" />
                                    </div>
                                    <div className="flex-1">
                                        <DialogTitle className="text-xl font-semibold text-foreground">
                                            Delete {items.length} {typeLabel}
                                        </DialogTitle>
                                        <p className="text-sm text-muted-foreground mt-0.5">
                                            This action cannot be undone.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            {/* Content */}
                            <div className="px-6 py-4">
                                <ScrollArea className="h-[200px] -mr-4 pr-4">
                                    <ul className="space-y-2">
                                        {items.map((item, index) => (
                                            <motion.li
                                                initial={{ opacity: 0, x: -10 }}
                                                animate={{ opacity: 1, x: 0 }}
                                                transition={{ delay: index * 0.05 }}
                                                key={item.id}
                                                className={cn(
                                                    "flex items-center gap-3 p-2 rounded-lg border text-sm transition-colors",
                                                    completedItems.has(item.id)
                                                        ? "bg-destructive/5 border-destructive/10 opacity-50"
                                                        : failedItems.has(item.id)
                                                            ? "bg-destructive/10 border-destructive/20"
                                                            : "bg-muted/30 border-transparent"
                                                )}
                                            >
                                                {/* Icon based on type */}
                                                {item.type === 'folder' ? (
                                                    <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
                                                ) : (
                                                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                                                )}

                                                <span className={cn(
                                                    "flex-1 truncate font-medium",
                                                    completedItems.has(item.id) && "line-through text-muted-foreground"
                                                )}>
                                                    {item.title}
                                                </span>

                                                {/* Status Icon */}
                                                {completedItems.has(item.id) && (
                                                    <CheckCircle2 className="h-4 w-4 text-success" />
                                                )}
                                                {failedItems.has(item.id) && (
                                                    <AlertCircle className="h-4 w-4 text-destructive" />
                                                )}
                                            </motion.li>
                                        ))}
                                    </ul>
                                </ScrollArea>
                            </div>

                            {/* Progress Bar (if deleting) */}
                            {isDeleting && (
                                <div className="px-6 pb-2">
                                    <div className="h-1 w-full bg-muted rounded-full overflow-hidden">
                                        <motion.div
                                            className="h-full bg-destructive"
                                            initial={{ width: 0 }}
                                            animate={{ width: `${progress}%` }}
                                            transition={{ type: "spring", stiffness: 50 }}
                                        />
                                    </div>
                                    <p className="text-xs text-center text-muted-foreground mt-2">
                                        Deleting... {Math.round(progress)}%
                                    </p>
                                </div>
                            )}

                            {/* Footer */}
                            <div className="px-6 py-4 bg-muted/30 flex justify-end gap-3 border-t">
                                <Button
                                    variant="ghost"
                                    onClick={() => onOpenChange(false)}
                                    disabled={isDeleting}
                                >
                                    Cancel
                                </Button>
                                <Button
                                    variant="destructive"
                                    onClick={handleConfirm}
                                    disabled={isDeleting || (items.length === completedItems.size)}
                                    className="shadow-md shadow-destructive/10"
                                >
                                    {isDeleting
                                        ? "Deleting..."
                                        : items.length === completedItems.size
                                            ? "Done"
                                            : `Delete ${typeLabel}`
                                    }
                                </Button>
                            </div>

                            <DialogClose
                                onClose={() => onOpenChange(false)}
                                className={cn(
                                    "absolute top-4 right-4 p-2 rounded-full text-muted-foreground/50 hover:bg-muted/50 transition-colors",
                                    isDeleting && "opacity-0 pointer-events-none"
                                )}
                            />
                        </motion.div>
                    )}
                </AnimatePresence>
            </DialogContent>
        </Dialog>
    )
}
