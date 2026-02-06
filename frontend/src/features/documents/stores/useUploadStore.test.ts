
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from '@testing-library/react'

vi.mock('@/lib/api-client', () => ({
    apiClient: {
        post: vi.fn(() => Promise.resolve({ data: {} })),
        get: vi.fn(() => Promise.resolve({ data: {} }))
    }
}))
// Auto-mock these
vi.mock('idb-keyval')
vi.mock('uuid')
vi.mock('@/lib/sse')
vi.mock('@/components/ui/animated-progress', () => ({})) // Ignore UI imports


// Import Store
import { useUploadStore } from './useUploadStore'
import { apiClient } from '@/lib/api-client'
import * as idb from 'idb-keyval'

describe('useUploadStore', () => {
    beforeEach(() => {
        useUploadStore.setState({ items: [], isOpen: false })
        vi.clearAllMocks()
        localStorage.clear()

        // Mock IDB get to return a file by default
        vi.mocked(idb.get).mockResolvedValue(new File(['test'], 'test.pdf', { type: 'application/pdf' }))

        // Mock Notification
        global.Notification = {
            permission: 'default',
            requestPermission: vi.fn()
        } as unknown as typeof Notification
    })

    it('enqueues files correctly', async () => {
        const file = new File(['content'], 'test.pdf', { type: 'application/pdf' })

        // Mock API to hang so we remain in 'uploading' state (startWorker runs synchronously up to the first await)
        vi.mocked(apiClient.post).mockImplementation(() => new Promise(() => { }))

        await act(async () => {
            await useUploadStore.getState().enqueueFiles([file])
        })

        const items = useUploadStore.getState().items
        expect(items).toHaveLength(1)
        expect(items[0].fileMeta.name).toBe('test.pdf')
        // startWorker runs immediately and sets status to uploading
        expect(items[0].status).toBe('uploading')

        // Verify IDB storage
        expect(idb.set).toHaveBeenCalled()
        expect(useUploadStore.getState().isOpen).toBe(true)
    })

    it('persists queue metadata to localStorage', async () => {
        const file = new File(['content'], 'persist.pdf', { type: 'application/pdf' })
        const setItemSpy = vi.spyOn(localStorage, 'setItem')

        // Prevent upload from resolving so we don't start SSE/polling
        vi.mocked(apiClient.post).mockImplementation(() => new Promise(() => { }))

        await act(async () => {
            await useUploadStore.getState().enqueueFiles([file])
        })

        // Allow persist middleware to flush
        await new Promise(resolve => setTimeout(resolve, 0))

        expect(setItemSpy).toHaveBeenCalled()
        setItemSpy.mockRestore()
    })

    it('processes queue: uploads and transitions to processing', async () => {
        const file = new File(['content'], 'test.pdf', { type: 'application/pdf' })

        // Mock successful upload response
        vi.mocked(apiClient.post).mockImplementation((url) => {
            if (url === '/documents') {
                return Promise.resolve({ data: { document_id: 'doc-123', events_url: '/v1/documents/doc-123/events' } })
            }
            if (url === '/auth/ticket') {
                return Promise.resolve({ data: { ticket: 'ticket-123' } })
            }
            return Promise.resolve({})
        })

        await act(async () => {
            await useUploadStore.getState().enqueueFiles([file])
        })

        // Wait for async worker
        await new Promise(resolve => setTimeout(resolve, 50))

        const items = useUploadStore.getState().items

        // Check API call
        expect(apiClient.post).toHaveBeenCalledWith('/documents', expect.any(FormData), expect.any(Object))

        // Assertions
        expect(items[0].status).toBe('processing')
        expect(items[0].documentId).toBe('doc-123')

        // Check SSE connection
        expect(apiClient.post).toHaveBeenCalledWith('/auth/ticket')
        // We can't easily check SSEManager constructor params without spying on the class mock, but we know it should have been instantiated
        // (Note: we mocked the module returning a function, checking if that function was called is possible if we imported it)
    })

    it('sends multipart upload headers', async () => {
        const file = new File(['content'], 'header.pdf', { type: 'application/pdf' })

        vi.mocked(apiClient.post).mockImplementation((url) => {
            if (url === '/documents') {
                return Promise.resolve({ data: { document_id: 'doc-123', events_url: '/v1/documents/doc-123/events' } })
            }
            if (url === '/auth/ticket') {
                return Promise.resolve({ data: { ticket: 'ticket-123' } })
            }
            return Promise.resolve({})
        })

        await act(async () => {
            await useUploadStore.getState().enqueueFiles([file])
        })

        await new Promise(resolve => setTimeout(resolve, 50))

        const uploadCall = vi.mocked(apiClient.post).mock.calls.find(call => call[0] === '/documents')
        expect(uploadCall).toBeTruthy()
        const config = uploadCall?.[2] as { headers?: Record<string, string> } | undefined
        expect(config?.headers?.['Content-Type']).toBe('multipart/form-data')
    })

    it('handles upload failure', async () => {
        const file = new File(['content'], 'fail.pdf', { type: 'application/pdf' })

        vi.mocked(apiClient.post).mockRejectedValue(new Error('Network Error'))

        await act(async () => {
            await useUploadStore.getState().enqueueFiles([file])
        })

        await new Promise(resolve => setTimeout(resolve, 50))

        const items = useUploadStore.getState().items
        expect(items[0].status).toBe('failed')
        expect(items[0].error).toBe('Network Error')
    })

    it('reconstructs filename when IDB returns a Blob', async () => {
        const file = new File(['content'], 'original.pdf', { type: 'application/pdf' })
        const blob = new Blob(['content'], { type: 'application/pdf' })

        vi.mocked(idb.get).mockResolvedValue(blob)

        vi.mocked(apiClient.post).mockImplementation((url, formData) => {
            if (url === '/documents') {
                const uploaded = (formData as FormData).get('file') as File
                expect(uploaded.name).toBe('original.pdf')
                return Promise.reject(new Error('stop-after-assert'))
            }
            return Promise.resolve({ data: {} })
        })

        await act(async () => {
            await useUploadStore.getState().enqueueFiles([file])
        })

        await new Promise(resolve => setTimeout(resolve, 50))
    })
})
