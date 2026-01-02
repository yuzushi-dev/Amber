import { useState } from 'react'
import { useChatStore } from '../../chat/store'
import SourceCard from './SourceCard'
import { cn } from '@/lib/utils'
import { Search, Network, List } from 'lucide-react'
import EntityGraph from './EntityGraph'
import ChunkViewer from './ChunkViewer'

import { X } from 'lucide-react'
import { useEvidenceStore } from '../stores/useEvidenceStore'

export default function EvidenceBoard() {
    const { messages } = useChatStore()
    const { isOpen, close, selectedSourceId, selectSource } = useEvidenceStore()
    const [view, setView] = useState<'list' | 'graph'>('list')

    if (!isOpen) return null

    // Get sources from the last assistant message
    const assistantMessages = messages.filter(m => m.role === 'assistant')
    const lastMessage = assistantMessages[assistantMessages.length - 1]
    const sources = lastMessage?.sources || []

    const selectedSource = sources.find(s => s.chunk_id === selectedSourceId)

    return (
        <div className="flex flex-col h-full w-[400px] border-l bg-card overflow-hidden">
            <header className="p-4 border-b flex justify-between items-center bg-muted/30">
                <div>
                    <h3 className="font-semibold flex items-center space-x-2">
                        <Search className="w-4 h-4" />
                        <span>Evidence Board</span>
                    </h3>
                    <p className="text-[10px] text-muted-foreground">Sources & Reasoning</p>
                </div>
                <button
                    onClick={close}
                    className="p-1 hover:bg-muted rounded-md transition-colors"
                    aria-label="Close Evidence Board"
                >
                    <X className="w-4 h-4" />
                </button>
                <div className="flex bg-muted rounded-md p-1">
                    <button
                        onClick={() => setView('list')}
                        className={cn(
                            "p-1.5 rounded-sm transition-all",
                            view === 'list' ? "bg-background shadow-sm" : "hover:bg-background/50"
                        )}
                    >
                        <List className="w-4 h-4" />
                    </button>
                    <button
                        onClick={() => setView('graph')}
                        className={cn(
                            "p-1.5 rounded-sm transition-all",
                            view === 'graph' ? "bg-background shadow-sm" : "hover:bg-background/50"
                        )}
                    >
                        <Network className="w-4 h-4" />
                    </button>
                </div>
            </header>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {sources.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-center p-8 opacity-50 space-y-2">
                        <Search className="w-8 h-8 mx-auto" />
                        <p className="text-sm font-medium">No citations found</p>
                        <p className="text-xs">Ask a question to see source evidence here.</p>
                    </div>
                ) : (
                    view === 'list' ? (
                        sources.map((source) => (
                            <SourceCard
                                key={source.chunk_id}
                                source={source}
                                isActive={selectedSourceId === source.chunk_id}
                                onClick={() => selectSource(source.chunk_id)}
                            />
                        ))
                    ) : (
                        <div className="h-full">
                            <EntityGraph />
                        </div>
                    )
                )}
            </div>

            {selectedSource && (
                <ChunkViewer
                    source={selectedSource}
                    onClose={() => selectSource(null)}
                />
            )}
        </div>
    )
}
