
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useChatStream } from '@/features/chat/hooks/useChatStream'
import { useChatStore } from '@/features/chat/store'

vi.mock('@/features/chat/store', () => ({
    useChatStore: vi.fn(() => ({
        messages: [],
        addMessage: vi.fn(),
        updateLastMessage: vi.fn(),
    })),
}))

// Mock setState inside hook? No, renderHook handles it.
// We need to mock EventSource properly including readyState

describe('useChatStream Error Handling', () => {
    let mockEventSource: any
    let mockUpdateLastMessage: any
    let mockAddMessage: any

    beforeEach(() => {
        vi.clearAllMocks()
        mockEventSource = {
            addEventListener: vi.fn(),
            close: vi.fn(),
            readyState: 0, // CONNECTING
        }

        // Mock the store implementation to capture calls
        mockUpdateLastMessage = vi.fn()
        mockAddMessage = vi.fn();

        (useChatStore as any).mockImplementation(() => ({
            addMessage: mockAddMessage,
            updateLastMessage: mockUpdateLastMessage,
            messages: [{ role: 'assistant', content: '', thinking: 'Analyzing query...' }] // Simulate existing state
        }))
            // Fix mock implementation return value structure
            ; (useChatStore as any).getState = () => ({
                messages: [{ role: 'assistant', content: '', thinking: 'Analyzing query...' }]
            })

        vi.stubGlobal('EventSource', vi.fn().mockImplementation(function () {
            return mockEventSource
        }))
        // Helper to simulate EventSource constant
        vi.stubGlobal('EventSource', Object.assign(vi.fn(), {
            CONNECTING: 0,
            OPEN: 1,
            CLOSED: 2
        }))
        // Actually the stub above might overwrite the constructor if not careful.
        // Better:
        const ES = vi.fn(function () { return mockEventSource })
        Object.assign(ES, { CONNECTING: 0, OPEN: 1, CLOSED: 2 })
        vi.stubGlobal('EventSource', ES)
    })

    it('should handle unexpected connection closure (500/Network Error)', async () => {
        const { result } = renderHook(() => useChatStream())

        // 1. Start Stream
        await act(async () => {
            // @ts-ignore
            await result.current.startStream('test query')
        })

        expect(result.current.isStreaming).toBe(true)
        expect(mockEventSource.addEventListener).toHaveBeenCalledWith('error', expect.any(Function))

        // Get the error handler
        const calls = mockEventSource.addEventListener.mock.calls
        const errorHandler = calls.find((c: any) => c[0] === 'error')?.[1]
        expect(errorHandler).toBeDefined()

        // 2. Simulate Connection Error with CLOSED state
        mockEventSource.readyState = 2 // CLOSED

        await act(async () => {
            errorHandler(new Event('error'))
        })

        // 3. Assertions
        // It SHOULD stop streaming
        expect(result.current.isStreaming).toBe(false)

        // It SHOULD update the message to show error and clear thinking
        expect(mockUpdateLastMessage).toHaveBeenCalledWith(expect.objectContaining({
            thinking: null,
            content: expect.stringContaining("Connection Error")
        }))
    })

    it('should handle structured processing_error', async () => {
        const { result } = renderHook(() => useChatStream())

        await act(async () => {
            // @ts-ignore
            await result.current.startStream('test query')
        })

        const calls = mockEventSource.addEventListener.mock.calls
        const processingErrorHandler = calls.find((c: any) => c[0] === 'processing_error')?.[1]

        const errorPayload = JSON.stringify({
            code: 'quota_exceeded',
            message: 'Quota exceeded. Pay up.',
            provider: 'OpenAI'
        })

        await act(async () => {
            processingErrorHandler({
                data: errorPayload,
                type: 'processing_error'
            } as MessageEvent)
        })

        expect(mockUpdateLastMessage).toHaveBeenCalledWith(expect.objectContaining({
            thinking: null,
            content: expect.stringContaining("Quota exceeded")
        }))
        expect(result.current.isStreaming).toBe(false)
    })
})
