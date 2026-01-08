import { useState, useCallback, useRef } from 'react'
import { useChatStore, Source } from '../store'
import { v4 as uuidv4 } from 'uuid'

interface StreamState {
    isStreaming: boolean
    error: Error | null
}

export function useChatStream() {
    const [state, setState] = useState<StreamState>({
        isStreaming: false,
        error: null,
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

        setState({
            isStreaming: true,
            error: null,
        })

        const apiKey = localStorage.getItem('api_key')
        // Build URL for proxy (configured in vite.config.ts)
        const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000/v1'
        const url = new URL(`${apiBaseUrl}/query/stream`)
        url.searchParams.set('query', query)
        url.searchParams.set('api_key', apiKey || '')

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

        eventSource.addEventListener('sources', (e) => {
            try {
                const sources: Source[] = JSON.parse(e.data)
                updateLastMessage({ sources })
            } catch (err) {
                console.error('Failed to parse sources', err)
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

    return { ...state, startStream, stopStream }
}
