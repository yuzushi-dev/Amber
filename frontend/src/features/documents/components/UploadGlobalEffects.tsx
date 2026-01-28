
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNotification } from '@/hooks/useNotification'
import { useTitleProgress } from '@/hooks/useTitleProgress'
import { calculateGlobalProgress, useUploadStore } from '../stores/useUploadStore'

export function UploadGlobalEffects() {
    const items = useUploadStore(state => state.items)
    const rehydrate = useUploadStore(state => state.rehydrate)
    const startWorker = useUploadStore(state => state.startWorker)
    const { setProgress } = useTitleProgress()
    const { requestPermission, showNotification } = useNotification()

    // Rehydrate on mount
    useEffect(() => {
        rehydrate()
    }, [rehydrate])

    // Request notification permission once when queue starts
    const permissionRequestedRef = useRef(false)
    useEffect(() => {
        if (!permissionRequestedRef.current && items.length > 0) {
            permissionRequestedRef.current = true
            requestPermission()
        }
    }, [items.length, requestPermission])

    // Watch items for title update
    useEffect(() => {
        const relevantItems = items.filter(i => !['failed', 'interrupted', 'missingFile'].includes(i.status))
        if (relevantItems.length === 0) {
            setProgress(null)
            return
        }

        const uploadingCount = relevantItems.filter(i => i.status === 'uploading').length
        const processingCount = relevantItems.filter(i => i.status === 'processing').length
        const queuedCount = relevantItems.filter(i => i.status === 'queued').length
        const totalCount = relevantItems.length
        const activeCount = uploadingCount + processingCount + queuedCount

        if (activeCount === 0) {
            setProgress(null)
            return
        }

        const percent = calculateGlobalProgress(items)
        let label = `Queued ${queuedCount}/${totalCount}`
        if (uploadingCount > 0) {
            label = `Uploading ${uploadingCount}/${totalCount}`
        } else if (processingCount > 0) {
            label = `Processing ${processingCount}/${totalCount}`
        }

        setProgress(percent, label)

        // Keep worker alive
        startWorker()
    }, [items, setProgress, startWorker])

    // Notify on completion/failure (hidden tab only)
    const notifiedRef = useRef<Map<string, 'success' | 'failed'>>(new Map())
    useEffect(() => {
        items.forEach(item => {
            if (['queued', 'uploading', 'processing'].includes(item.status)) {
                notifiedRef.current.delete(item.id)
                return
            }

            if (item.status === 'ready' || item.status === 'completed') {
                if (notifiedRef.current.get(item.id) !== 'success') {
                    showNotification('Upload Complete', {
                        body: `"${item.fileMeta.name}" processed successfully`,
                        tag: `upload-${item.id}-complete`,
                    })
                    notifiedRef.current.set(item.id, 'success')
                }
                return
            }

            if (['failed', 'interrupted', 'missingFile'].includes(item.status)) {
                if (notifiedRef.current.get(item.id) !== 'failed') {
                    const reason = item.status === 'interrupted'
                        ? 'Upload interrupted — please retry.'
                        : item.status === 'missingFile'
                            ? 'File data missing — please reselect.'
                            : (item.error || 'Processing failed.')
                    showNotification('Upload Failed', {
                        body: `"${item.fileMeta.name}" failed: ${reason}`,
                        tag: `upload-${item.id}-failed`,
                    })
                    notifiedRef.current.set(item.id, 'failed')
                }
            }
        })
    }, [items, showNotification])

    // Watch for completion to invalidate queries
    const queryClient = useQueryClient()
    const lastCompletedRef = useRef<Set<string>>(new Set())

    useEffect(() => {
        const completedItems = items.filter(i => i.status === 'ready' || i.status === 'completed')
        let shouldRefetch = false

        // Check for new completions
        completedItems.forEach(item => {
            if (!lastCompletedRef.current.has(item.id)) {
                lastCompletedRef.current.add(item.id)
                shouldRefetch = true
            }
        })

        if (shouldRefetch) {
            queryClient.invalidateQueries({ queryKey: ['documents'] })
            queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] })
            queryClient.invalidateQueries({ queryKey: ['graph-top-nodes'] })
        }
    }, [items, queryClient])

    return null
}
