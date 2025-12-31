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
            className={`flex flex-col items-center justify-center py-16 px-4 text-center ${className}`}
            role="status"
            aria-label={title}
        >
            <div className="mb-6 p-4 rounded-full bg-muted/50" aria-hidden="true">
                {icon || <FileQuestion className="w-12 h-12 text-muted-foreground" />}
            </div>

            <h3 className="text-xl font-semibold text-foreground mb-2">
                {title}
            </h3>

            {description && (
                <p className="text-muted-foreground max-w-md mb-6">
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
