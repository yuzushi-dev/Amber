import { ReactNode } from 'react'
import { FileQuestion } from 'lucide-react'

interface EmptyStateProps {
    icon?: ReactNode
    title: string
    description?: string
    actions?: ReactNode
    className?: string
}

/**
 * Reusable empty state component for when there's no content to display.
 * 
 * Usage:
 * <EmptyState
 *   icon={<FileText />}
 *   title="No documents yet"
 *   description="Upload your first document to get started"
 *   actions={<Button>Upload</Button>}
 * />
 */
export default function EmptyState({
    icon,
    title,
    description,
    actions,
    className = ''
}: EmptyStateProps) {
    return (
        <div
            className={`flex flex-col items-center justify-center py-16 px-8 text-center rounded-xl border-2 border-dashed border-white/5 bg-white/5 backdrop-blur-sm ${className}`}
            role="status"
            aria-label={title}
        >
            <div className="mb-6 p-4 rounded-full bg-gradient-to-b from-white/10 to-transparent border border-white/5 shadow-inner" aria-hidden="true">
                {icon || <FileQuestion className="w-8 h-8 text-muted-foreground/50" />}
            </div>

            <h3 className="text-xl font-display font-medium text-foreground mb-2 tracking-tight">
                {title}
            </h3>

            {description && (
                <p className="text-muted-foreground max-w-md mb-8 text-sm leading-relaxed">
                    {description}
                </p>
            )}

            {actions && (
                <div className="flex flex-wrap items-center justify-center gap-3">
                    {actions}
                </div>
            )}
        </div>
    )
}
