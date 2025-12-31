import { Source } from '../../chat/store'
import { X, FileText } from 'lucide-react'

interface ChunkViewerProps {
    source: Source
    onClose: () => void
}

export default function ChunkViewer({ source, onClose }: ChunkViewerProps) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
            <div className="bg-card border shadow-2xl rounded-xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden">
                <header className="p-4 border-b flex justify-between items-center bg-muted/30">
                    <div className="flex items-center space-x-3">
                        <FileText className="w-5 h-5 text-primary" />
                        <div>
                            <h3 className="font-semibold">{source.title}</h3>
                            <p className="text-xs text-muted-foreground">Original Document Excerpt</p>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-muted rounded-full transition-colors"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </header>

                <div className="flex-1 overflow-y-auto p-8 leading-relaxed text-lg">
                    <p>{source.snippet}</p>
                </div>

                <footer className="p-4 border-t bg-muted/30 flex justify-between items-center text-xs text-muted-foreground">
                    <span>Page {source.page || 1}</span>
                    <span>Similarity Score: {(source.score || 0).toFixed(4)}</span>
                </footer>
            </div>
        </div>
    )
}
