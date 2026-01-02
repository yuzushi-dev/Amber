/**
 * useFuzzySearch Hook
 * ====================
 * 
 * Generic fuzzy search hook using Fuse.js.
 * Supports searching any array of objects by specified keys.
 */

import { useMemo } from 'react'
import Fuse, { IFuseOptions } from 'fuse.js'

export interface UseFuzzySearchOptions<T> {
    /** Keys to search within each item */
    keys: (keyof T | string)[]
    /** Fuse.js threshold (0 = exact, 1 = match anything). Default: 0.4 */
    threshold?: number
    /** Minimum characters before search activates. Default: 1 */
    minMatchCharLength?: number
}

export function useFuzzySearch<T>(
    items: T[] | undefined,
    query: string,
    options: UseFuzzySearchOptions<T>
): T[] {
    const { keys, threshold = 0.4, minMatchCharLength = 1 } = options

    const fuse = useMemo(() => {
        if (!items || items.length === 0) return null

        const fuseOptions: IFuseOptions<T> = {
            keys: keys as string[],
            threshold,
            minMatchCharLength,
            ignoreLocation: true,
            includeScore: false,
        }

        return new Fuse(items, fuseOptions)
    }, [items, keys, threshold, minMatchCharLength])

    const results = useMemo(() => {
        // Return all items if no query or query too short
        if (!query || query.length < minMatchCharLength) {
            return items || []
        }

        if (!fuse) {
            return items || []
        }

        // Return matched items
        return fuse.search(query).map(result => result.item)
    }, [fuse, query, items, minMatchCharLength])

    return results
}

export default useFuzzySearch
