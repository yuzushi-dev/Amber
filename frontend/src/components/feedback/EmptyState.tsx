import { LucideIcon } from 'lucide-react'

interface EmptyStateProps {
    icon: LucideIcon
    title: string
    description: string
    action?: React.ReactNode
}

export default function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
    return (
        <div className="flex flex-col items-center justify-center p-12 text-center space-y-4 animate-in fade-in duration-500">
            <div className="p-4 rounded-full bg-muted">
                <Icon className="w-8 h-8 text-muted-foreground" />
            </div>
            <div className="space-y-2">
                <h3 className="text-xl font-bold tracking-tight">{title}</h3>
                <p className="text-sm text-muted-foreground max-w-xs mx-auto">{description}</p>
            </div>
            {action && (
                <div className="pt-4">
                    {action}
                </div>
            )}
        </div>
    )
}
