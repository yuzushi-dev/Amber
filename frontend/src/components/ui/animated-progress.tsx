/**
 * AnimatedProgress Component
 * ==========================
 * 
 * Smooth animated progress bar using framer-motion.
 * Supports stages for displaying current operation label.
 */

import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

export interface ProgressStage {
    label: string
    threshold: number
}

interface AnimatedProgressProps {
    /** Progress value from 0-100 */
    value: number
    /** Optional stages to display labels based on progress thresholds */
    stages?: ProgressStage[]
    /** Whether to show the percentage value */
    showPercentage?: boolean
    /** Additional class names for the container */
    className?: string
    /** Size variant */
    size?: 'sm' | 'md' | 'lg'
}

export function AnimatedProgress({
    value,
    stages,
    showPercentage = true,
    className,
    size = 'md',
}: AnimatedProgressProps) {
    // Clamp value between 0-100
    const clampedValue = Math.min(100, Math.max(0, value))

    // Determine current stage label
    const currentStage = stages?.reduce((current, stage) => {
        if (clampedValue >= stage.threshold) {
            return stage
        }
        return current
    }, stages[0])

    const sizeClasses = {
        sm: 'h-1.5',
        md: 'h-2',
        lg: 'h-3',
    }

    return (
        <div className={cn('w-full space-y-1.5', className)}>
            {/* Stage label and percentage */}
            {(currentStage || showPercentage) && (
                <div className="flex items-center justify-between text-sm">
                    {currentStage && (
                        <motion.span
                            key={currentStage.label}
                            initial={{ opacity: 0, y: -5 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="text-foreground/90 font-medium"
                        >
                            {currentStage.label}
                        </motion.span>
                    )}
                    {showPercentage && (
                        <span className="text-foreground/90 font-mono text-xs">
                            {Math.round(clampedValue)}%
                        </span>
                    )}
                </div>
            )}

            {/* Progress bar track */}
            <div
                className={cn(
                    'w-full bg-muted rounded-full overflow-hidden',
                    sizeClasses[size]
                )}
            >
                {/* Animated fill */}
                <motion.div
                    className={cn(
                        'h-full rounded-full',
                        'bg-gradient-to-r from-primary to-primary/80',
                        clampedValue > 0 && 'shadow-glow-sm'
                    )}
                    initial={{ width: 0 }}
                    animate={{ width: `${clampedValue}%` }}
                    transition={{
                        type: 'spring',
                        damping: 20,
                        stiffness: 100,
                    }}
                />
            </div>
        </div>
    )
}

export default AnimatedProgress
