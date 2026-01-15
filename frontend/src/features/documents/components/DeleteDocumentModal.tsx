import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogTitle,
    DialogClose,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

interface DeleteDocumentModalProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    documentTitle: string
    onConfirm: () => Promise<void>
}

export default function DeleteDocumentModal({
    open,
    onOpenChange,
    documentTitle,
    onConfirm,
}: DeleteDocumentModalProps) {
    const [isLoading, setIsLoading] = useState(false)

    const handleConfirm = async () => {
        try {
            setIsLoading(true)
            await onConfirm()
        } catch (error) {
            console.error(error)
        } finally {
            setIsLoading(false)
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            {/* 
              We use a transparent border/bg for the base DialogContent 
              and build our own card inside for better animation control 
            */}
            <DialogContent className="max-w-md p-0 overflow-hidden border-0 bg-transparent shadow-none sm:rounded-2xl">
                <AnimatePresence mode="wait">
                    {open && (
                        <motion.div
                            initial={{ opacity: 0, scale: 0.95, y: 10 }}
                            animate={{ opacity: 1, scale: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.95, y: 10 }}
                            transition={{
                                type: "spring",
                                damping: 25,
                                stiffness: 300,
                            }}
                            className={cn(
                                "relative flex flex-col w-full overflow-hidden",
                                "bg-[#09090b] border border-white/10 rounded-2xl shadow-2xl",
                                "before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/[0.08] before:to-transparent before:pointer-events-none"
                            )}
                        >
                            {/* Decorative Top Glow */}
                            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-3/4 h-24 bg-red-500/20 blur-[60px] pointer-events-none" />

                            {/* Header / Icon */}
                            <div className="flex flex-col items-center pt-8 pb-4 px-6 relative z-10">
                                <motion.div
                                    initial={{ scale: 0.8, rotate: -10 }}
                                    animate={{ scale: 1, rotate: 0 }}
                                    transition={{
                                        delay: 0.1,
                                        type: "spring",
                                        stiffness: 200
                                    }}
                                    className="w-16 h-16 rounded-full bg-red-500/10 flex items-center justify-center mb-4 border border-red-500/20 shadow-[0_0_15px_rgba(239,68,68,0.2)]"
                                >
                                    <Trash2 className="w-8 h-8 text-red-500" strokeWidth={1.5} />
                                </motion.div>

                                <DialogTitle className="text-2xl font-semibold text-center text-foreground tracking-tight">
                                    Delete Document
                                </DialogTitle>
                            </div>

                            {/* Body Content */}
                            <div className="px-8 pb-8 text-center space-y-4 relative z-10">
                                <p className="text-muted-foreground text-[15px] leading-relaxed">
                                    Are you sure you want to permanently delete
                                    <span className="block my-3 p-3 bg-muted/40 border border-white/5 rounded-lg text-foreground font-mono text-sm break-all font-medium select-all shadow-inner">
                                        {documentTitle}
                                    </span>
                                </p>

                                <div className="flex items-start gap-3 p-3 text-left rounded-lg bg-red-500/5 border border-red-500/10">
                                    <AlertTriangle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
                                    <span className="text-xs text-red-500/90 font-medium leading-relaxed">
                                        This action is irreversible. All chunks, extracted entities, and relationships associated with this document will be removed.
                                    </span>
                                </div>
                            </div>

                            {/* Actions */}
                            <div className="p-4 bg-muted/30 border-t border-white/5 flex gap-3 justify-end items-center">
                                <Button
                                    variant="ghost"
                                    onClick={() => onOpenChange(false)}
                                    disabled={isLoading}
                                    className="hover:bg-muted/50 text-muted-foreground hover:text-foreground"
                                >
                                    Cancel
                                </Button>
                                <Button
                                    variant="destructive"
                                    onClick={handleConfirm}
                                    disabled={isLoading}
                                    className="bg-red-600 hover:bg-red-700 text-white shadow-lg shadow-red-900/20 relative overflow-hidden"
                                >
                                    {isLoading ? (
                                        <div className="flex items-center gap-2">
                                            <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                            <span>Deleting...</span>
                                        </div>
                                    ) : (
                                        "Delete Document"
                                    )}
                                </Button>
                            </div>

                            <DialogClose
                                onClose={() => onOpenChange(false)}
                                className={`absolute top-4 right-4 text-muted-foreground/50 hover:text-foreground transition-colors ${isLoading ? 'pointer-events-none opacity-50' : ''}`}
                            />
                        </motion.div>
                    )}
                </AnimatePresence>
            </DialogContent>
        </Dialog>
    )
}
