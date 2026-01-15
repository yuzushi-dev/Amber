import ReactMarkdown from 'react-markdown'
import { Message } from '../store'
import { cn } from '@/lib/utils'
import { User, Loader2, FileText, Code } from 'lucide-react'
import AmberAvatar from './AmberAvatar'
import { useCitationStore, Citation } from '../store/citationStore'
import { useEffect, useMemo } from 'react'
import { FeedbackButtons } from './FeedbackButtons'
import QualityBadge from './QualityBadge'
import RoutingBadge from './RoutingBadge'

interface MessageItemProps {
    message: Message
    queryContent?: string
}

function parseCitations(content: string, messageId: string): { processedContent: string, citations: Citation[] } {
    const citations: Citation[] = [];
    // Updated regex to match [[Source: 1]], [[Source ID: 1]], [[1]], or [[Source 1]]
    const regex = /\[\[(?:Source(?: ID)?:?)?\s*(\d+)\]\]/g;

    const processedContent = content.replace(regex, (match, value) => {
        const id = `${messageId}-${citations.length}`;
        const label = value; // Group 1 is the ID, which serves as the label here

        citations.push({
            id,
            type: 'Source', // Type is always 'Source' with this regex
            label,
            value,
            content: match
        });

        // Return a special link format we can intercept safely
        return `[Source: ${label}](#citation-${id})`;
    });

    return { processedContent, citations };
}

export default function MessageItem({ message, queryContent }: MessageItemProps) {
    const isAssistant = message.role === 'assistant'
    const { registerCitations, setHoveredCitation, selectCitation, hoveredCitationId } = useCitationStore()

    // Parse citations once when message content changes
    const { processedContent, citations } = useMemo(() =>
        parseCitations(message.content, message.id),
        [message.content, message.id]);

    // Register text-based citations to the store
    useEffect(() => {
        if (citations.length > 0) {
            registerCitations(message.id, citations);
        }
    }, [citations, message.id, registerCitations]);

    const components = useMemo(() => ({
        a: ({ href, children, ...props }: any) => {
            if (href?.startsWith('#citation-')) {
                const id = href.replace('#citation-', '');
                const citation = citations.find(c => c.id === id);
                if (!citation) return <span className="text-red-500">?</span>;

                const isHovered = hoveredCitationId === id;
                const Icon = citation.type === 'Document' ? FileText :
                    citation.type === 'Code' ? Code :
                        FileText;

                return (
                    <span
                        className={cn(
                            "inline-flex items-center gap-1 px-1.5 py-0.5 mx-1 rounded text-xs font-medium cursor-pointer transition-all border select-none align-middle transform active:scale-95",
                            // Dynamic coloring based on type
                            citation.type === 'Document' && "bg-blue-500/10 text-blue-600 border-blue-200 dark:border-blue-800 dark:text-blue-400 hover:bg-blue-500/20",
                            citation.type === 'Code' && "bg-purple-500/10 text-purple-600 border-purple-200 dark:border-purple-800 dark:text-purple-400 hover:bg-purple-500/20",
                            citation.type === 'Source' && "bg-amber-500/10 text-amber-600 border-amber-200 dark:border-amber-800 dark:text-amber-400 hover:bg-amber-500/20",
                            // Bidirectional highlighting
                            isHovered && "ring-2 ring-offset-1 ring-primary z-10 scale-105 shadow-sm"
                        )}
                        onMouseEnter={() => setHoveredCitation(id)}
                        onMouseLeave={() => setHoveredCitation(null)}
                        onClick={(e) => {
                            e.preventDefault();
                            selectCitation(id);
                            useCitationStore.getState().setActiveMessageId(message.id);
                        }}
                    >
                        <Icon className="w-3 h-3 opacity-70" />
                        {children}
                    </span>
                )
            }
            return <a href={href} {...props}>{children}</a>
        }
    }), [citations, hoveredCitationId, setHoveredCitation, selectCitation, message.id]);

    return (
        <div className={cn(
            "flex w-full space-x-6 p-8 group transition-colors duration-500",
            isAssistant
                ? "bg-background/40 backdrop-blur-sm border-b border-white/5 hover:bg-background/60"
                : "bg-transparent" // User messages just sit on the background
        )}>
            {isAssistant ? (
                <div className="shrink-0">
                    <AmberAvatar size="md" className="shadow-[0_0_15px_rgba(251,191,36,0.2)] ring-1 ring-amber-500/20" />
                </div>
            ) : (
                <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0 bg-secondary/50 text-secondary-foreground ring-1 ring-white/10 shadow-inner">
                    <User className="w-5 h-5 opacity-70" />
                </div>
            )}

            <div className="flex-1 space-y-3 overflow-hidden min-w-0">
                <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                        <span className={cn(
                            "font-semibold text-sm tracking-wide",
                            isAssistant ? "text-amber-500" : "text-muted-foreground"
                        )}>
                            {isAssistant ? "AMBER" : "YOU"}
                        </span>
                        <span className="text-xs text-muted-foreground/40 opacity-0 group-hover:opacity-100 transition-opacity">
                            {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                    </div>
                </div>

                {message.thinking && (
                    <div className="flex items-center space-x-3 text-sm text-muted-foreground italic bg-muted/30 p-3 rounded-lg border border-white/5 animate-pulse">
                        <Loader2 className="w-4 h-4 animate-spin text-amber-500/50" />
                        <span className="text-muted-foreground/70">{message.thinking}</span>
                    </div>
                )}

                <div className={cn(
                    "prose prose-sm dark:prose-invert max-w-none leading-relaxed",
                    // Custom prose styles for better readability
                    "prose-headings:font-display prose-headings:tracking-tight",
                    "prose-a:text-primary prose-a:no-underline hover:prose-a:underline",
                    "prose-pre:bg-black/50 prose-pre:backdrop-blur-xl prose-pre:border prose-pre:border-white/10"
                )}>
                    <ReactMarkdown
                        components={components}
                    >
                        {processedContent}
                    </ReactMarkdown>
                </div>

                {/* Footer Area: Feedback, Routing, Quality */}
                {isAssistant && !message.thinking && (
                    <div className="mt-6 pt-4 flex items-center justify-between border-t border-white/5 opacity-80 group-hover:opacity-100 transition-opacity">
                        <div className="flex items-center gap-4">
                            <FeedbackButtons
                                messageId={message.id}
                                requestId={message.request_id}
                                sessionId={message.session_id}
                                content={message.content}
                                relatedQuery={queryContent}
                                initialScore={undefined}
                            />
                            {message.routing_info && (
                                <RoutingBadge routingInfo={message.routing_info} />
                            )}
                        </div>

                        {message.quality_score && (
                            <QualityBadge score={message.quality_score} />
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
