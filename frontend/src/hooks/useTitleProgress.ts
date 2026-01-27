/**
 * useTitleProgress.ts
 * ===================
 * 
 * Custom hook for updating the document title with a progress percentage.
 * Automatically restores the original title when unmounted or when progress is cleared.
 */

import { useEffect, useRef } from 'react'

export function useTitleProgress() {
    const originalTitleRef = useRef<string>(document.title)

    useEffect(() => {
        // Capture original title on mount
        originalTitleRef.current = document.title

        return () => {
            // Restore original title on unmount
            document.title = originalTitleRef.current
        }
    }, [])

    const setProgress = (percent: number | null, label?: string) => {
        if (percent === null) {
            document.title = originalTitleRef.current
        } else {
            const rounded = Math.round(percent)
            const prefix = `[${rounded}%]`
            document.title = label ? `${prefix} ${label}` : `${prefix} ${originalTitleRef.current}`
        }
    }

    return { setProgress }
}
