
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { v4 as uuidv4 } from 'uuid'
import { get as idbGet, set as idbSet, del as idbDel } from 'idb-keyval'
import { apiClient } from '@/lib/api-client'
import { SSEManager } from '@/lib/sse'

// --- Types ---

export type UploadStatus =
    | 'queued'
    | 'uploading'
    | 'processing'
    | 'ready'
    | 'completed'
    | 'failed'
    | 'interrupted'
    | 'missingFile'

export interface FileMeta {
    name: string
    size: number
    type: string
    lastModified: number
}

export interface UploadItem {
    id: string
    fileMeta: FileMeta
    fileKey: string // IDB key
    status: UploadStatus
    uploadProgress: number
    stageProgress: number
    currentStage?: string
    documentId?: string
    eventsUrl?: string
    error?: string
    attempts: number
    createdAt: number
}

interface DocumentUploadResponse {
    document_id: string
    events_url?: string
    status?: string
    message?: string
}

interface UploadState {
    items: UploadItem[]
    isOpen: boolean

    // Actions
    setOpen: (open: boolean) => void
    enqueueFiles: (files: File[]) => Promise<void>
    retry: (id: string) => Promise<void>
    remove: (id: string) => Promise<void>
    dismiss: (id: string) => void // Just remove from list if terminal
    reset: () => void

    // Control
    startWorker: () => void
    rehydrate: () => Promise<void>
}

// --- Runtime Resources (Non-persisted) ---

const abortControllers = new Map<string, AbortController>()
const sseManagers = new Map<string, SSEManager>()
// Removed: const pollingTimers = new Map<string, NodeJS.Timeout>()
let globalPollingTimer: NodeJS.Timeout | null = null

// --- Constants ---
const MAX_CONCURRENT_UPLOADS = 1
const POLLING_INTERVAL = 3000
const UPLOAD_PHASE_WEIGHT = 0.3
const PROCESS_PHASE_WEIGHT = 0.7

// --- Helper: Progress Calculation ---

const isExcludedFromProgress = (status: UploadStatus) =>
    status === 'failed' || status === 'interrupted' || status === 'missingFile'

export const getItemProgress = (item: UploadItem): number => {
    if (item.status === 'queued') return 0
    if (item.status === 'uploading') return item.uploadProgress * UPLOAD_PHASE_WEIGHT
    if (item.status === 'processing') {
        return (UPLOAD_PHASE_WEIGHT * 100) + (item.stageProgress * PROCESS_PHASE_WEIGHT)
    }
    if (item.status === 'ready' || item.status === 'completed') return 100
    return 0
}

export const calculateGlobalProgress = (items: UploadItem[]): number => {
    const relevantItems = items.filter(i => !isExcludedFromProgress(i.status))
    if (relevantItems.length === 0) return 0

    const totalSize = relevantItems.reduce((acc, i) => acc + i.fileMeta.size, 0)
    if (totalSize === 0) return 0

    const loadedBytes = relevantItems.reduce((acc, i) => {
        const p = getItemProgress(i)
        return acc + (i.fileMeta.size * (p / 100))
    }, 0)

    return (loadedBytes / totalSize) * 100
}

const createFileFromBlob = (blob: Blob, meta: FileMeta): File => {
    return new File([blob], meta.name, {
        type: meta.type || blob.type || 'application/octet-stream',
        lastModified: meta.lastModified
    })
}

const loadFileForItem = async (item: UploadItem): Promise<File | null> => {
    const blob = await idbGet(item.fileKey)
    if (!blob) return null
    if (blob instanceof File) return blob
    return createFileFromBlob(blob as Blob, item.fileMeta)
}

const resolveEventsUrl = (eventsUrl: string | undefined, documentId: string): string => {
    if (!eventsUrl) return `/api/v1/documents/${documentId}/events`
    if (eventsUrl.startsWith('/api/')) return eventsUrl
    if (eventsUrl.startsWith('/v1/')) return `/api${eventsUrl}`
    return eventsUrl.startsWith('http') ? eventsUrl : `/api/v1/documents/${documentId}/events`
}


export const useUploadStore = create<UploadState>()(
    persist(
        (set, get) => ({
            items: [],
            isOpen: false,

            setOpen: (open) => set({ isOpen: open }),
            // ... (rest of the store body is inside, we just removed the wrapper)

            enqueueFiles: async (files) => {
                const newItems: UploadItem[] = []
                for (const file of files) {
                    const id = uuidv4()
                    const fileKey = `upload_blob_${id}`

                    // Store blob in IDB
                    await idbSet(fileKey, file)

                    newItems.push({
                        id,
                        fileMeta: {
                            name: file.name,
                            size: file.size,
                            type: file.type,
                            lastModified: file.lastModified
                        },
                        fileKey,
                        status: 'queued',
                        uploadProgress: 0,
                        stageProgress: 0,
                        attempts: 0,
                        createdAt: Date.now()
                    })
                }

                set(state => ({ items: [...state.items, ...newItems], isOpen: true }))
                get().startWorker()
            },

            retry: async (id) => {
                const item = get().items.find(i => i.id === id)
                if (!item) return

                const file = await loadFileForItem(item)
                if (!file) {
                    set(state => ({
                        items: state.items.map(i => i.id === id ? { ...i, status: 'missingFile', error: 'File data lost' } : i)
                    }))
                    return
                }

                set(state => ({
                    items: state.items.map(i => i.id === id ? {
                        ...i,
                        status: 'queued',
                        error: undefined,
                        uploadProgress: 0,
                        stageProgress: 0,
                        attempts: 0
                    } : i)
                }))
                get().startWorker()
            },

            remove: async (id) => {
                const item = get().items.find(i => i.id === id)
                if (item) {
                    // Cleanup runtime
                    abortControllers.get(id)?.abort()
                    abortControllers.delete(id)
                    sseManagers.get(id)?.disconnect()
                    sseManagers.delete(id)
                    // Polling now global, no individual cleanup needed unless it's the last one

                    // Cleanup IDB
                    await idbDel(item.fileKey)
                }

                set(state => ({ items: state.items.filter(i => i.id !== id) }))
                get().startWorker() // Check if others can start
            },

            dismiss: (id) => {
                // Same as remove but maybe keep IDB? No, dismiss means "I'm done with this"
                get().remove(id)
            },

            reset: () => {
                // Clear all completed/terminal
                const { items } = get()
                items.forEach(async i => {
                    // Clean up IDB for all
                    await idbDel(i.fileKey)
                })
                set({ items: [] })
            },

            startWorker: async () => {
                const { items } = get()
                const activeCount = items.filter(i => i.status === 'uploading').length

                // Also kick off polling if we have processing items
                const processingItems = items.filter(i => i.status === 'processing')
                if (processingItems.length > 0) {
                    startGlobalPolling()
                }

                if (activeCount >= MAX_CONCURRENT_UPLOADS) return

                const nextItem = items.find(i => i.status === 'queued')
                if (!nextItem) return

                // Mark as uploading
                set(state => ({
                    items: state.items.map(i => i.id === nextItem.id ? { ...i, status: 'uploading', attempts: i.attempts + 1 } : i)
                }))

                // Process
                try {
                    const file = await loadFileForItem(nextItem)
                    if (!file) {
                        throw new Error('File data missing')
                    }

                    await processItemUpload(nextItem.id, file)

                } catch (e: unknown) {
                    const errorMessage = e instanceof Error ? e.message : 'Upload failed'
                    set(state => ({
                        items: state.items.map(i => i.id === nextItem.id ? {
                            ...i,
                            status: errorMessage === 'File data missing' ? 'missingFile' : 'failed',
                            error: errorMessage
                        } : i)
                    }))
                    // Continue worker
                    get().startWorker()
                }
            },

            rehydrate: async () => {
                const { items } = get()
                let hasChanges = false
                const newItems = [...items]

                for (let i = 0; i < newItems.length; i++) {
                    const item = newItems[i]

                    // If it was uploading, it's now interrupted
                    if (item.status === 'uploading') {
                        newItems[i] = { ...item, status: 'interrupted', error: 'Reloaded during upload' }
                        hasChanges = true
                        continue
                    }

                    // Check if blob exists for non-completed
                    if (!['completed', 'ready', 'failed'].includes(item.status)) {
                        const blob = await idbGet(item.fileKey)
                        if (!blob) {
                            newItems[i] = { ...item, status: 'missingFile', error: 'File cache missing' }
                            hasChanges = true
                        }
                        // If processing, we should reconnect SSE? 
                        // Yes, if we have a documentId and it's not terminal
                        if (item.status === 'processing' && item.documentId) {
                            startSSEMonitoring(item.id, item.documentId, item.eventsUrl)
                        }
                    }
                }

                if (hasChanges) {
                    set({ items: newItems })
                }

                // Restart worker to pick up queues
                get().startWorker()
            }
        }),
        {
            name: 'upload-queue',
            storage: createJSONStorage(() => localStorage),
            partialize: (state) => ({
                items: state.items,
                isOpen: state.isOpen
            })
        }
    )
)

// --- Internal Logic ---

const processItemUpload = async (itemId: string, file: File) => {
    const controller = new AbortController()
    abortControllers.set(itemId, controller)

    try {
        const formData = new FormData()
        formData.append('file', file)

        const res = await apiClient.post<DocumentUploadResponse>('/documents', formData, {
            signal: controller.signal,
            timeout: 0, // No timeout for uploads
            headers: {
                'Content-Type': 'multipart/form-data',
            },
            onUploadProgress: (progressEvent) => {
                const percent = Math.round((progressEvent.loaded * 100) / (progressEvent.total || file.size))
                useUploadStore.setState(state => ({
                    items: state.items.map(i => i.id === itemId ? { ...i, uploadProgress: percent } : i)
                }))
            }
        })

        const { document_id: documentId, events_url: eventsUrl } = res.data
        if (!documentId) {
            throw new Error('Upload response missing document_id')
        }

        // Mark as processing
        useUploadStore.setState(state => ({
            items: state.items.map(i => i.id === itemId ? {
                ...i,
                status: 'processing',
                uploadProgress: 100,
                stageProgress: 0,
                documentId,
                eventsUrl
            } : i)
        }))

        // Cleanup upload controller
        abortControllers.delete(itemId)

        // Start Monitoring
        startSSEMonitoring(itemId, documentId, eventsUrl)

        // Trigger next
        useUploadStore.getState().startWorker()

    } catch (e: unknown) {
        if (e instanceof Error && e.name === 'AbortError') {
            // Handled by caller or user action
        } else {
            throw e
        }
    }
}

type UploadStatusEvent = {
    status?: string
    error_message?: string
    error?: string
}

const startSSEMonitoring = async (itemId: string, documentId: string, eventsUrl?: string) => {
    // secure ticket
    try {
        const ticketRes = await apiClient.post<{ ticket: string }>('/auth/ticket')
        const ticket = ticketRes.data.ticket

        const baseUrl = resolveEventsUrl(eventsUrl, documentId)
        const monitorUrl = baseUrl.includes('?')
            ? `${baseUrl}&ticket=${encodeURIComponent(ticket)}`
            : `${baseUrl}?ticket=${encodeURIComponent(ticket)}`

        const manager = new SSEManager(
            monitorUrl,
            (event) => {
                try {
                    const data = JSON.parse(event.data)
                    handleSSEMessage(itemId, data)
                } catch (e) {
                    console.error('SSE parse error', e)
                }
            },
            (err) => {
                console.warn('SSE Error', err)
                // Retry handled by SSEManager usually, but we have limits
            }
        )

        sseManagers.set(itemId, manager)
        manager.connect()

        // Fallback Polling - kicked off globally now
        startGlobalPolling()

    } catch (e) {
        console.error('Failed to start monitoring', e)
    }
}

const handleSSEMessage = (itemId: string, data: UploadStatusEvent) => {
    if (!data.status) return

    // Map backend status to store 
    // Backend: uploaded, ingested, extracting, classifying, chunking, embedding, graph_sync, ready, failed

    // We update stage stats
    // Map status to progress %
    const STAGE_WEIGHTS: Record<string, number> = {
        'ingested': 5,
        'extracting': 10,
        'classifying': 20,
        'chunking': 35,
        'embedding': 50,
        'graph_sync': 70,
        'ready': 100,
        'completed': 100
    }

    const defaultProgress = STAGE_WEIGHTS[data.status] ?? 0
    let progress = (data as any).progress

    // If progress is missing (e.g. from polling), and we are in the same stage,
    // preserve the current granular progress instead of reverting to default.
    const currentItem = useUploadStore.getState().items.find(i => i.id === itemId)
    if (progress === undefined) {
        if (currentItem && currentItem.currentStage === data.status) {
            progress = currentItem.stageProgress
        } else {
            progress = defaultProgress
        }
    }
    let newStatus: UploadStatus = 'processing'

    if (data.status === 'ready' || data.status === 'completed') newStatus = 'ready'
    if (data.status === 'failed') newStatus = 'failed'
    const errorMessage = data.error_message || data.error

    useUploadStore.setState(state => ({
        items: state.items.map(i => i.id === itemId ? {
            ...i,
            status: newStatus,
            stageProgress: progress,
            currentStage: data.status,
            error: errorMessage
        } : i)
    }))

    if (newStatus === 'ready' || newStatus === 'failed') {
        cleanupMonitoring(itemId)
        // Cleanup IDB blob now that it's done/failed (if failed, we might want to keep it? No, backend failed processing, not upload. The source file is less useful unless we re-upload, but design says "user can retry". Retry implies re-upload usually. If backend fails processing, re-uploading the SAME file might just fail again unless it was a transient error. Let's keep IDB blob until user dismisses or we decide policy. Design says: "On terminal state: cleanup runtime resources, advance queue". It doesn't explicitly say delete blob. "markComplete" action in plan says "Remove blob". Let's stick to that.)

        // Wait, if it failed processing, we might not want to delete the blob if the user wants to "retry" (re-upload).
        // But "Retry" in our store logic resets to "queued" and checks IDB. So we MUST keep IDB blob if we want retry to work without selecting file again.
        // Let's only delete blob on success or manual remove.
        if (newStatus === 'ready') {
            const fileKey = useUploadStore.getState().items.find(i => i.id === itemId)?.fileKey
            if (fileKey) {
                idbDel(fileKey)
            }
        }
    }
}

const checkStatus = async (itemId: string, documentId: string) => {
    try {
        const res = await apiClient.get<UploadStatusEvent>(`/documents/${documentId}`)
        handleSSEMessage(itemId, res.data)
    } catch (e) {
        console.error('Polling error', e)
    }
}

const cleanupMonitoring = (itemId: string) => {
    sseManagers.get(itemId)?.disconnect()
    sseManagers.delete(itemId)

    // Global polling takes care of itself (won't pick up items that aren't processing)
}

// --- Global Polling ---

const startGlobalPolling = () => {
    if (globalPollingTimer) return // Already running
    // Start the loop
    globalPollingTimer = setTimeout(runGlobalPoll, POLLING_INTERVAL)
}

const runGlobalPoll = async () => {
    const state = useUploadStore.getState()
    // Identify items that need polling: 'processing' state and have a documentId
    // We could also poll 'uploading' if we wanted server-side confirmation, but usually we just poll 'processing'
    const processingItems = state.items.filter(i => i.status === 'processing' && i.documentId)

    if (processingItems.length === 0) {
        // Stop polling if nothing to do
        if (globalPollingTimer) {
            clearTimeout(globalPollingTimer)
            globalPollingTimer = null
        }
        return
    }

    // Process sequentially to be gentle on the browser
    for (const item of processingItems) {
        if (item.documentId) {
            await checkStatus(item.id, item.documentId)
        }
    }

    // Schedule next run
    globalPollingTimer = setTimeout(runGlobalPoll, POLLING_INTERVAL)
}
