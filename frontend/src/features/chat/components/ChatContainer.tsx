import { useChatStore } from '../store'
import { useChatStream } from '../hooks/useChatStream'
import MessageList from './MessageList'
import QueryInput from './QueryInput'
import { useRouterState } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { chatHistoryApi } from '@/lib/api-admin'

export default function ChatContainer() {
    const { messages, addMessage, clearMessages } = useChatStore()
    const { startStream, isStreaming } = useChatStream()
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
            const loadHistory = async () => {
                try {
                    // Fetch full conversation details
                    const initialDetail = await chatHistoryApi.getDetail(requestId)

                    if (!ignore && initialDetail) {
                        clearMessages()

                        // Reconstruct messages
                        // 1. User Message
                        if (initialDetail.query_text) {
                            addMessage({
                                id: `user-${requestId}`,
                                role: 'user',
                                content: initialDetail.query_text,
                                timestamp: initialDetail.created_at
                            })
                        }

                        // 2. Assistant Message
                        if (initialDetail.response_text) {
                            addMessage({
                                id: `assistant-${requestId}`,
                                role: 'assistant',
                                content: initialDetail.response_text,
                                timestamp: initialDetail.created_at
                            })
                        }

                        // Title from query if available
                        const derivedTitle = initialDetail.query_text
                            ? (initialDetail.query_text.length > 50 ? initialDetail.query_text.substring(0, 50) + '...' : initialDetail.query_text)
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
            // New chat - clear messages
            clearMessages()
            setTitle('New Conversation')
        }
    }, [requestId, clearMessages, addMessage])

    // Update title based on current messages if in new chat flow
    useEffect(() => {
        if (!requestId && messages.length > 0) {
            const firstUserContent = messages.find(m => m.role === 'user')?.content
            if (firstUserContent) {
                const newTitle = firstUserContent.length > 50
                    ? firstUserContent.substring(0, 50) + '...'
                    : firstUserContent
                setTitle(newTitle)
            }
        }
    }, [messages, requestId])


    return (
        <main
            className="flex flex-col h-full w-full border-x bg-card/10"
            aria-label="Chat with Amber"
        >
            <div className="flex-1 flex flex-col min-h-0 bg-background/50 backdrop-blur-sm">
                <header className="p-4 border-b flex justify-between items-center bg-card">
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
        </main>
    )
}

