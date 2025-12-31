import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useChatStream } from '@/features/chat/hooks/useChatStream'
import { useChatStore } from '@/features/chat/store'

// Mock the store
vi.mock('@/features/chat/store', () => ({
    useChatStore: vi.fn(() => ({
        messages: [],
        addMessage: vi.fn(),
        updateLastMessage: vi.fn(),
    })),
}))

describe('useChatStream', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('should initialize with default state', () => {
        const { result } = renderHook(() => useChatStream())

        expect(result.current.isStreaming).toBe(false)
        expect(result.current.error).toBeNull()
    })

    it('should set isStreaming to true when stream starts', async () => {
        const mockEventSource = {
            addEventListener: vi.fn(),
            close: vi.fn(),
        }
        vi.stubGlobal('EventSource', vi.fn().mockImplementation(function () {
            return mockEventSource
        }))

        const { result } = renderHook(() => useChatStream())

        act(() => {
            result.current.startStream('test query')
        })

        expect(result.current.isStreaming).toBe(true)
    })
})
