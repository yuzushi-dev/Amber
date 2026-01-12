import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
    apiKey: string | null
    isAuthenticated: boolean
    isValidating: boolean
    permissions: string[]
    isSuperAdmin: boolean
    error: string | null

    // Actions
    setApiKey: (key: string) => Promise<boolean>
    clearApiKey: () => void
    validateKey: (key: string) => Promise<boolean>
    initialFetch: () => Promise<void>
}

export const useAuth = create<AuthState>()(
    persist(
        (set, get) => ({
            apiKey: null,
            isAuthenticated: false,
            isValidating: false,
            permissions: [],
            isSuperAdmin: false,
            error: null,

            setApiKey: async (key: string) => {
                set({ isValidating: true, error: null })

                const isValid = await get().validateKey(key)

                if (isValid) {
                    // Fetch permissions
                    try {
                        const { keysApi } = await import('@/lib/api-admin')
                        // We need to set the key in localStorage FIRST so the API client uses it
                        localStorage.setItem('api_key', key)

                        const info = await keysApi.me()
                        const isSuper = info.scopes.includes('super_admin')

                        set({
                            apiKey: key,
                            isAuthenticated: true,
                            isValidating: false,
                            permissions: info.scopes,
                            isSuperAdmin: isSuper,
                            error: null
                        })
                        return true
                    } catch (err) {
                        console.error("Failed to fetch permissions", err)
                        // Fallback: key is valid but couldn't get scopes (shouldn't happen)
                        set({
                            apiKey: key,
                            isAuthenticated: true,
                            isValidating: false,
                            error: null
                        })
                        return true
                    }
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
                    permissions: [],
                    isSuperAdmin: false,
                    error: null
                })
            },

            validateKey: async (key: string): Promise<boolean> => {
                try {
                    // Use a simple endpoint to check validity
                    const response = await fetch('/api/health')
                    if (!response.ok) return false

                    // Try to access whoami to verify key
                    const keysResponse = await fetch('/api/v1/admin/keys/me', {
                        headers: { 'X-API-Key': key }
                    })
                    return keysResponse.ok
                } catch {
                    return false
                }
            },

            initialFetch: async () => {
                const key = get().apiKey
                if (!key) return

                try {
                    const { keysApi } = await import('@/lib/api-admin')
                    const info = await keysApi.me()
                    set({
                        permissions: info.scopes,
                        isSuperAdmin: info.scopes.includes('super_admin')
                    })
                } catch (err) {
                    console.error("Initial fetch failed", err)
                    // If me() fails, key might be revoked, but we keep the session for now
                    // clearApiKey() if we want to be strict
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
