import { Loader2 } from 'lucide-react'

interface LoadingStateProps {
    message?: string
}

export default function LoadingState({ message = "Loading..." }: LoadingStateProps) {
    return (
        <div className="flex flex-col items-center justify-center p-12 text-center space-y-4 animate-in fade-in duration-300">
            <Loader2 className="w-10 h-10 animate-spin text-primary opacity-50" />
            <p className="text-sm text-muted-foreground font-medium animate-pulse">{message}</p>
        </div>
    )
}
