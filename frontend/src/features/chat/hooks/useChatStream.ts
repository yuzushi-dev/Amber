import { useState, useCallback, useRef } from 'react'
import { useChatStore, Source } from '../store'
import { v4 as uuidv4 } from 'uuid'

interface StreamState {
    isStreaming: boolean
    error: Error | null
    conversationId: string | null  // Track conversation for threading
}

export function useChatStream() {
    const [state, setState] = useState<StreamState>({
        isStreaming: false,
        error: null,
        conversationId: null,
    })

    const { addMessage, updateLastMessage } = useChatStore()
    const eventSourceRef = useRef<EventSource | null>(null)

    const stopStream = useCallback(() => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close()
            eventSourceRef.current = null
        }
        setState((prev) => ({ ...prev, isStreaming: false }))
    }, [])

    // Reset conversation when starting a new chat
    const resetConversation = useCallback(() => {
        setState((prev) => ({ ...prev, conversationId: null }))
    }, [])

    const startStream = useCallback(async (query: string) => {
        // Cleanup previous stream
        stopStream()

        // Add user message
        addMessage({
            id: uuidv4(),
            role: 'user',
            content: query,
            timestamp: new Date().toISOString(),
        })

        // Add initial assistant message for streaming
        addMessage({
            id: uuidv4(),
            role: 'assistant',
            content: '',
            thinking: 'Analyzing query...',
            timestamp: new Date().toISOString(),
        })

        setState((prev) => ({
            ...prev,
            isStreaming: true,
            error: null,
        }))

        const apiKey = localStorage.getItem('api_key')
        // Build URL for proxy (configured in vite.config.ts)
        const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000/v1'
        const url = new URL(`${apiBaseUrl}/query/stream`)

        // Trigger Logic: Check for @agent or /agent
        let finalQuery = query
        let isAgentMode = false

        if (query.startsWith('@agent') || query.startsWith('/agent') || query.startsWith('/carbonio')) {
            isAgentMode = true
            // Remove trigger from query sent to backend
            finalQuery = query.replace(/^(@agent|\/agent|\/carbonio)\s*/, '')
        }

        url.searchParams.set('query', finalQuery)
        url.searchParams.set('api_key', apiKey || '')

        if (isAgentMode) {
            url.searchParams.set('agent_mode', 'true')
        }

        // Pass conversation_id for threading (if we have one from previous messages)
        if (state.conversationId) {
            url.searchParams.set('conversation_id', state.conversationId)
        }

        const eventSource = new EventSource(url.toString())
        eventSourceRef.current = eventSource

        eventSource.addEventListener('thinking', (e) => {
            try {
                const text = JSON.parse(e.data)
                updateLastMessage({ thinking: text })
            } catch (err) {
                // Fallback for legacy/error messages
                updateLastMessage({ thinking: e.data })
            }
        })

        eventSource.addEventListener('token', (e) => {
            try {
                const token = JSON.parse(e.data)
                updateLastMessage({
                    thinking: null,
                    content: (useChatStore.getState().messages.slice(-1)[0]?.content || '') + token
                })
            } catch (err) {
                // Fallback
                updateLastMessage({
                    thinking: null,
                    content: (useChatStore.getState().messages.slice(-1)[0]?.content || '') + e.data
                })
            }
        })

        // Handle 'message' event from Agent mode (complete answer at once)
        eventSource.addEventListener('message', (e) => {
            try {
                const fullMessage = JSON.parse(e.data)
                updateLastMessage({
                    thinking: null,
                    content: fullMessage
                })
            } catch (err) {
                // Fallback: use raw data
                updateLastMessage({
                    thinking: null,
                    content: e.data
                })
            }
        })

        eventSource.addEventListener('sources', (e) => {
            try {
                const sources: Source[] = JSON.parse(e.data)
                updateLastMessage({ sources })
            } catch (err) {
                console.error('Failed to parse sources', err)
            }
        })

        // Listen for conversation_id from backend (for threading)
        eventSource.addEventListener('conversation_id', (e) => {
            try {
                const convId = JSON.parse(e.data)
                setState((prev) => ({ ...prev, conversationId: convId }))
                console.log('Received conversation_id for threading:', convId)
            } catch (err) {
                console.error('Failed to parse conversation_id', err)
            }
        })

        eventSource.addEventListener('done', () => {
            setState((prev) => ({ ...prev, isStreaming: false }))
            stopStream()
            useChatStore.getState().triggerHistoryUpdate()
        })

        eventSource.addEventListener('error', (e) => {
            console.error('SSE Error', e)
            setState((prev) => ({
                ...prev,
                isStreaming: false,
                error: new Error('Stream connection failed'),
            }))
            stopStream()
        })
    }, [addMessage, updateLastMessage, stopStream, state.conversationId])

    const setConversationId = useCallback((id: string | null) => {
        setState((prev) => ({ ...prev, conversationId: id }))
    }, [])

    return { ...state, startStream, stopStream, resetConversation, setConversationId }
}
