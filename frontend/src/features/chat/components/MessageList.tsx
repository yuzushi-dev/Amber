import { useRef, useEffect } from 'react'
import { Message } from '../store'
import MessageItem from './MessageItem'

interface MessageListProps {
    messages: Message[]
}

export default function MessageList({ messages }: MessageListProps) {
    const bottomRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages])

    return (
        <div className="flex-1 overflow-y-auto w-full">
            {messages.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center p-8">
                    <div className="max-w-md w-full text-center space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
                        {/* Hero Icon */}
                        <div className="relative mx-auto w-24 h-24">
                            <div className="absolute inset-0 bg-primary/20 blur-3xl rounded-full" />
                            <div className="relative bg-gradient-to-tr from-primary/10 to-primary/5 border border-primary/20 rounded-3xl p-6 shadow-2xl">
                                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-full h-full text-primary">
                                    <path d="M12 2a10 10 0 0 1 10 10c0 5.523-4.477 10-10 10S2 17.523 2 12 6.477 2 12 2z" />
                                    <path d="m9 12 2 2 4-4" />
                                    <path d="M12 8v8" className="opacity-0" /> {/* Decorative */}
                                </svg>
                            </div>
                        </div>

                        {/* Hero Text */}
                        <div className="space-y-4">
                            <h2 className="text-3xl font-display font-bold tracking-tight bg-gradient-to-br from-white to-white/60 bg-clip-text text-transparent">
                                Hi, I'm Amber
                            </h2>
                            <p className="text-lg text-muted-foreground/80 leading-relaxed font-light">
                                Your advanced documents intelligence assistant. Ask me anything about your data.
                            </p>
                        </div>

                        {/* Warning/Disclaimer Badge */}
                        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/5 text-xs text-muted-foreground/60">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500/50" />
                            AI can make mistakes. Please verify important information.
                        </div>
                    </div>
                </div>
            ) : (
                messages.map((msg, index) => {
                    // Find preceding user query for assistant responses
                    let queryContent: string | undefined;
                    if (msg.role === 'assistant' && index > 0) {
                        const prevMsg = messages[index - 1];
                        if (prevMsg.role === 'user') {
                            queryContent = prevMsg.content;
                        }
                    }
                    return (
                        <MessageItem
                            key={msg.id}
                            message={msg}
                            queryContent={queryContent}
                        />
                    );
                })
            )}
            <div ref={bottomRef} className="h-4" />
        </div>
    )
}
