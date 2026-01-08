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
                    <p className="text-sm">Your documents intelligence assistant</p>
                </div>
            ) : (
                messages.map((msg) => (
                    <MessageItem key={msg.id} message={msg} />
                ))
            )}
            <div ref={bottomRef} className="h-4" />
        </div>
    )
}
