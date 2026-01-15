/**
 * Dialog Component
 * ================
 *
 * Reusable modal/dialog component with consistent styling across the app.
 * Based on the Amber design system for backdrop, container, and spacing.
 */

import * as React from "react"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"

interface DialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    children: React.ReactNode
}

interface DialogContentProps extends React.HTMLAttributes<HTMLDivElement> {
    children: React.ReactNode
    className?: string
}

interface DialogHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
    children: React.ReactNode
    className?: string
}

interface DialogFooterProps extends React.HTMLAttributes<HTMLDivElement> {
    children: React.ReactNode
    className?: string
}

interface DialogTitleProps extends React.HTMLAttributes<HTMLHeadingElement> {
    children: React.ReactNode
    className?: string
}

interface DialogDescriptionProps extends React.HTMLAttributes<HTMLParagraphElement> {
    children: React.ReactNode
    className?: string
}

/**
 * Dialog Root - Controls open/close state
 */
export function Dialog({ open, onOpenChange, children }: DialogProps) {
    React.useEffect(() => {
        if (open) {
            document.body.style.overflow = 'hidden'
        } else {
            document.body.style.overflow = 'unset'
        }
        return () => {
            document.body.style.overflow = 'unset'
        }
    }, [open])

    if (!open) return null

    return (
        // Premium Glass Dialog
        <>
            {/* Backdrop */}
            <div
                className="fixed inset-0 z-50 bg-background/80 backdrop-blur-md animate-in fade-in duration-300 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
                onClick={() => onOpenChange(false)}
                aria-hidden="true"
            />
            {/* Dialog Container */}
            <div
                className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
                onClick={() => onOpenChange(false)}
            >
                {children}
            </div>
        </>
    )
}

/**
 * DialogContent - Main content container
 */
export function DialogContent({ children, className, ...props }: DialogContentProps) {
    return (
        <div
            className={cn(
                "bg-black/80 backdrop-blur-xl border border-white/10 shadow-2xl rounded-xl w-full max-w-lg overflow-hidden",
                "animate-in fade-in zoom-in-95 slide-in-from-bottom-2 duration-300",
                className
            )}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            {...props}
        >
            {children}
        </div>
    )
}

/**
 * DialogHeader - Header section with optional close button
 */
export function DialogHeader({ children, className, ...props }: DialogHeaderProps) {
    return (
        <div
            className={cn(
                "p-6 border-b bg-muted/30",
                className
            )}
            {...props}
        >
            {children}
        </div>
    )
}

/**
 * DialogTitle - Title heading
 */
export function DialogTitle({ children, className, ...props }: DialogTitleProps) {
    return (
        <h2
            className={cn(
                "text-lg font-semibold",
                className
            )}
            {...props}
        >
            {children}
        </h2>
    )
}

/**
 * DialogDescription - Subtitle/description text
 */
export function DialogDescription({ children, className, ...props }: DialogDescriptionProps) {
    return (
        <p
            className={cn(
                "text-sm text-muted-foreground mt-1",
                className
            )}
            {...props}
        >
            {children}
        </p>
    )
}

/**
 * DialogBody - Main content area with scrolling
 */
export function DialogBody({ children, className, ...props }: DialogContentProps) {
    return (
        <div
            className={cn(
                "p-6 overflow-y-auto max-h-[60vh]",
                className
            )}
            {...props}
        >
            {children}
        </div>
    )
}

/**
 * DialogFooter - Footer section for actions
 */
export function DialogFooter({ children, className, ...props }: DialogFooterProps) {
    return (
        <div
            className={cn(
                "p-6 border-t bg-muted/30 flex gap-3 justify-end",
                className
            )}
            {...props}
        >
            {children}
        </div>
    )
}

/**
 * DialogClose - Close button (optional, can use custom buttons)
 */
export function DialogClose({ onClose, className }: { onClose: () => void; className?: string }) {
    return (
        <button
            onClick={onClose}
            className={cn(
                "absolute top-4 right-4 p-2 hover:bg-muted rounded-full transition-colors",
                "focus:outline-none focus:ring-2 focus:ring-primary",
                className
            )}
            aria-label="Close dialog"
        >
            <X className="w-5 h-5" />
        </button>
    )
}

/**
 * Simple Confirm Dialog - Pre-composed confirmation dialog
 */
interface ConfirmDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    title: string
    description: string
    confirmText?: string
    cancelText?: string
    onConfirm: () => void
    variant?: 'default' | 'destructive'
    loading?: boolean
}

export function ConfirmDialog({
    open,
    onOpenChange,
    title,
    description,
    confirmText = "Confirm",
    cancelText = "Cancel",
    onConfirm,
    variant = 'default',
    loading = false
}: ConfirmDialogProps) {
    const handleConfirm = () => {
        onConfirm()
        if (!loading) {
            onOpenChange(false)
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-md">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <p className="text-muted-foreground">{description}</p>
                </DialogBody>
                <DialogFooter>
                    <button
                        onClick={() => onOpenChange(false)}
                        disabled={loading}
                        className="px-4 py-2 border rounded-md hover:bg-muted transition-colors disabled:opacity-50"
                    >
                        {cancelText}
                    </button>
                    <button
                        onClick={handleConfirm}
                        disabled={loading}
                        className={cn(
                            "px-4 py-2 rounded-md transition-colors disabled:opacity-50",
                            variant === 'destructive'
                                ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                : "bg-primary text-primary-foreground hover:bg-primary/90"
                        )}
                    >
                        {loading ? 'Processing...' : confirmText}
                    </button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
