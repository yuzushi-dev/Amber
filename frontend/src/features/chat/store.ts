import { create } from 'zustand'

export interface Message {
    id: string
    role: 'user' | 'assistant'
    content: string
    thinking?: string | null
    sources?: Source[]
    timestamp: string

    // Feedback & Metadata
    session_id?: string
    message_id?: string // Legacy or duplicate of id
    request_id?: string
    quality_score?: QualityScore
    routing_info?: RoutingInfo
}

export interface QualityScore {
    total: number
    retrieval: number
    generation: number
}

export interface RoutingInfo {
    categories: string[]
    confidence: number
}

export interface Source {
    chunk_id: string
    index?: number
    document_id?: string
    title: string
    content_preview: string
    text?: string
    score?: number
    page?: number
}

interface ChatState {
    messages: Message[]
    isStreaming: boolean
    addMessage: (message: Message) => void
    updateLastMessage: (update: Partial<Message>) => void
    clearMessages: () => void

    // History Refresh Trigger
    lastHistoryUpdate: number
    triggerHistoryUpdate: () => void
}

export const useChatStore = create<ChatState>((set) => ({
    messages: [],
    isStreaming: false,
    addMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
    updateLastMessage: (update) => set((state) => {
        const lastMessage = state.messages[state.messages.length - 1]
        if (!lastMessage || lastMessage.role !== 'assistant') return state
        const newMessages = [...state.messages]
        newMessages[newMessages.length - 1] = { ...lastMessage, ...update }
        return { messages: newMessages }
    }),
    clearMessages: () => set({ messages: [] }),

    lastHistoryUpdate: 0,
    triggerHistoryUpdate: () => set({ lastHistoryUpdate: Date.now() }),
}))
