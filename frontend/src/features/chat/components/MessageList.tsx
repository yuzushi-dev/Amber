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
                <div className="h-full flex flex-col items-center justify-center p-8 opacity-50">
                    <p className="text-lg font-medium">Hi, I'm Amber!</p>
                    <p className="text-sm">Your documents intelligence assistant.</p>
                    <p className="text-xs italic">AI can make mistakes, please double check the information.</p>
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
