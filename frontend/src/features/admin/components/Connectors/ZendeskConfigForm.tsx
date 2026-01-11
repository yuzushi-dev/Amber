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
    subdomain: z.string().min(1, 'Subdomain is required'),
    email: z.string().email('Invalid email address'),
    api_token: z.string().min(1, 'API Token is required'),
})

interface ZendeskConfigFormProps {
    onSuccess: () => void
}

export default function ZendeskConfigForm({ onSuccess }: ZendeskConfigFormProps) {
    const [submitting, setSubmitting] = useState(false)
    const [showToken, setShowToken] = useState(false)
    const [testError, setTestError] = useState<string | null>(null)

    const form = useForm<z.infer<typeof formSchema>>({
        resolver: zodResolver(formSchema),
        defaultValues: {
            subdomain: '',
            email: '',
            api_token: '',
        },
    })

    const onSubmit = async (values: z.infer<typeof formSchema>) => {
        try {
            setSubmitting(true)
            setTestError(null)
            await connectorsApi.authenticate('zendesk', values)
            toast.success('Successfully authenticated with Zendesk')
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
            connectorType="zendesk"
            title="Zendesk Configuration"
            description="Enter your Zendesk Help Center credentials to sync articles."
            errorMessage={testError ?? undefined}
        >
            <Form {...form}>
                <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                    <FormField
                        control={form.control}
                        name="subdomain"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>Subdomain</FormLabel>
                                <FormControl>
                                    <div className="flex items-center gap-0">
                                        <span className="px-3 py-2 text-sm text-muted-foreground bg-muted border border-r-0 rounded-l-md">
                                            https://
                                        </span>
                                        <Input
                                            placeholder="mycompany"
                                            className="rounded-none"
                                            {...field}
                                        />
                                        <span className="px-3 py-2 text-sm text-muted-foreground bg-muted border border-l-0 rounded-r-md">
                                            .zendesk.com
                                        </span>
                                    </div>
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                    <FormField
                        control={form.control}
                        name="email"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>Admin Email</FormLabel>
                                <FormControl>
                                    <Input placeholder="admin@example.com" {...field} />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                    <FormField
                        control={form.control}
                        name="api_token"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>API Token</FormLabel>
                                <FormControl>
                                    <div className="relative">
                                        <Input
                                            type={showToken ? 'text' : 'password'}
                                            placeholder="Enter your API token"
                                            className="pr-10"
                                            {...field}
                                        />
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                                            onClick={() => setShowToken(!showToken)}
                                        >
                                            {showToken ? (
                                                <EyeOff className="h-4 w-4 text-muted-foreground" />
                                            ) : (
                                                <Eye className="h-4 w-4 text-muted-foreground" />
                                            )}
                                            <span className="sr-only">
                                                {showToken ? 'Hide token' : 'Show token'}
                                            </span>
                                        </Button>
                                    </div>
                                </FormControl>
                                <FormDescription>
                                    Go to Admin Center → Apps and integrations → APIs → Zendesk API
                                </FormDescription>
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
