import { useQuery } from '@tanstack/react-query'
import { useAuth, type AuthState } from '@/features/auth'

interface SetupStatus {
    initialized: boolean
    setup_complete: boolean
    features: Array<{
        id: string
        name: string
        description: string
        size_mb: number
        status: 'not_installed' | 'installing' | 'installed' | 'failed'
    }>
    summary: {
        total: number
        installed: number
        installing: number
        not_installed: number
    }
}

export function useSetupStatus() {
    const apiKey = useAuth((state: AuthState) => state.apiKey)

    return useQuery<SetupStatus>({
        queryKey: ['setup-status'],
        queryFn: async () => {
            const response = await fetch('/api/v1/setup/status', {
                headers: {
                    'X-API-Key': apiKey || '',
                    'Content-Type': 'application/json'
                }
            })
            if (!response.ok) {
                // Return null or throw - if throw, useQuery goes to error state
                if (response.status === 401) {
                    // We could listen to this in App to logout, 
                    // or just throw and let the UI handle it
                    throw new Error('Unauthorized')
                }
                throw new Error('Failed to fetch setup status')
            }
            return response.json()
        },
        enabled: !!apiKey,
        // Don't refetch automatically - we'll handle this manually
        staleTime: Infinity,
        retry: (_failureCount: number, error: Error) => {
            if (error.message === 'Unauthorized') return false
            return true
        },
        retryDelay: 2000
    })
}

export type { SetupStatus }
