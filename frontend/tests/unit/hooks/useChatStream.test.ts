
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useChatStream } from '@/features/chat/hooks/useChatStream'
import { useChatStore } from '@/features/chat/store'

vi.mock('@/features/chat/store', () => ({
    useChatStore: vi.fn(),
}))

type ChatStoreState = {
    messages: Array<{ role: string; content: string; thinking?: string }>
    triggerHistoryUpdate: ReturnType<typeof vi.fn>
}

type UseChatStoreMock = {
    mockImplementation: (impl: () => unknown) => void
    getState: () => ChatStoreState
}

describe('useChatStream Error Handling', () => {
    let mockUpdateLastMessage: ReturnType<typeof vi.fn>
    let mockAddMessage: ReturnType<typeof vi.fn>
    let mockTriggerHistoryUpdate: ReturnType<typeof vi.fn>
    let mockedUseChatStore: UseChatStoreMock

    const createStreamingResponse = (chunks: string[]) => {
        const encoded = chunks.map((chunk) => new TextEncoder().encode(chunk))
        let index = 0

        const reader = {
            read: vi.fn(async () => {
                if (index >= encoded.length) {
                    return { done: true, value: undefined as Uint8Array | undefined }
                }
                const value = encoded[index]
                index += 1
                return { done: false, value }
            }),
        }

        return {
            ok: true,
            body: {
                getReader: () => reader,
            },
            text: vi.fn(async () => ''),
        }
    }

    beforeEach(() => {
        vi.clearAllMocks()
        vi.spyOn(console, 'log').mockImplementation(() => {})
        vi.spyOn(console, 'error').mockImplementation(() => {})

        mockUpdateLastMessage = vi.fn()
        mockAddMessage = vi.fn()
        mockTriggerHistoryUpdate = vi.fn()

        const state: ChatStoreState = {
            messages: [{ role: 'assistant', content: '', thinking: 'Analyzing query...' }],
            triggerHistoryUpdate: mockTriggerHistoryUpdate,
        }

        mockedUseChatStore = useChatStore as unknown as UseChatStoreMock
        mockedUseChatStore.mockImplementation(() => ({
            addMessage: mockAddMessage,
            updateLastMessage: mockUpdateLastMessage,
            messages: state.messages,
        }))
        mockedUseChatStore.getState = () => state
    })

    afterEach(() => {
        vi.unstubAllGlobals()
        vi.restoreAllMocks()
    })

    it('should handle unexpected connection closure (500/Network Error)', async () => {
        const fetchMock = vi.fn().mockRejectedValue(new Error('network down'))
        vi.stubGlobal('fetch', fetchMock)

        const { result } = renderHook(() => useChatStream())

        await act(async () => {
            await result.current.startStream('test query')
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(result.current.isStreaming).toBe(false)
        expect(mockUpdateLastMessage).toHaveBeenCalledWith(expect.objectContaining({
            thinking: null,
            content: expect.stringContaining('[Connection Error]'),
        }))
    })

    it('should handle structured processing_error', async () => {
        const errorPayload = JSON.stringify({
            code: 'quota_exceeded',
            message: 'Quota exceeded. Pay up.',
            provider: 'OpenAI',
        })

        const fetchMock = vi.fn().mockResolvedValue(
            createStreamingResponse([
                `event: processing_error\ndata: ${errorPayload}\n\n`,
            ])
        )
        vi.stubGlobal('fetch', fetchMock)

        const { result } = renderHook(() => useChatStream())

        await act(async () => {
            await result.current.startStream('test query')
        })

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(mockUpdateLastMessage).toHaveBeenCalledWith(expect.objectContaining({
            thinking: null,
            content: expect.stringContaining('Quota exceeded. Pay up.'),
        }))
        expect(result.current.isStreaming).toBe(false)
    })
})
