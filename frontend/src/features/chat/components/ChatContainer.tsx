import { useChatStore } from '../store'
import { useChatStream } from '../hooks/useChatStream'
import MessageList from './MessageList'
import QueryInput from './QueryInput'
import CitationExplorer from './CitationExplorer'
import { useRouterState } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { chatHistoryApi } from '@/lib/api-admin'
import { useCitationStore } from '../store/citationStore'

export default function ChatContainer() {
    const { messages, addMessage, clearMessages } = useChatStore()
    const { activeConversationId, setActiveConversationId, reset: resetCitations } = useCitationStore()
    // Load history when request_id changes
    const { startStream, isStreaming, resetConversation, setConversationId } = useChatStream()
    const routerState = useRouterState()
    // Type casting for search params
    const searchParams = routerState.location.search as { request_id?: string }
    const requestId = searchParams.request_id

    // Dynamic title state
    const [title, setTitle] = useState('New Conversation')

    // Load history when request_id changes

    useEffect(() => {
        let ignore = false
        if (requestId) {
            // Check if we need to sync the ID to valid conversation flow
            setConversationId(requestId)

            // Sync Citation Store Context
            if (activeConversationId !== requestId) {
                resetCitations()
                setActiveConversationId(requestId)
            }

            const loadHistory = async () => {
                try {
                    // Fetch full conversation details
                    const initialDetail = await chatHistoryApi.getDetail(requestId)

                    if (!ignore && initialDetail) {
                        clearMessages()

                        // Check if we have full history in metadata
                        const history = initialDetail.metadata?.history
                        if (Array.isArray(history) && history.length > 0) {
                            // Reconstruct ALL messages from history array
                            history.forEach((turn: { query: string; answer: string; timestamp?: string }, idx: number) => {
                                // User message
                                if (turn.query) {
                                    addMessage({
                                        id: `user-${requestId}-${idx}`,
                                        role: 'user',
                                        content: turn.query,
                                        timestamp: turn.timestamp || initialDetail.created_at
                                    })
                                }
                                // Assistant message
                                if (turn.answer) {
                                    addMessage({
                                        id: `assistant-${requestId}-${idx}`,
                                        role: 'assistant',
                                        content: turn.answer,
                                        sources: Array.isArray((turn as any).sources)
                                            ? (turn as any).sources
                                            : (typeof (turn as any).sources === 'string'
                                                ? JSON.parse((turn as any).sources)
                                                : undefined),
                                        timestamp: turn.timestamp || initialDetail.created_at,
                                        quality_score: (turn as any).quality_score,
                                        routing_info: (turn as any).routing_info
                                    })
                                }
                            })
                        } else {
                            // Fallback: Single-turn conversation (legacy or first message)
                            if (initialDetail.query_text) {
                                addMessage({
                                    id: `user-${requestId}`,
                                    role: 'user',
                                    content: initialDetail.query_text,
                                    timestamp: initialDetail.created_at
                                })
                            }
                            if (initialDetail.response_text) {
                                addMessage({
                                    id: `assistant-${requestId}`,
                                    role: 'assistant',
                                    content: initialDetail.response_text,
                                    timestamp: initialDetail.created_at
                                })
                            }
                        }

                        // Title from first query (use already-typed history variable)
                        const firstQuery = (Array.isArray(history) && history.length > 0)
                            ? history[0].query
                            : initialDetail.query_text
                        const derivedTitle = firstQuery
                            ? (firstQuery.length > 50 ? firstQuery.substring(0, 50) + '...' : firstQuery)
                            : initialDetail.request_id
                        setTitle(derivedTitle)
                    }
                } catch (e) {
                    if (!ignore) {
                        console.error("Failed to load conversation", e)
                        setTitle('Error loading conversation')
                    }
                }
            }
            loadHistory()
            return () => { ignore = true }
        } else {
            // New chat - clear messages AND reset conversation threading
            clearMessages()
            resetConversation()
            // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: reset title on route change
            setTitle('New Conversation')
        }
    }, [requestId, clearMessages, addMessage, resetConversation, setConversationId, activeConversationId, resetCitations, setActiveConversationId])

    // Update title based on current messages if in new chat flow
    useEffect(() => {
        if (!requestId && messages.length > 0) {
            const firstUserContent = messages.find(m => m.role === 'user')?.content
            if (firstUserContent) {
                const newTitle = firstUserContent.length > 50
                    ? firstUserContent.substring(0, 50) + '...'
                    : firstUserContent
                // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: derive title from messages
                setTitle(newTitle)
            }
        }
    }, [messages, requestId])


    return (
        <main
            className="flex h-full w-full border-x bg-card/10 overflow-hidden"
            aria-label="Chat with Amber"
        >
            <div className="flex-1 flex flex-col min-h-0 bg-background/50 backdrop-blur-sm min-w-0 transition-all duration-500 ease-in-out">
                <header className="p-4 border-b flex justify-between items-center bg-card shrink-0">
                    <div>
                        <h1 className="font-semibold">{title}</h1>
                    </div>
                    {isStreaming && (
                        <div
                            className="flex items-center gap-2 text-sm text-muted-foreground"
                            role="status"
                            aria-live="polite"
                        >
                            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" aria-hidden="true" />
                            <span>Generating response...</span>
                        </div>
                    )}
                </header>

                <div className="flex-1 flex flex-col min-h-0 overflow-hidden relative">
                    {/* Live region for streaming message updates */}
                    <div
                        aria-live="polite"
                        aria-atomic="false"
                        className="contents"
                    >
                        <MessageList messages={messages} />
                    </div>

                    <QueryInput onSend={startStream} disabled={isStreaming} />
                </div>
            </div>

            {/* Citation Explorer Panel (Right Side - Full Height) */}
            <CitationExplorer />
        </main>
    )
}
