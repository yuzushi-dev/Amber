import { create } from 'zustand'

export interface Message {
    id: string
    role: 'user' | 'assistant'
    content: string
    thinking?: string | null
    sources?: Source[]
    timestamp: string
}

export interface Source {
    id: string
    title: string
    snippet: string
    score?: number
    page?: number
}

interface ChatState {
    messages: Message[]
    isStreaming: boolean
    addMessage: (message: Message) => void
    updateLastMessage: (update: Partial<Message>) => void
    clearMessages: () => void
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
}))
