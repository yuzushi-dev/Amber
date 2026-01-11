import { cn } from '@/lib/utils'

interface ConnectorIconProps {
    type: string
    className?: string
    size?: 'sm' | 'md' | 'lg'
}

const sizeClasses = {
    sm: 'w-8 h-8',
    md: 'w-12 h-12',
    lg: 'w-16 h-16',
}

/**
 * Stylized abstract icons for each connector type.
 * Uses gradient fills with CSS variables for consistent theming.
 */
export function ConnectorIcon({ type, className, size = 'md' }: ConnectorIconProps) {
    const baseClasses = cn(
        sizeClasses[size],
        'transition-transform duration-300',
        className
    )

    switch (type.toLowerCase()) {
        case 'zendesk':
            return <ZendeskIcon className={baseClasses} />
        case 'confluence':
            return <ConfluenceIcon className={baseClasses} />
        case 'carbonio':
            return <CarbonioIcon className={baseClasses} />
        default:
            return <GenericConnectorIcon className={baseClasses} type={type} />
    }
}

/**
 * Zendesk: Support/ticket-inspired icon
 * Abstract ticket shape with headset curves
 */
function ZendeskIcon({ className }: { className?: string }) {
    return (
        <div className={cn('relative', className)}>
            <svg viewBox="0 0 48 48" fill="none" className="w-full h-full">
                <defs>
                    <linearGradient id="zendesk-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="hsl(18, 100%, 64%)" />
                        <stop offset="100%" stopColor="hsl(14, 100%, 48%)" />
                    </linearGradient>
                    <filter id="zendesk-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="2" result="coloredBlur" />
                        <feMerge>
                            <feMergeNode in="coloredBlur" />
                            <feMergeNode in="SourceGraphic" />
                        </feMerge>
                    </filter>
                </defs>
                {/* Ticket shape with rounded corners */}
                <path
                    d="M8 14C8 10.686 10.686 8 14 8H34C37.314 8 40 10.686 40 14V34C40 37.314 37.314 40 34 40H14C10.686 40 8 37.314 8 34V14Z"
                    fill="url(#zendesk-gradient)"
                    filter="url(#zendesk-glow)"
                    className="opacity-90"
                />
                {/* Headset/support symbol */}
                <path
                    d="M16 28C16 23.582 19.582 20 24 20C28.418 20 32 23.582 32 28"
                    stroke="hsl(30, 12%, 5%)"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    fill="none"
                />
                <circle cx="16" cy="28" r="3" fill="hsl(30, 12%, 5%)" />
                <circle cx="32" cy="28" r="3" fill="hsl(30, 12%, 5%)" />
                {/* Smile/ticket notch */}
                <path
                    d="M20 34C20 34 22 36 24 36C26 36 28 34 28 34"
                    stroke="hsl(30, 12%, 5%)"
                    strokeWidth="2"
                    strokeLinecap="round"
                    fill="none"
                />
            </svg>
        </div>
    )
}

/**
 * Confluence: Wiki/knowledge-inspired icon
 * Abstract book/pages shape with connecting nodes
 */
function ConfluenceIcon({ className }: { className?: string }) {
    return (
        <div className={cn('relative', className)}>
            <svg viewBox="0 0 48 48" fill="none" className="w-full h-full">
                <defs>
                    <linearGradient id="confluence-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="hsl(217, 91%, 65%)" />
                        <stop offset="100%" stopColor="hsl(217, 91%, 50%)" />
                    </linearGradient>
                    <filter id="confluence-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="2" result="coloredBlur" />
                        <feMerge>
                            <feMergeNode in="coloredBlur" />
                            <feMergeNode in="SourceGraphic" />
                        </feMerge>
                    </filter>
                </defs>
                {/* Base rounded square */}
                <rect
                    x="8" y="8"
                    width="32" height="32"
                    rx="8"
                    fill="url(#confluence-gradient)"
                    filter="url(#confluence-glow)"
                    className="opacity-90"
                />
                {/* Page stack effect */}
                <rect x="14" y="14" width="20" height="20" rx="2" fill="hsl(30, 12%, 5%)" fillOpacity="0.15" />
                <rect x="16" y="12" width="16" height="2" rx="1" fill="hsl(30, 12%, 5%)" fillOpacity="0.3" />
                {/* Document lines */}
                <line x1="18" y1="20" x2="30" y2="20" stroke="hsl(30, 12%, 5%)" strokeWidth="2" strokeLinecap="round" />
                <line x1="18" y1="25" x2="28" y2="25" stroke="hsl(30, 12%, 5%)" strokeWidth="2" strokeLinecap="round" />
                <line x1="18" y1="30" x2="24" y2="30" stroke="hsl(30, 12%, 5%)" strokeWidth="2" strokeLinecap="round" />
            </svg>
        </div>
    )
}

/**
 * Carbonio: Mail + Chat inspired icon
 * Abstract envelope with chat bubble accent
 */
function CarbonioIcon({ className }: { className?: string }) {
    return (
        <div className={cn('relative', className)}>
            <svg viewBox="0 0 48 48" fill="none" className="w-full h-full">
                <defs>
                    <linearGradient id="carbonio-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="hsl(48, 100%, 62%)" />
                        <stop offset="100%" stopColor="hsl(38, 100%, 50%)" />
                    </linearGradient>
                    <linearGradient id="carbonio-accent" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="hsl(38, 100%, 55%)" />
                        <stop offset="100%" stopColor="hsl(30, 95%, 45%)" />
                    </linearGradient>
                    <filter id="carbonio-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="2" result="coloredBlur" />
                        <feMerge>
                            <feMergeNode in="coloredBlur" />
                            <feMergeNode in="SourceGraphic" />
                        </feMerge>
                    </filter>
                </defs>
                {/* Main envelope body */}
                <path
                    d="M6 16C6 13.791 7.791 12 10 12H32C34.209 12 36 13.791 36 16V32C36 34.209 34.209 36 32 36H10C7.791 36 6 34.209 6 32V16Z"
                    fill="url(#carbonio-gradient)"
                    filter="url(#carbonio-glow)"
                    className="opacity-90"
                />
                {/* Envelope flap */}
                <path
                    d="M6 16L21 26L36 16"
                    stroke="hsl(30, 12%, 5%)"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                />
                {/* Chat bubble accent */}
                <circle
                    cx="38" cy="14"
                    r="8"
                    fill="url(#carbonio-accent)"
                    stroke="hsl(32, 10%, 7%)"
                    strokeWidth="2"
                />
                <circle cx="35" cy="14" r="1.5" fill="hsl(30, 12%, 5%)" />
                <circle cx="38" cy="14" r="1.5" fill="hsl(30, 12%, 5%)" />
                <circle cx="41" cy="14" r="1.5" fill="hsl(30, 12%, 5%)" />
            </svg>
        </div>
    )
}

/**
 * Fallback generic connector icon
 * Simple plug/connection shape
 */
function GenericConnectorIcon({ className, type }: { className?: string; type: string }) {
    return (
        <div className={cn('relative', className)}>
            <svg viewBox="0 0 48 48" fill="none" className="w-full h-full">
                <defs>
                    <linearGradient id="generic-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="hsl(var(--muted-foreground))" />
                        <stop offset="100%" stopColor="hsl(var(--muted))" />
                    </linearGradient>
                </defs>
                <rect
                    x="8" y="8"
                    width="32" height="32"
                    rx="8"
                    fill="url(#generic-gradient)"
                    className="opacity-60"
                />
                {/* Connection/plug symbol */}
                <circle cx="18" cy="24" r="4" fill="hsl(var(--foreground))" fillOpacity="0.6" />
                <circle cx="30" cy="24" r="4" fill="hsl(var(--foreground))" fillOpacity="0.6" />
                <line x1="22" y1="24" x2="26" y2="24" stroke="hsl(var(--foreground))" strokeWidth="3" strokeLinecap="round" strokeOpacity="0.6" />
                {/* Type initial as fallback */}
                <text
                    x="24" y="40"
                    textAnchor="middle"
                    fontSize="8"
                    fill="hsl(var(--muted-foreground))"
                    fontWeight="bold"
                >
                    {type.charAt(0).toUpperCase()}
                </text>
            </svg>
        </div>
    )
}

export default ConnectorIcon
