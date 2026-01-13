
import * as React from "react"
import * as SliderPrimitive from "@radix-ui/react-slider"

import { cn } from "@/lib/utils"

const Slider = React.forwardRef<
    React.ElementRef<typeof SliderPrimitive.Root>,
    React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root> & {
        showValue?: boolean
        formatLabel?: (value: number) => string
    }
>(({ className, showValue = false, formatLabel, ...props }, ref) => {
    const [showTooltip, setShowTooltip] = React.useState(false)

    // Internal state to track value for the tooltip if controlled value isn't enough
    // but Radix Slider is controlled or uncontrolled. 
    // We can just rely on props.value or props.defaultValue if we want, 
    // but for the tooltip to track drag, we might need access to the current value.
    // Ideally we use the value passed in. 

    // If uncontrolled, we can't easily show the value without internal state or getting it from onValueChange.
    // For this use case, we are likely using it controlled or can wrap it.

    // Actually, Radix exposes the value via context to the thumb, but we can't access it easily outside.
    // Let's assume controlled for now since we use it in TuningPage with state.

    const value = props.value || props.defaultValue || [0]
    const val = Array.isArray(value) ? value[0] : value

    return (
        <SliderPrimitive.Root
            ref={ref}
            className={cn(
                "relative flex w-full touch-none select-none items-center",
                className
            )}
            onPointerDown={() => setShowTooltip(true)}
            onPointerUp={() => setShowTooltip(false)}
            onPointerLeave={() => setShowTooltip(false)}
            {...props}
        >
            <SliderPrimitive.Track className="relative h-2 w-full grow overflow-hidden rounded-full bg-secondary">
                <SliderPrimitive.Range className="absolute h-full bg-primary" />
            </SliderPrimitive.Track>
            <SliderPrimitive.Thumb
                className="block h-5 w-5 rounded-full border-2 border-primary bg-background ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 hover:bg-accent hover:border-accent-foreground/50"
            >
                {(showValue || showTooltip) && (
                    <div
                        className={cn(
                            "absolute -top-8 left-1/2 -translate-x-1/2 px-2 py-1 rounded bg-popover text-popover-foreground text-xs font-medium shadow-md border animate-in fade-in zoom-in duration-200",
                            !showTooltip && "hidden" // Only show on drag/interaction if we want that behavior
                        )}
                    >
                        {formatLabel ? formatLabel(val) : val}
                    </div>
                )}
            </SliderPrimitive.Thumb>
        </SliderPrimitive.Root>
    )
})
Slider.displayName = SliderPrimitive.Root.displayName

export { Slider }
