import { Source } from '../../chat/store'
import { cn } from '@/lib/utils'
import { FileText, ExternalLink } from 'lucide-react'

interface SourceCardProps {
    source: Source
    isActive?: boolean
    onClick?: () => void
}

export default function SourceCard({ source, isActive, onClick }: SourceCardProps) {
    return (
        <div
            className={cn(
                "p-4 rounded-lg border transition-all cursor-pointer",
                isActive ? "border-primary bg-primary/5 ring-1 ring-primary" : "border-border bg-card hover:bg-accent/50"
            )}
            onClick={onClick}
        >
            <div className="flex items-start justify-between mb-2">
                <div className="flex items-center space-x-2 overflow-hidden">
                    <FileText className="w-4 h-4 text-primary shrink-0" />
                    <h4 className="font-semibold text-sm truncate">{source.title}</h4>
                </div>
                {source.score && (
                    <span className="text-[10px] font-mono bg-muted px-1.5 py-0.5 rounded">
                        {(source.score * 100).toFixed(0)}%
                    </span>
                )}
            </div>

            <p className="text-xs text-muted-foreground line-clamp-3 mb-3 leading-relaxed">
                {source.snippet}
            </p>

            <div className="flex items-center justify-between text-[10px] text-muted-foreground font-medium">
                <span>Page {source.page || 1}</span>
                <button className="flex items-center space-x-1 hover:text-primary transition-colors">
                    <span>View full doc</span>
                    <ExternalLink className="w-3 h-3" />
                </button>
            </div>
        </div>
    )
}
