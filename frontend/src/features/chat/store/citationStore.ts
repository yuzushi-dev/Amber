import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export interface Citation {
    id: string; // Unique ID for the citation instance (e.g., messageId-index)
    type: 'Document' | 'Code' | 'Source';
    label: string; // e.g., "auth.py" or "User Manual"
    value: string; // The raw value e.g. "src/auth.py:L10-20"
    content?: string; // The resolved content (text/code)
    filePath?: string;
    startLine?: number;
    endLine?: number;
}

interface CitationState {
    // Map of messageId -> citations list
    citations: Map<string, Citation[]>;

    // The conversation this state belongs to
    activeConversationId: string | null;

    // The message currently being inspected in the Citation Explorer
    activeMessageId: string | null;

    // The citation currently hovered (in chat or explorer)
    hoveredCitationId: string | null;

    // The citation actively selected (clicked)
    selectedCitationId: string | null;

    // Actions
    registerCitations: (messageId: string, citations: Citation[]) => void;
    setActiveConversationId: (id: string | null) => void;
    setActiveMessageId: (id: string | null) => void;
    setHoveredCitation: (id: string | null) => void;
    selectCitation: (id: string | null) => void;
    reset: () => void;
}

export const useCitationStore = create<CitationState>()(
    persist(
        (set) => ({
            citations: new Map(),
            activeConversationId: null,
            activeMessageId: null,
            hoveredCitationId: null,
            selectedCitationId: null,

            registerCitations: (messageId, newCitations) =>
                set((state) => {
                    const next = new Map(state.citations);
                    next.set(messageId, newCitations);
                    return { citations: next };
                }),

            setActiveConversationId: (id) => set({ activeConversationId: id }),

            setActiveMessageId: (id) => set({ activeMessageId: id }),

            setHoveredCitation: (id) => set({ hoveredCitationId: id }),

            selectCitation: (id) => set({ selectedCitationId: id }),

            reset: () => set({
                activeMessageId: null,
                hoveredCitationId: null,
                selectedCitationId: null,
                activeConversationId: null,
                citations: new Map()
            })
        }),
        {
            name: 'citation-storage',
            storage: createJSONStorage(() => sessionStorage),
            partialize: (state) => ({
                activeConversationId: state.activeConversationId,
                activeMessageId: state.activeMessageId,
                selectedCitationId: state.selectedCitationId
            }),
        }
    )
);
