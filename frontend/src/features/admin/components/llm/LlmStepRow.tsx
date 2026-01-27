import { ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { LlmStepMeta, LlmStepOverride } from '@/lib/api-admin'

interface LlmStepRowProps {
    step: LlmStepMeta
    override: LlmStepOverride | undefined
    defaultProvider: string
    defaultModel: string
    onEdit: (stepId: string) => void
}

export function LlmStepRow({
    step,
    override,
    defaultProvider,
    defaultModel,
    onEdit
}: LlmStepRowProps) {
    const isOverridden = Boolean(override && Object.values(override).some(v => v !== null && v !== undefined))

    // Determine effective values for display
    const accessProvider = override?.provider || defaultProvider
    const accessModel = override?.model || defaultModel

    return (
        <div
            className={cn(
                "group relative overflow-hidden flex items-center justify-between p-4 rounded-lg border transition-[background-color,border-color,box-shadow,transform] duration-300 ease-out cursor-pointer",
                isOverridden
                    ? "bg-primary/5 border-primary/20 hover:bg-primary/10 hover:border-primary/30"
                    : "bg-foreground/[0.02] border-white/5 hover:bg-foreground/5 hover:border-border/60"
            )}
            onClick={() => onEdit(step.id)}
        >
            <div className="flex-1 min-w-0 mr-4">
                <div className="flex items-center gap-2 mb-0.5">
                    <h4 className="font-medium text-sm text-foreground truncate">
                        {step.label}
                    </h4>
                    {isOverridden && (
                        <Badge variant="secondary" className="text-[9px] h-4 px-1.5 uppercase tracking-wider bg-primary/20 text-primary border-primary/30 font-bold shrink-0">
                            Custom
                        </Badge>
                    )}
                </div>
                <p className="text-xs text-muted-foreground/60 truncate">
                    {step.description}
                </p>
            </div>

            <div className="flex items-center gap-3 shrink-0">
                <div className="text-right hidden lg:block">
                    <div className="text-xs font-medium text-foreground/80 truncate max-w-[140px]">
                        {accessModel}
                    </div>
                    <div className="text-[10px] text-muted-foreground/50 uppercase tracking-wider">
                        {accessProvider}
                    </div>
                </div>

                <ChevronRight className="w-4 h-4 text-muted-foreground/30 group-hover:text-primary/70 transition-colors" />
            </div>
        </div>
    )
}
