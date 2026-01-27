/**
 * useNotification.ts
 * ==================
 * 
 * Custom hook for browser notifications.
 * Shows native browser notifications when the tab is not visible.
 */

import { useCallback, useRef } from 'react'

interface NotificationOptions {
    body?: string
    icon?: string
    tag?: string
    onClick?: () => void
}

interface UseNotificationReturn {
    /** Whether the Notification API is supported */
    isSupported: boolean
    /** Request notification permission. Returns true if granted. */
    requestPermission: () => Promise<boolean>
    /** Show a notification if permission is granted and tab is hidden */
    showNotification: (title: string, options?: NotificationOptions) => void
}

export function useNotification(): UseNotificationReturn {
    const notificationRef = useRef<Notification | null>(null)

    const isSupported = typeof window !== 'undefined' && 'Notification' in window

    const requestPermission = useCallback(async (): Promise<boolean> => {
        if (!isSupported) return false

        if (Notification.permission === 'granted') {
            return true
        }

        if (Notification.permission === 'denied') {
            return false
        }

        // Request permission
        const result = await Notification.requestPermission()
        return result === 'granted'
    }, [isSupported])

    const showNotification = useCallback((title: string, options?: NotificationOptions) => {
        if (!isSupported) return
        if (Notification.permission !== 'granted') return

        // Only show notification if tab is not visible
        if (document.visibilityState === 'visible') return

        // Close any existing notification with the same tag
        if (notificationRef.current) {
            notificationRef.current.close()
        }

        const notification = new Notification(title, {
            body: options?.body,
            icon: options?.icon || '/amber-icon.png',
            tag: options?.tag || 'upload-notification',
        })

        notificationRef.current = notification

        // Handle click to focus the app
        notification.onclick = () => {
            window.focus()
            notification.close()
            options?.onClick?.()
        }

        // Auto-close after 10 seconds
        setTimeout(() => {
            notification.close()
        }, 10000)
    }, [isSupported])

    return {
        isSupported,
        requestPermission,
        showNotification,
    }
}
