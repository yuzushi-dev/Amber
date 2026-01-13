import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { ThumbsUp, ThumbsDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'

interface RatingProps {
    messageId: string
    initialRating?: 'up' | 'down' | null
}

export default function Rating({ messageId, initialRating = null }: RatingProps) {
    const [rating, setRating] = useState<'up' | 'down' | null>(initialRating)
    const [isSubmitting, setIsSubmitting] = useState(false)

    const handleRate = async (type: 'up' | 'down') => {
        if (isSubmitting) return

        // Toggle off if clicking the same
        const newRating = rating === type ? null : type
        setRating(newRating)
        setIsSubmitting(true)

        try {
            await apiClient.post(`/feedback/${messageId}`, {
                type: newRating,
                // Additional metadata could go here
            })
        } catch (err) {
            console.error('Failed to submit feedback', err)
        } finally {
            setIsSubmitting(false)
        }
    }

    return (
        <div className="flex items-center space-x-1">
            <Button
                variant="ghost"
                size="icon"
                onClick={() => handleRate('up')}
                disabled={isSubmitting}
                className={cn(
                    "h-8 w-8 transition-colors",
                    rating === 'up' ? "text-green-600 bg-green-100 hover:bg-green-200 hover:text-green-700" : "text-muted-foreground hover:bg-muted"
                )}
            >
                <ThumbsUp className="w-4 h-4" />
            </Button>
            <Button
                variant="ghost"
                size="icon"
                onClick={() => handleRate('down')}
                disabled={isSubmitting}
                className={cn(
                    "h-8 w-8 transition-colors",
                    rating === 'down' ? "text-red-600 bg-red-100 hover:bg-red-200 hover:text-red-700" : "text-muted-foreground hover:bg-muted"
                )}
            >
                <ThumbsDown className="w-4 h-4" />
            </Button>
        </div>
    )
}
