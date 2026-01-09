import * as React from "react"
import { cn } from "@/lib/utils"

export interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {
    onCheckedChange?: (checked: boolean) => void
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
    ({ className, onCheckedChange, onChange, ...props }, ref) => (
        <div className="relative flex items-center">
            <input
                type="checkbox"
                ref={ref}
                onChange={(e) => {
                    onChange?.(e)
                    onCheckedChange?.(e.target.checked)
                }}
                className={cn(
                    "peer h-4 w-4 shrink-0 rounded-sm border border-primary ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground accent-primary",
                    className
                )}
                {...props}
            />
        </div>
    )
)
Checkbox.displayName = "Checkbox"

export { Checkbox }
