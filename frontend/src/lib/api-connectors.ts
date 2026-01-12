import { apiClient as api } from './api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'

export interface ConnectorStatus {
    connector_type: string
    status: 'idle' | 'syncing' | 'error'
    is_authenticated: boolean
    last_sync_at: string | null
    items_synced: number
    error_message: string | null
}

export interface ConnectorItem {
    id: string
    title: string
    url: string
    updated_at: string
    content_type: string
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- metadata values can be rendered as ReactNode
    metadata: Record<string, any>
}

export interface ConnectorItemsResponse {
    items: ConnectorItem[]
    has_more: boolean
    page: number
    total_count?: number
}

export interface SyncJobResponse {
    job_id: string
    status: string
    message: string
}

export const connectorsApi = {
    list: async (): Promise<string[]> => {
        const response = await api.get('/connectors/')
        return response.data.data
    },

    getStatus: async (type: string): Promise<ConnectorStatus> => {
        const response = await api.get(`/connectors/${type}/status`)
        return response.data.data
    },

    authenticate: async (type: string, credentials: Record<string, unknown>): Promise<ConnectorStatus> => {
        const response = await api.post(`/connectors/${type}/auth`, { credentials })
        return response.data.data
    },

    sync: async (type: string, fullSync = false): Promise<SyncJobResponse> => {
        const response = await api.post(`/connectors/${type}/sync`, { full_sync: fullSync })
        return response.data.data
    },

    listItems: async (type: string, page = 1, pageSize = 20, search?: string): Promise<ConnectorItemsResponse> => {
        const response = await api.get(`/connectors/${type}/items`, {
            params: { page, page_size: pageSize, search }
        })
        return response.data.data
    },

    ingestItems: async (type: string, itemIds: string[]): Promise<SyncJobResponse> => {
        const response = await api.post(`/connectors/${type}/ingest`, { item_ids: itemIds })
        return response.data.data
    }
}

export const useConnectors = () => {
    const queryClient = useQueryClient()

    const authenticate = useMutation({
        mutationFn: ({ type, credentials }: { type: string; credentials: Record<string, unknown> }) =>
            connectorsApi.authenticate(type, credentials),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['connector-status', variables.type] })
        }
    })

    return {
        authenticate
    }
}
