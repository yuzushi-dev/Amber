import * as React from "react"
import { cn } from "@/lib/utils"

type RadioCardContextValue = {
    name: string
    value: string
    onValueChange: (value: string) => void
    disabled?: boolean
}

const RadioCardContext = React.createContext<RadioCardContextValue | null>(null)

interface RadioCardGroupProps extends React.HTMLAttributes<HTMLFieldSetElement> {
    value: string
    onValueChange: (value: string) => void
    name?: string
    label?: React.ReactNode
    ariaLabel?: string
    ariaLabelledby?: string
    itemsClassName?: string
    disabled?: boolean
}

function RadioCardGroup({
    value,
    onValueChange,
    name,
    label,
    ariaLabel,
    ariaLabelledby,
    itemsClassName,
    disabled,
    className,
    children,
    ...props
}: RadioCardGroupProps) {
    const generatedName = React.useId()
    const groupName = name ?? generatedName

    return (
        <RadioCardContext.Provider value={{ name: groupName, value, onValueChange, disabled }}>
            <fieldset
                className={cn("border-0 p-0 m-0 space-y-2", className)}
                aria-label={ariaLabel}
                aria-labelledby={ariaLabelledby}
                disabled={disabled}
                {...props}
            >
                {label && (
                    <legend className="text-base font-medium text-foreground">
                        {label}
                    </legend>
                )}
                <div className={cn("space-y-4", itemsClassName)}>
                    {children}
                </div>
            </fieldset>
        </RadioCardContext.Provider>
    )
}

interface RadioCardItemProps {
    value: string
    label: React.ReactNode
    description?: React.ReactNode
    icon?: React.ReactNode
    badge?: React.ReactNode
    className?: string
    disabled?: boolean
    id?: string
}

function RadioCardItem({
    value,
    label,
    description,
    icon,
    badge,
    className,
    disabled,
    id
}: RadioCardItemProps) {
    const context = React.useContext(RadioCardContext)

    if (!context) {
        throw new Error("RadioCardItem must be used within a RadioCardGroup")
    }

    const generatedId = React.useId()
    const isChecked = context.value === value
    const inputId = id ?? generatedId
    const isDisabled = disabled ?? context.disabled

    return (
        <label className="block">
            <input
                id={inputId}
                type="radio"
                name={context.name}
                value={value}
                checked={isChecked}
                onChange={() => context.onValueChange(value)}
                disabled={isDisabled}
                className="sr-only peer"
            />
            <div
                className={cn(
                    "flex items-start gap-3 rounded-lg border border-border p-4 transition-colors cursor-pointer",
                    "hover:bg-muted/50",
                    "peer-checked:border-primary peer-checked:bg-primary/5",
                    "peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-background",
                    "peer-disabled:cursor-not-allowed peer-disabled:opacity-60",
                    className
                )}
            >
                <div className="mt-1 flex h-4 w-4 items-center justify-center rounded-full border-2 border-muted-foreground/50 peer-checked:border-primary">
                    <span className="h-2 w-2 rounded-full bg-primary opacity-0 transition-opacity peer-checked:opacity-100" />
                </div>
                <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-2 text-base">
                        {icon && <span className="shrink-0">{icon}</span>}
                        <div className="font-medium text-foreground">{label}</div>
                        {badge}
                    </div>
                    {description && (
                        <div className="text-sm text-muted-foreground">
                            {description}
                        </div>
                    )}
                </div>
            </div>
        </label>
    )
}

export { RadioCardGroup, RadioCardItem }
