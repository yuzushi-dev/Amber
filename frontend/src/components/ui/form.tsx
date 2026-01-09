import * as React from "react"
import { useFormContext, Controller, ControllerProps, FieldPath, FieldValues, FormProvider } from "react-hook-form"
import { cn } from "@/lib/utils"

const Form = FormProvider

type FormItemContextValue = {
    id: string
}

const FormItemContext = React.createContext<FormItemContextValue>(
    {} as FormItemContextValue
)

type FormFieldContextValue = {
    name: string
}

const FormFieldContext = React.createContext<FormFieldContextValue>(
    {} as FormFieldContextValue
)

const FormItem = React.forwardRef<
    HTMLDivElement,
    React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => {
    const id = React.useId()

    return (
        <FormItemContext.Provider value={{ id }}>
            <div ref={ref} className={cn("space-y-2", className)} {...props} />
        </FormItemContext.Provider>
    )
})
FormItem.displayName = "FormItem"

const FormLabel = React.forwardRef<
    HTMLLabelElement,
    React.LabelHTMLAttributes<HTMLLabelElement>
>(({ className, ...props }, ref) => {
    const { id } = React.useContext(FormItemContext)
    const { name } = React.useContext(FormFieldContext)
    const { formState: { errors } } = useFormContext()
    const error = errors[name]

    return (
        <label
            ref={ref}
            htmlFor={id}
            className={cn(
                "text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
                error && "text-destructive",
                className
            )}
            {...props}
        />
    )
})
FormLabel.displayName = "FormLabel"

const FormControl = React.forwardRef<
    HTMLDivElement,
    React.HTMLAttributes<HTMLDivElement>
>(({ ...props }, ref) => {
    const { id } = React.useContext(FormItemContext)
    const { name } = React.useContext(FormFieldContext)
    const { formState: { errors } } = useFormContext()
    const error = errors[name]

    return (
        <div
            ref={ref}
            id={id}
            aria-invalid={!!error}
            aria-describedby={!error ? undefined : `${id}-form-item-message`}
            {...props}
        />
    )
})
FormControl.displayName = "FormControl"

const FormDescription = React.forwardRef<
    HTMLParagraphElement,
    React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => {
    return (
        <p
            ref={ref}
            className={cn("text-sm text-muted-foreground", className)}
            {...props}
        />
    )
})
FormDescription.displayName = "FormDescription"

const FormMessage = React.forwardRef<
    HTMLParagraphElement,
    React.HTMLAttributes<HTMLParagraphElement>
>(({ className, children, ...props }, ref) => {
    const { name } = React.useContext(FormFieldContext)
    const { formState: { errors } } = useFormContext()
    const error = errors[name]

    // If no error, and no children, render nothing
    if (!error && !children) {
        return null
    }

    const message = error ? String(error.message) : children

    return (
        <p
            ref={ref}
            className={cn("text-sm font-medium text-destructive", className)}
            {...props}
        >
            {message}
        </p>
    )
})
FormMessage.displayName = "FormMessage"

const FormField = <
    TFieldValues extends FieldValues = FieldValues,
    TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>
>({
    ...props
}: ControllerProps<TFieldValues, TName>) => {
    return (
        <FormFieldContext.Provider value={{ name: props.name }}>
            <Controller {...props} />
        </FormFieldContext.Provider>
    )
}

export {
    Form,
    FormItem,
    FormLabel,
    FormControl,
    FormDescription,
    FormMessage,
    FormField,
}
