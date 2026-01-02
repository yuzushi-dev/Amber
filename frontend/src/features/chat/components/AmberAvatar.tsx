/**
 * AmberAvatar.tsx
 * ===============
 * 
 * Avatar component for the Amber assistant identity.
 * Uses brand colors from AMBER-UI-PALETTE.
 */

import { cn } from '@/lib/utils'

interface AmberAvatarProps {
    size?: 'sm' | 'md' | 'lg'
    className?: string
}

const sizeClasses = {
    sm: 'w-6 h-6 text-xs',
    md: 'w-8 h-8 text-sm',
    lg: 'w-12 h-12 text-base',
}

export default function AmberAvatar({ size = 'md', className }: AmberAvatarProps) {
    return (
        <div
            className={cn(
                "rounded-full flex items-center justify-center shrink-0 font-bold",
                "bg-gradient-to-br from-amber-400 to-amber-600 text-white shadow-sm",
                sizeClasses[size],
                className
            )}
            aria-label="Amber Assistant"
            role="img"
        >
            A
        </div>
    )
}
