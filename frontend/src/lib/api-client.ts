import axios from 'axios'
import { toast } from 'sonner'

// IMPORTANT: Always use relative /api/v1 path for browser requests.
// The Vite dev server proxies /api/* to the backend container.
// Never use absolute URLs like http://api:8000 as 'api' is an internal Docker hostname.
const baseURL = '/api/v1'


export const apiClient = axios.create({
    baseURL,
    headers: {
        'Content-Type': 'application/json',
    },
})

// Add auth interceptor
apiClient.interceptors.request.use((config) => {
    const token = localStorage.getItem('api_key')
    if (token) {
        config.headers['X-API-Key'] = token
    }
    return config
})


// Add error interceptor
apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            // Handle auth error - e.g. redirect to login or show modal
            console.error('Unauthorized access - potential API key issue')
        }

        // Detect OpenAI quota errors (429)
        if (error.response?.status === 429) {
            const message = error.response?.data?.detail || error.response?.data?.message || ''
            if (message.toLowerCase().includes('quota') || message.toLowerCase().includes('rate limit')) {
                toast.error('OpenAI Quota Exceeded', {
                    description: 'Please check your billing at platform.openai.com',
                    duration: 10000,
                })
            } else {
                toast.warning('Rate Limited', {
                    description: 'Too many requests. Please wait a moment.',
                    duration: 5000,
                })
            }
        }

        return Promise.reject(error)
    }
)

export interface Folder {
    id: string
    name: string
    tenant_id: string
    created_at: string
}

export const folderApi = {
    list: async () => {
        const response = await apiClient.get<Folder[]>('/folders')
        return response.data
    },
    create: async (name: string) => {
        const response = await apiClient.post<Folder>('/folders', { name })
        return response.data
    },
    delete: async (id: string) => {
        await apiClient.delete(`/folders/${id}`)
    },
    updateDocumentFolder: async (documentId: string, folderId: string | null) => {
        // null or empty string to unfile
        const payload = { folder_id: folderId === null ? "" : folderId }
        await apiClient.patch(`/documents/${documentId}`, payload)
    }
}

import { HealRequest, HealingSuggestion, MergeRequest, EdgeRequest } from '@/types/graph';

export const graphEditorApi = {
    heal: async (request: HealRequest) => {
        const response = await apiClient.post<HealingSuggestion[]>('/graph/editor/heal', request);
        return response.data;
    },
    merge: async (request: MergeRequest) => {
        const response = await apiClient.post('/graph/editor/nodes/merge', request);
        return response.data;
    },
    createEdge: async (request: EdgeRequest) => {
        const response = await apiClient.post('/graph/editor/edge', request);
        return response.data;
    },
    deleteEdge: async (request: EdgeRequest) => {
        // DELETE with body requires 'data' field in config
        const response = await apiClient.delete('/graph/editor/edge', { data: request });
        return response.data;
    },
    deleteNode: async (nodeId: string) => {
        const response = await apiClient.delete(`/graph/editor/node/${nodeId}`);
        return response.data;
    }
}

