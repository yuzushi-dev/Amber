import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
    apiKey: string | null
    isAuthenticated: boolean
    isValidating: boolean
    error: string | null

    // Actions
    setApiKey: (key: string) => Promise<boolean>
    clearApiKey: () => void
    validateKey: (key: string) => Promise<boolean>
}

export const useAuth = create<AuthState>()(
    persist(
        (set, get) => ({
            apiKey: null,
            isAuthenticated: false,
            isValidating: false,
            error: null,

            setApiKey: async (key: string) => {
                set({ isValidating: true, error: null })

                const isValid = await get().validateKey(key)

                if (isValid) {
                    set({
                        apiKey: key,
                        isAuthenticated: true,
                        isValidating: false,
                        error: null
                    })
                    // Also store in localStorage for axios interceptor
                    localStorage.setItem('api_key', key)
                    return true
                } else {
                    set({
                        isValidating: false,
                        error: 'Invalid API key'
                    })
                    return false
                }
            },

            clearApiKey: () => {
                localStorage.removeItem('api_key')
                set({
                    apiKey: null,
                    isAuthenticated: false,
                    error: null
                })
            },

            validateKey: async (key: string): Promise<boolean> => {
                try {
                    // Try to access a protected endpoint with this key
                    const response = await fetch('/v1/documents', {
                        method: 'GET',
                        headers: {
                            'X-API-Key': key,
                            'Content-Type': 'application/json'
                        }
                    })
                    return response.ok
                } catch {
                    return false
                }
            }
        }),
        {
            name: 'auth-storage',
            partialize: (state) => ({
                apiKey: state.apiKey,
                isAuthenticated: state.isAuthenticated
            }),
        }
    )
)

// Helper to mask API key for display
export function maskApiKey(key: string): string {
    if (!key || key.length < 10) return '****'

    if (key.includes('-')) {
        const parts = key.split('-')
        if (parts.length >= 3) {
            return `${parts[0]}-***-***-${parts[parts.length - 1]}`
        }
    }

    return `${key.slice(0, 4)}...${key.slice(-4)}`
}
