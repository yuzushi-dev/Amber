import { cn } from "@/lib/utils"

interface PageHeaderProps {
    title: string
    description?: string
    actions?: React.ReactNode
    className?: string
}

export function PageHeader({ title, description, actions, className }: PageHeaderProps) {
    return (
        <div className={cn("flex flex-col gap-1 md:flex-row md:items-center md:justify-between", className)}>
            <div className="space-y-1.5">
                <h1 className="text-3xl font-display font-bold tracking-tight text-foreground">{title}</h1>
                {description && (
                    <p className="text-muted-foreground text-sm max-w-2xl">{description}</p>
                )}
            </div>
            {actions && (
                <div className="flex items-center gap-2 mt-4 md:mt-0">
                    {actions}
                </div>
            )}
        </div>
    )
}
