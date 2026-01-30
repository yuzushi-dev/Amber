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
    const abortControllerRef = useRef<AbortController | null>(null)
    const debugEnabledRef = useRef(
        localStorage.getItem('chat_debug') === 'true'
    )
    const streamStatsRef = useRef({
        tokenCount: 0,
        messageCount: 0,
        charCount: 0,
        startedAt: 0,
    })

    // Token buffering for smoother streaming (prevents paint starvation)
    const tokenBufferRef = useRef<string>('')
    const lastFlushTimeRef = useRef<number>(0)

    // Use ref to always access current conversationId (avoids stale closure)
    const conversationIdRef = useRef<string | null>(null)
    const debugLog = (...args: unknown[]) => {
        if (debugEnabledRef.current) {
            console.log('[ChatStream]', ...args)
        }
    }

    // Flush accumulated tokens to state
    const flushTokenBuffer = useCallback(() => {
        if (tokenBufferRef.current.length > 0) {
            const bufferedContent = tokenBufferRef.current
            tokenBufferRef.current = ''
            lastFlushTimeRef.current = performance.now()

            updateLastMessage({
                thinking: null,
                content: (useChatStore.getState().messages.slice(-1)[0]?.content || '') + bufferedContent
            })
        }
    }, [updateLastMessage])

    const stopStream = useCallback(() => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort()
            abortControllerRef.current = null
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

        // Create new AbortController
        const abortController = new AbortController()
        abortControllerRef.current = abortController

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

        // Trigger Logic: Check for @agent or /agent
        let finalQuery = query
        let isAgentMode = false

        if (query.startsWith('@agent') || query.startsWith('/agent') || query.startsWith('/carbonio')) {
            isAgentMode = true
            // Remove trigger from query sent to backend
            finalQuery = query.replace(/^(@agent|\/agent|\/carbonio)\s*/, '')
        }

        const apiKey = localStorage.getItem('api_key')

        // Use relative path for SSE to leverage Vite proxy / Nginx
        const url = new URL('/api/v1/query/stream', window.location.origin)
        url.searchParams.set('api_key', apiKey || '')

        // Reset streaming stats for diagnostics
        streamStatsRef.current = {
            tokenCount: 0,
            messageCount: 0,
            charCount: 0,
            startedAt: performance.now(),
        }

        debugLog('Starting POST Stream', {
            url: url.toString(),
            agentMode: isAgentMode,
            queryLength: finalQuery.length,
            conversationId: conversationIdRef.current
        })

        try {
            const response = await fetch(url.toString(), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    query: finalQuery,
                    conversation_id: conversationIdRef.current,
                    options: {
                        agent_mode: isAgentMode,
                        model: localStorage.getItem('selected_model'),
                        stream: true
                    }
                }),
                signal: abortController.signal
            })

            if (!response.ok) {
                // Try to read error body
                const errorText = await response.text().catch(() => response.statusText)
                throw new Error(`Server returned ${response.status}: ${errorText}`)
            }

            if (!response.body) {
                throw new Error('ReadableStream not supported in this browser.')
            }

            const reader = response.body.getReader()
            const decoder = new TextDecoder()
            let buffer = ''

            debugLog('Connection established, reading stream...')

            while (true) {
                const { done, value } = await reader.read()

                if (done) {
                    debugLog('Stream complete')
                    break
                }

                const chunk = decoder.decode(value, { stream: true })
                buffer += chunk

                // Process buffer line by line, looking for SSE double-newline
                const parts = buffer.split('\n\n')
                buffer = parts.pop() || '' // Keep incomplete part

                for (const part of parts) {
                    if (!part.trim()) continue

                    // Parse event: ... data: ...
                    // There might be multiple lines like "event: token\ndata: hello"
                    const lines = part.split('\n')
                    let eventType = 'message'
                    let data = ''

                    for (const line of lines) {
                        if (line.startsWith('event: ')) {
                            eventType = line.slice(7).trim()
                        } else if (line.startsWith('data: ')) {
                            data = line.slice(6)
                        }
                    }

                    if (eventType && data) {
                        handleEvent(eventType, data)
                    }
                }
            }

            // Flush any remaining
            if (buffer.trim()) {
                // Handle remaining buffer similar to loop
                // (Usually valid SSE ends with \n\n so buffer should be empty)
            }

            // End of stream
            handleEvent('done', '')

        } catch (err: any) {
            if (err.name === 'AbortError') {
                debugLog('Stream aborted by user')
                return
            }
            console.error('Stream Fetch Error', err)
            updateLastMessage({
                thinking: null,
                content: `[Connection Error] Stream failed: ${err.message}`
            })
            setState((prev) => ({
                ...prev,
                isStreaming: false,
                error: err
            }))
        }
    }, [])

    const handleEvent = useCallback((type: string, data: string) => {
        // Helper to parse JSON safely
        const parseJSON = (str: string) => {
            try { return JSON.parse(str) } catch { return str }
        }

        switch (type) {
            case 'token':
                const token = parseJSON(data)
                const tokenText = typeof token === 'string' ? token : String(token)

                // Stats
                streamStatsRef.current.tokenCount += 1
                streamStatsRef.current.charCount += tokenText.length

                // Buffer
                tokenBufferRef.current += tokenText

                // Flush logic
                const now = performance.now()
                if ((now - lastFlushTimeRef.current >= 50) || streamStatsRef.current.tokenCount === 1) {
                    flushTokenBuffer()
                }
                break

            case 'thinking':
                updateLastMessage({ thinking: parseJSON(data) })
                break

            case 'status':
                // Optional log
                break

            case 'sources':
                updateLastMessage({ sources: parseJSON(data) })
                break

            case 'conversation_id':
                const cid = parseJSON(data)
                conversationIdRef.current = cid
                setState(p => ({ ...p, conversationId: cid }))
                updateLastMessage({ session_id: cid })
                break

            case 'done':
                flushTokenBuffer()
                setState(p => ({ ...p, isStreaming: false }))
                useChatStore.getState().triggerHistoryUpdate()

                // Clear abort controller since we are done
                if (abortControllerRef.current) {
                    abortControllerRef.current = null
                }
                break

            case 'processing_error':
                const errData = parseJSON(data)
                updateLastMessage({
                    thinking: null,
                    content: typeof errData === 'object' ? `[Error] ${errData.message || 'Unknown'}` : `[Error] ${errData}`
                })
                setState(p => ({ ...p, isStreaming: false }))
                if (abortControllerRef.current) abortControllerRef.current.abort()
                break

            case 'error':
                // Generic error
                updateLastMessage({
                    thinking: null,
                    content: "[Error] Stream error occurred."
                })
                setState(p => ({ ...p, isStreaming: false }))
                break
        }
    }, [updateLastMessage, flushTokenBuffer])

    const setConversationId = useCallback((id: string | null) => {
        conversationIdRef.current = id  // Sync ref
        setState((prev) => ({ ...prev, conversationId: id }))
    }, [])

    return { ...state, startStream, stopStream, resetConversation, setConversationId }
}
