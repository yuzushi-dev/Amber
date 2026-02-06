import { AlertTriangle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'

interface EmbeddingMigrationDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    saving: boolean
    sourceProvider: string
    sourceModel: string
    targetProvider: string | null
    targetModel: string | null
    availableModels: string[]
    onModelChange: (model: string) => void
    onCancel: () => void
    onConfirm: () => void
}

export function EmbeddingMigrationDialog({
    open,
    onOpenChange,
    saving,
    sourceProvider,
    sourceModel,
    targetProvider,
    targetModel,
    availableModels,
    onModelChange,
    onCancel,
    onConfirm,
}: EmbeddingMigrationDialogProps) {
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="p-0 gap-0 overflow-hidden sm:max-w-md">
                <DialogHeader className="p-6 border-b border-white/5 bg-foreground/[0.02]">
                    <DialogTitle className="font-display tracking-tight text-lg flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-warning-muted">
                            <AlertTriangle className="h-5 w-5 text-warning" />
                        </div>
                        Embedding Model Change
                    </DialogTitle>
                </DialogHeader>

                <div className="p-6 space-y-5">
                    <div className="p-4 rounded-lg bg-muted/10 border border-white/5 space-y-4">
                        <div className="space-y-1">
                            <label className="text-sm font-medium text-foreground">Target Model</label>
                            <Select
                                value={targetModel || ''}
                                onValueChange={onModelChange}
                            >
                                <SelectTrigger>
                                    <SelectValue placeholder="Select model" />
                                </SelectTrigger>
                                <SelectContent>
                                    {availableModels.map((model) => (
                                        <SelectItem key={model} value={model}>
                                            {model}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <p className="text-sm text-muted-foreground leading-relaxed">
                            You are migrating from{' '}
                            <span className="font-mono text-foreground bg-muted/50 px-1.5 py-0.5 rounded">
                                {sourceProvider}/{sourceModel}
                            </span>{' '}
                            to{' '}
                            <span className="font-mono text-primary bg-primary/10 px-1.5 py-0.5 rounded">
                                {targetProvider}/{targetModel}
                            </span>
                        </p>
                    </div>

                    <div className="flex items-start gap-3 p-4 rounded-lg bg-destructive/5 border border-destructive/10">
                        <AlertTriangle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
                        <div className="space-y-2">
                            <p className="text-sm font-medium text-destructive">This action requires a full data migration</p>
                            <ul className="text-xs text-destructive/80 space-y-1 list-disc list-inside">
                                <li>All existing vector embeddings will be deleted</li>
                                <li>Documents will be queued for re-processing</li>
                                <li>Search may be limited until complete</li>
                            </ul>
                        </div>
                    </div>

                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Info className="w-3.5 h-3.5" />
                        You'll be redirected to monitor the migration progress.
                    </div>
                </div>

                <DialogFooter className="p-4 bg-muted/5 border-t border-white/5 gap-3">
                    <Button
                        variant="ghost"
                        onClick={onCancel}
                        disabled={saving}
                        className="hover:bg-foreground/5"
                    >
                        Cancel
                    </Button>
                    <Button
                        onClick={onConfirm}
                        disabled={saving}
                        className="bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/20"
                    >
                        {saving ? 'Processing...' : 'Proceed with Migration'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
