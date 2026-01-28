
import { AlertCircle, Loader2 } from 'lucide-react'
import { calculateGlobalProgress, useUploadStore } from '../stores/useUploadStore'
import { Button } from '@/components/ui/button'
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@/components/ui/tooltip'

export function UploadGlobalIndicator() {
    const { items, setOpen, isOpen } = useUploadStore()

    // Calculate derived state
    const activeItems = items.filter(i => ['queued', 'uploading', 'processing'].includes(i.status))
    const failedItems = items.filter(i => ['failed', 'interrupted', 'missingFile'].includes(i.status))

    if (activeItems.length === 0 && failedItems.length === 0) {
        return null
    }

    // Don't show if modal is open (redundant)
    if (isOpen) {
        return null
    }

    const totalActive = activeItems.length
    const totalFailed = failedItems.length

    const avgProgress = calculateGlobalProgress(items)

    return (
        <div className="fixed bottom-6 right-6 z-50 animate-in slide-in-from-bottom-4">
            <TooltipProvider>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <Button
                            variant="outline"
                            className="h-12 w-12 rounded-full shadow-lg border-primary/20 bg-background relative"
                            onClick={() => setOpen(true)}
                        >
                            {/* Progress Ring Background */}
                            <svg className="absolute inset-0 w-full h-full -rotate-90 p-1">
                                <circle
                                    className="text-muted/20"
                                    stroke="currentColor"
                                    strokeWidth="3"
                                    fill="transparent"
                                    r="20"
                                    cx="24"
                                    cy="24"
                                />
                                <circle
                                    className="text-primary transition-all duration-500 ease-in-out"
                                    stroke="currentColor"
                                    strokeWidth="3"
                                    fill="transparent"
                                    r="20"
                                    cx="24"
                                    cy="24"
                                    strokeDasharray={126}
                                    strokeDashoffset={126 - (126 * avgProgress) / 100}
                                />
                            </svg>

                            {/* Center Icon */}
                            <div className="relative z-10 flex items-center justify-center">
                                {totalFailed > 0 ? (
                                    <AlertCircle className="h-5 w-5 text-destructive" />
                                ) : (
                                    <Loader2 className="h-5 w-5 text-primary animate-spin" />
                                )}
                            </div>

                            {/* Badges */}
                            {totalActive > 0 && (
                                <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[10px] text-primary-foreground">
                                    {totalActive}
                                </span>
                            )}
                        </Button>
                    </TooltipTrigger>
                    <TooltipContent side="left">
                        <div className="flex flex-col gap-1">
                            <p className="font-medium">Uploads in progress</p>
                            <div className="text-xs text-muted-foreground">
                                {totalActive} active, {totalFailed} failed
                            </div>
                        </div>
                    </TooltipContent>
                </Tooltip>
            </TooltipProvider>
        </div>
    )
}
