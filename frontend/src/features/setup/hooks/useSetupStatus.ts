import { useQuery } from '@tanstack/react-query'

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
    return useQuery<SetupStatus>({
        queryKey: ['setup-status'],
        queryFn: async () => {
            const apiKey = localStorage.getItem('api_key')
            const response = await fetch('/api/setup/status', {
                headers: {
                    'X-API-Key': apiKey || '',
                    'Content-Type': 'application/json'
                }
            })
            if (!response.ok) {
                throw new Error('Failed to fetch setup status')
            }
            return response.json()
        },
        enabled: !!localStorage.getItem('api_key'),
        // Don't refetch automatically - we'll handle this manually
        staleTime: Infinity,
        retry: false
    })
}

export type { SetupStatus }
