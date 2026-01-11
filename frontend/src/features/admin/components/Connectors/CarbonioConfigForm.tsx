import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import * as z from 'zod'
import { connectorsApi } from '@/lib/api-connectors'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
    Form,
    FormControl,
    FormDescription,
    FormField,
    FormItem,
    FormLabel,
    FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { BaseConfigForm } from './BaseConfigForm'
import { Loader2, Eye, EyeOff } from 'lucide-react'

const formSchema = z.object({
    host: z.string().url('Must be a valid URL'),
    email: z.string().email('Invalid email address'),
    password: z.string().min(1, 'Password is required'),
})

interface CarbonioConfigFormProps {
    onSuccess: () => void
}

export default function CarbonioConfigForm({ onSuccess }: CarbonioConfigFormProps) {
    const [submitting, setSubmitting] = useState(false)
    const [showPassword, setShowPassword] = useState(false)
    const [testError, setTestError] = useState<string | null>(null)

    const form = useForm<z.infer<typeof formSchema>>({
        resolver: zodResolver(formSchema),
        defaultValues: {
            host: '',
            email: '',
            password: '',
        },
    })

    const onSubmit = async (values: z.infer<typeof formSchema>) => {
        try {
            setSubmitting(true)
            setTestError(null)
            await connectorsApi.authenticate('carbonio', values)
            toast.success('Successfully authenticated with Carbonio')
            onSuccess()
        } catch (err: any) {
            console.error(err)
            const errorMsg = err.response?.data?.detail || 'Authentication failed'
            setTestError(errorMsg)
            toast.error(errorMsg)
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <BaseConfigForm
            connectorType="carbonio"
            title="Carbonio Configuration"
            description="Connect to your Zextras Carbonio instance via SOAP/JSON API."
            errorMessage={testError ?? undefined}
        >
            <Form {...form}>
                <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                    <FormField
                        control={form.control}
                        name="host"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>Host URL</FormLabel>
                                <FormControl>
                                    <Input placeholder="https://mail.company.com" {...field} />
                                </FormControl>
                                <FormDescription>
                                    The URL of your Carbonio webmail/API.
                                </FormDescription>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                    <FormField
                        control={form.control}
                        name="email"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>Email</FormLabel>
                                <FormControl>
                                    <Input placeholder="user@company.com" {...field} />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                    <FormField
                        control={form.control}
                        name="password"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>Password</FormLabel>
                                <FormControl>
                                    <div className="relative">
                                        <Input
                                            type={showPassword ? 'text' : 'password'}
                                            placeholder="Enter your password"
                                            className="pr-10"
                                            {...field}
                                        />
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                                            onClick={() => setShowPassword(!showPassword)}
                                        >
                                            {showPassword ? (
                                                <EyeOff className="h-4 w-4 text-muted-foreground" />
                                            ) : (
                                                <Eye className="h-4 w-4 text-muted-foreground" />
                                            )}
                                            <span className="sr-only">
                                                {showPassword ? 'Hide password' : 'Show password'}
                                            </span>
                                        </Button>
                                    </div>
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                    <div className="pt-2">
                        <Button type="submit" disabled={submitting}>
                            {submitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                            {submitting ? 'Verifying...' : 'Save Configuration'}
                        </Button>
                    </div>
                </form>
            </Form>
        </BaseConfigForm>
    )
}
