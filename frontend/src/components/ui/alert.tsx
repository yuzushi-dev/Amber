/**
 * Alert Component
 * ===============
 *
 * Alert/notification component with semantic variants and optional glows.
 * Supports success, warning, error/destructive, and info states.
 */

import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { AlertCircle, CheckCircle, Info, AlertTriangle, X } from "lucide-react"

const alertVariants = cva(
    "relative w-full rounded-lg border p-4 [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-4 [&>svg+div]:pl-8",
    {
        variants: {
            variant: {
                default: "bg-background text-foreground border-border",
                destructive:
                    "bg-[hsl(var(--destructive)_/_0.1)] border-destructive/30 text-destructive [&>svg]:text-destructive",
                success:
                    "bg-success-muted border-success/30 text-success-foreground [&>svg]:text-success",
                warning:
                    "bg-warning-muted border-warning/30 text-warning-foreground [&>svg]:text-warning",
                info:
                    "bg-info-muted border-info/30 text-info-foreground [&>svg]:text-info",
            },
            glow: {
                true: "",
                false: "",
            },
        },
        compoundVariants: [
            {
                variant: "destructive",
                glow: true,
                className: "shadow-glow-destructive",
            },
            {
                variant: "success",
                glow: true,
                className: "shadow-glow-success",
            },
            {
                variant: "warning",
                glow: true,
                className: "shadow-glow-warning",
            },
            {
                variant: "info",
                glow: true,
                className: "shadow-glow-info",
            },
        ],
        defaultVariants: {
            variant: "default",
            glow: false,
        },
    }
)

export interface AlertProps
    extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
    /** Show default icon for variant */
    showIcon?: boolean
    /** Custom icon to override default */
    icon?: React.ReactNode
    /** Show close button */
    dismissible?: boolean
    /** Callback when dismissed */
    onDismiss?: () => void
}

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
    ({ className, variant, glow, showIcon = true, icon, dismissible = false, onDismiss, children, ...props }, ref) => {
        const [dismissed, setDismissed] = React.useState(false)

        const handleDismiss = () => {
            setDismissed(true)
            onDismiss?.()
        }

        if (dismissed) return null

        // Default icons for each variant
        const getDefaultIcon = () => {
            if (icon) return icon

            if (!showIcon) return null

            const iconClass = "h-5 w-5"
            switch (variant) {
                case "destructive":
                    return <AlertCircle className={iconClass} />
                case "success":
                    return <CheckCircle className={iconClass} />
                case "warning":
                    return <AlertTriangle className={iconClass} />
                case "info":
                    return <Info className={iconClass} />
                default:
                    return <Info className={iconClass} />
            }
        }

        return (
            <div
                ref={ref}
                role="alert"
                className={cn(alertVariants({ variant, glow }), className)}
                {...props}
            >
                {getDefaultIcon()}
                <div className="flex-1">
                    {children}
                </div>
                {dismissible && (
                    <button
                        onClick={handleDismiss}
                        className="absolute top-4 right-4 p-1 rounded-md hover:bg-black/10 dark:hover:bg-white/10 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                        aria-label="Dismiss alert"
                    >
                        <X className="h-4 w-4" />
                    </button>
                )}
            </div>
        )
    }
)
Alert.displayName = "Alert"

const AlertTitle = React.forwardRef<
    HTMLParagraphElement,
    React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
    <h5
        ref={ref}
        className={cn("mb-1 font-medium leading-none tracking-tight", className)}
        {...props}
    />
))
AlertTitle.displayName = "AlertTitle"

const AlertDescription = React.forwardRef<
    HTMLParagraphElement,
    React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
    <div
        ref={ref}
        className={cn("text-sm [&_p]:leading-relaxed", className)}
        {...props}
    />
))
AlertDescription.displayName = "AlertDescription"

export { Alert, AlertTitle, AlertDescription }
