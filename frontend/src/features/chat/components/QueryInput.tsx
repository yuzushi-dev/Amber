import React, { useState, useRef, useEffect } from 'react'
import { SendHorizontal, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

interface QueryInputProps {
    onSend: (query: string) => void
    disabled?: boolean
}

export default function QueryInput({ onSend, disabled }: QueryInputProps) {
    const [query, setQuery] = useState('')
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    const handleSubmit = (e?: React.FormEvent) => {
        e?.preventDefault()
        if (query.trim() && !disabled) {
            onSend(query.trim())
            setQuery('')
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSubmit()
        }
    }

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'inherit'
            textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
        }
    }, [query])

    return (
        <form
            onSubmit={handleSubmit}
            className="p-4 border-t bg-card"
            role="search"
            aria-label="Ask a question"
        >
            <div className="relative flex items-end space-x-2 px-4">
                <label htmlFor="query-input" className="sr-only">
                    Enter your question
                </label>
                <textarea
                    id="query-input"
                    ref={textareaRef}
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask Amber..."
                    className={cn(
                        "flex-1 w-full bg-background border rounded-lg px-4 py-3 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1 resize-none",
                        "min-h-[48px] max-h-[200px]"
                    )}
                    disabled={disabled}
                    rows={1}
                    aria-describedby="query-hint"
                    aria-busy={disabled}
                />
                <Button
                    type="submit"
                    size="icon"
                    disabled={!query.trim() || disabled}
                    className="shrink-0"
                    aria-label={disabled ? "Processing query" : "Send query"}
                >
                    {disabled ? (
                        <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" />
                    ) : (
                        <SendHorizontal className="w-5 h-5" aria-hidden="true" />
                    )}
                </Button>
            </div>
            <p id="query-hint" className="text-[10px] text-center mt-2 text-muted-foreground opacity-50">
                Shift + Enter for new line. Amber can make mistakes. Check important info.
            </p>
        </form>
    )
}

