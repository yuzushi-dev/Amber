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
        <img
            src="/avatar.png"
            alt="Amber Assistant"
            className={cn(
                "rounded-full object-cover shadow-sm bg-secondary",
                sizeClasses[size],
                className
            )}
        />
    )
}
