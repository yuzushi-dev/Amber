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

    // Use ref to always access current conversationId (avoids stale closure)
    const conversationIdRef = useRef<string | null>(null)

    const stopStream = useCallback(() => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close()
            eventSourceRef.current = null
        }
        setState((prev) => ({ ...prev, isStreaming: false }))
    }, [])

    // Reset conversation when starting a new chat
    const resetConversation = useCallback(() => {
        conversationIdRef.current = null
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
        // Use relative path for SSE to leverage Vite proxy / Nginx
        // This ensures it works on remote deployments (e.g. cph-01)
        const baseUrl = `/api/v1/query/stream`
        // We use window.location.origin to form a valid URL object if needed, 
        // but EventSource can take a relative path string directly usually. 
        // However, constructing URL object requires a base if path is relative. 
        // We can just use string concatenation for params to keep it simple and relative.
        const url = new URL(baseUrl, window.location.origin)

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
        // Use ref to avoid stale closure issue
        if (conversationIdRef.current) {
            url.searchParams.set('conversation_id', conversationIdRef.current)
        }

        const eventSource = new EventSource(url.toString())
        eventSourceRef.current = eventSource

        eventSource.addEventListener('thinking', (e) => {
            try {
                const text = JSON.parse(e.data)
                updateLastMessage({ thinking: text })
            } catch {
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
            } catch {
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
            } catch {
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

        eventSource.addEventListener('quality', (e) => {
            try {
                const quality = JSON.parse(e.data)
                updateLastMessage({ quality_score: quality })
            } catch (err) {
                console.error('Failed to parse quality score', err)
            }
        })

        eventSource.addEventListener('routing', (e) => {
            try {
                const routing = JSON.parse(e.data)
                updateLastMessage({ routing_info: routing })
            } catch (err) {
                console.error('Failed to parse routing info', err)
            }
        })

        // Listen for conversation_id from backend (for threading)
        eventSource.addEventListener('conversation_id', (e) => {
            try {
                const convId = JSON.parse(e.data)
                conversationIdRef.current = convId  // Update ref immediately
                setState((prev) => ({ ...prev, conversationId: convId }))
                console.log('Received conversation_id for threading:', convId)

                // Update the current assistant message with the session_id
                updateLastMessage({ session_id: convId })

                // Also retroactively update the user message if possible? 
                // Difficult because we only have updateLastMessage. 
                // But usually feedback is on the Assistant message, so this is enough.
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
    }, [addMessage, updateLastMessage, stopStream])

    const setConversationId = useCallback((id: string | null) => {
        conversationIdRef.current = id  // Sync ref
        setState((prev) => ({ ...prev, conversationId: id }))
    }, [])

    return { ...state, startStream, stopStream, resetConversation, setConversationId }
}
