import ReactMarkdown from 'react-markdown'
import { Message } from '../store'
import { cn } from '@/lib/utils'
import { User, Loader2 } from 'lucide-react'
import AmberAvatar from './AmberAvatar'
import { useEvidenceStore } from '../../evidence/stores/useEvidenceStore'

interface MessageItemProps {
    message: Message
}

export default function MessageItem({ message }: MessageItemProps) {
    const isAssistant = message.role === 'assistant'

    return (
        <div className={cn(
            "flex w-full space-x-4 p-6",
            isAssistant ? "bg-secondary/30" : "bg-background"
        )}>
            {isAssistant ? (
                <AmberAvatar size="md" />
            ) : (
                <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 bg-muted text-muted-foreground">
                    <User className="w-5 h-5" />
                </div>
            )}

            <div className="flex-1 space-y-2 overflow-hidden">
                <div className="flex items-center space-x-2">
                    <span className="font-semibold text-sm">
                        {isAssistant ? "Amber" : "You"}
                    </span>
                    <span className="text-xs text-muted-foreground">
                        {new Date(message.timestamp).toLocaleTimeString()}
                    </span>
                </div>


                {message.thinking && (
                    <div className="flex items-center space-x-2 text-sm text-muted-foreground italic bg-muted/50 p-2 rounded-md">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>{message.thinking}</span>
                    </div>
                )}

                <div className="prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>

                {message.sources && message.sources.length > 0 && (
                    <div className="mt-4 pt-4 border-t flex flex-wrap gap-2">
                        {message.sources.map((source, idx) => (
                            <button
                                key={source.chunk_id}
                                onClick={() => useEvidenceStore.getState().selectSource(source.chunk_id)}
                                className="text-xs px-2 py-1 rounded bg-muted hover:bg-accent transition-colors border"
                                title={source.content_preview}
                            >
                                [{idx + 1}] {source.title}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
