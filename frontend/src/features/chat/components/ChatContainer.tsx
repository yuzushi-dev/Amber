import { useChatStore } from '../store'
import { useChatStream } from '../hooks/useChatStream'
import MessageList from './MessageList'
import QueryInput from './QueryInput'

export default function ChatContainer() {
    const { messages } = useChatStore()
    const { startStream, isStreaming } = useChatStream()

    return (
        <main
            className="flex flex-col h-full w-full max-w-5xl mx-auto border-x bg-card/10"
            aria-label="Chat with Amber"
        >
            <div className="flex-1 flex flex-col min-h-0 bg-background/50 backdrop-blur-sm">
                <header className="p-4 border-b flex justify-between items-center bg-card">
                    <div>
                        <h1 className="font-semibold">New Conversation</h1>
                        <p className="text-xs text-muted-foreground">Hybrid GraphRAG Engine</p>
                    </div>
                    {isStreaming && (
                        <div
                            className="flex items-center gap-2 text-sm text-muted-foreground"
                            role="status"
                            aria-live="polite"
                        >
                            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" aria-hidden="true" />
                            <span>Generating response...</span>
                        </div>
                    )}
                </header>

                {/* Live region for streaming message updates */}
                <div
                    aria-live="polite"
                    aria-atomic="false"
                    className="contents"
                >
                    <MessageList messages={messages} />
                </div>

                <QueryInput onSend={startStream} disabled={isStreaming} />
            </div>
        </main>
    )
}

