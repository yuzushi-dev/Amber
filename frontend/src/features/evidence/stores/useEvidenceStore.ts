import { create } from 'zustand'

interface EvidenceStore {
    isOpen: boolean
    selectedSourceId: string | null
    toggle: () => void
    open: () => void
    close: () => void
    selectSource: (id: string | null) => void
}

export const useEvidenceStore = create<EvidenceStore>((set) => ({
    isOpen: false, // Default to hidden
    selectedSourceId: null,
    toggle: () => set((state) => ({ isOpen: !state.isOpen })),
    open: () => set({ isOpen: true }),
    close: () => set({ isOpen: false }),
    selectSource: (id) => set({ selectedSourceId: id, isOpen: true }), // Auto-open on select
}))
