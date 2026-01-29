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

        // Reset streaming stats for diagnostics
        streamStatsRef.current = {
            tokenCount: 0,
            messageCount: 0,
            charCount: 0,
            startedAt: performance.now(),
        }

        debugLog('Starting SSE', {
            path: url.pathname,
            hasApiKey: url.searchParams.has('api_key'),
            hasConversationId: url.searchParams.has('conversation_id'),
            agentMode: url.searchParams.get('agent_mode') === 'true',
            queryLength: finalQuery.length,
        })

        const eventSource = new EventSource(url.toString())
        eventSourceRef.current = eventSource

        eventSource.onopen = () => {
            debugLog('SSE connection opened')
        }

        eventSource.addEventListener('thinking', (e) => {
            try {
                const text = JSON.parse(e.data)
                updateLastMessage({ thinking: text })
            } catch {
                // Fallback for legacy/error messages
                updateLastMessage({ thinking: e.data })
            }
            debugLog('thinking event', e.data?.toString()?.slice(0, 60) || '')
        })

        eventSource.addEventListener('status', (e) => {
            debugLog('status event', e.data?.toString()?.slice(0, 80) || '')
        })

        eventSource.addEventListener('token', (e) => {
            try {
                const token = JSON.parse(e.data)
                const tokenText = typeof token === 'string' ? token : String(token)
                streamStatsRef.current.tokenCount += 1
                streamStatsRef.current.charCount += tokenText.length

                // Buffer tokens instead of updating state on each one
                tokenBufferRef.current += tokenText

                // Flush buffer every 50ms to allow browser to paint
                const now = performance.now()
                const timeSinceLastFlush = now - lastFlushTimeRef.current
                if (timeSinceLastFlush >= 50 || streamStatsRef.current.tokenCount === 1) {
                    flushTokenBuffer()
                }

                if (streamStatsRef.current.tokenCount === 1 || streamStatsRef.current.tokenCount % 20 === 0) {
                    const storeLen = useChatStore.getState().messages.slice(-1)[0]?.content?.length || 0
                    debugLog('store content length', storeLen)
                }
                const { tokenCount, charCount, startedAt } = streamStatsRef.current
                if (tokenCount === 1 || tokenCount % 20 === 0) {
                    debugLog('token event', {
                        tokenCount,
                        charCount,
                        msSinceStart: Math.round(performance.now() - startedAt),
                        preview: tokenText.slice(0, 20),
                    })
                }
            } catch {
                // Fallback
                streamStatsRef.current.tokenCount += 1
                streamStatsRef.current.charCount += e.data.length

                // Buffer tokens instead of updating state on each one
                tokenBufferRef.current += e.data

                // Flush buffer every 50ms to allow browser to paint
                const now = performance.now()
                const timeSinceLastFlush = now - lastFlushTimeRef.current
                if (timeSinceLastFlush >= 50 || streamStatsRef.current.tokenCount === 1) {
                    flushTokenBuffer()
                }

                if (streamStatsRef.current.tokenCount === 1 || streamStatsRef.current.tokenCount % 20 === 0) {
                    const storeLen = useChatStore.getState().messages.slice(-1)[0]?.content?.length || 0
                    debugLog('store content length', storeLen)
                }
                const { tokenCount, charCount, startedAt } = streamStatsRef.current
                if (tokenCount === 1 || tokenCount % 20 === 0) {
                    debugLog('token event (raw)', {
                        tokenCount,
                        charCount,
                        msSinceStart: Math.round(performance.now() - startedAt),
                        preview: e.data.toString().slice(0, 20),
                    })
                }
            }
        })

        // Handle 'message' event from Agent mode (complete answer at once)
        eventSource.addEventListener('message', (e) => {
            try {
                const fullMessage = JSON.parse(e.data)
                streamStatsRef.current.messageCount += 1
                updateLastMessage({
                    thinking: null,
                    content: fullMessage
                })
                debugLog('message event', {
                    messageCount: streamStatsRef.current.messageCount,
                    length: typeof fullMessage === 'string' ? fullMessage.length : 0,
                })
            } catch {
                // Fallback: use raw data
                streamStatsRef.current.messageCount += 1
                updateLastMessage({
                    thinking: null,
                    content: e.data
                })
                debugLog('message event (raw)', {
                    messageCount: streamStatsRef.current.messageCount,
                    length: e.data.length,
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
            debugLog('sources event', e.data?.toString()?.slice(0, 80) || '')
        })

        eventSource.addEventListener('quality', (e) => {
            try {
                const quality = JSON.parse(e.data)
                updateLastMessage({ quality_score: quality })
            } catch (err) {
                console.error('Failed to parse quality score', err)
            }
            debugLog('quality event', e.data?.toString()?.slice(0, 80) || '')
        })

        eventSource.addEventListener('routing', (e) => {
            try {
                const routing = JSON.parse(e.data)
                updateLastMessage({ routing_info: routing })
            } catch (err) {
                console.error('Failed to parse routing info', err)
            }
            debugLog('routing event', e.data?.toString()?.slice(0, 80) || '')
        })

        // Listen for conversation_id from backend (for threading)
        eventSource.addEventListener('conversation_id', (e) => {
            try {
                const convId = JSON.parse(e.data)
                conversationIdRef.current = convId  // Update ref immediately
                setState((prev) => ({ ...prev, conversationId: convId }))

                // Update the current assistant message with the session_id
                updateLastMessage({ session_id: convId })

                // Also retroactively update the user message if possible? 
                // Difficult because we only have updateLastMessage. 
                // But usually feedback is on the Assistant message, so this is enough.
            } catch (err) {
                console.error('Failed to parse conversation_id', err)
            }
            debugLog('conversation_id event', e.data?.toString() || '')
        })

        eventSource.addEventListener('done', () => {
            // Flush any remaining buffered tokens
            flushTokenBuffer()

            setState((prev) => ({ ...prev, isStreaming: false }))
            stopStream()
            useChatStore.getState().triggerHistoryUpdate()
            const { tokenCount, messageCount, charCount, startedAt } = streamStatsRef.current
            debugLog('done event', {
                tokenCount,
                messageCount,
                charCount,
                totalMs: Math.round(performance.now() - startedAt),
            })
        })

        eventSource.addEventListener('error', (e) => {
            console.error('SSE Error Event', e)

            let handled = false

            // Try to parse the error data if it's a MessageEvent
            if (e instanceof MessageEvent && e.data) {
                try {
                    const errorData = JSON.parse(e.data)
                    // Check for structured error
                    if (errorData && typeof errorData === 'object') {
                        const provider = errorData.provider || 'System'
                        let errorMsg = ''
                        let handledCode = true

                        switch (errorData.code) {
                            case 'rate_limit':
                                errorMsg = `[429 - ${provider}] The cognitive circuits are momentarily overwhelmed. Contact an administrator and stand by please.`
                                break
                            case 'quota_exceeded':
                                errorMsg = `[429 - ${provider}] Quota exceeded. Please check your billing details.`
                                break
                            case 'auth_error':
                                errorMsg = `[401 - ${provider}] I can’t verify you. Access stays locked.`
                                break
                            case 'context_length':
                                errorMsg = `[400 - ${provider}] That’s beyond my current buffer. Trim it down.`
                                break
                            case 'provider_error':
                                errorMsg = `[503 - ${provider}] Connection lost. I’ll be back when the line clears.`
                                break
                            case 'invalid_request':
                                errorMsg = `[400 - ${provider}] This request doesn’t compile. Fix the inputs.`
                                break
                            default:
                                // Fallback for handled but unknown codes? 
                                // Or treating generic errors with provider info
                                if (provider !== 'System') {
                                    errorMsg = `[Error - ${provider}] An unexpected provider error occurred.`
                                } else {
                                    handledCode = false
                                }
                        }

                        if (handledCode && errorMsg) {
                            updateLastMessage({
                                thinking: null,
                                content: errorMsg
                            })

                            setState((prev) => ({
                                ...prev,
                                isStreaming: false,
                            }))
                            stopStream()
                            handled = true
                        }
                    } else {
                        // It might be a simple string error from old backend
                        debugLog('error event data string', errorData)
                    }
                } catch (parseErr) {
                    // ignore parse error, treat as generic
                }
            }

            if (!handled) {
                // Default handling for connection errors or generic backend errors
                updateLastMessage({
                    thinking: null,
                    content: "[Connection Error] Stream connection failed. Please try again."
                })
                setState((prev) => ({
                    ...prev,
                    isStreaming: false,
                    // error: new Error('Stream connection failed'), // We handled it in UI
                }))
                stopStream()
                debugLog('error event (unhandled)', e)
            }
        })
    }, [addMessage, updateLastMessage, stopStream, flushTokenBuffer])

    const setConversationId = useCallback((id: string | null) => {
        conversationIdRef.current = id  // Sync ref
        setState((prev) => ({ ...prev, conversationId: id }))
    }, [])

    return { ...state, startStream, stopStream, resetConversation, setConversationId }
}
