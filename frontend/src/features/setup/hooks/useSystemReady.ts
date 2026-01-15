import { useQuery } from '@tanstack/react-query'

interface DependencyStatus {
    status: string
    latency_ms?: number
    error?: string
}

interface ReadinessResponse {
    status: string
    timestamp: string
    dependencies: Record<string, DependencyStatus>
}

export function useSystemReady() {
    return useQuery<ReadinessResponse>({
        queryKey: ['system-ready'],
        queryFn: async () => {
            // silent=true prevents 503 error logs in browser console
            const response = await fetch('/api/v1/health/ready?silent=true')
            if (!response.ok) {
                throw new Error('System not ready')
            }
            return response.json()
        },
        // Poll every 1s until ready
        refetchInterval: (query) => {
            const data = query.state.data
            return data?.status === 'ready' ? false : 1000
        },
        retry: true,
        retryDelay: 1000,
        staleTime: 5000,
    })
}
