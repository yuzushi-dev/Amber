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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

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
            await connectorsApi.authenticate('zendesk', values)
            toast.success('Successfully authenticated with Zendesk')
            onSuccess()
        } catch (err: any) {
            console.error(err)
            toast.error(err.response?.data?.detail || 'Authentication failed')
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <Card>
            <CardHeader>
                <CardTitle>Zendesk Configuration</CardTitle>
                <CardDescription>
                    Enter your Zendesk Help Center credentials.
                    You can generate an API token in validation settings.
                </CardDescription>
            </CardHeader>
            <CardContent>
                <Form {...form}>
                    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                        <FormField
                            control={form.control}
                            name="subdomain"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel>Subdomain</FormLabel>
                                    <FormControl>
                                        <div className="flex items-center gap-2">
                                            <span className="text-muted-foreground">https://</span>
                                            <Input placeholder="mycompany" {...field} />
                                            <span className="text-muted-foreground">.zendesk.com</span>
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
                                        <Input type="password" placeholder="Ex: e6c..." {...field} />
                                    </FormControl>
                                    <FormDescription>
                                        Go to Admin Center {'>'} Apps and integrations {'>'} APIs {'>'} Zendesk API
                                    </FormDescription>
                                    <FormMessage />
                                </FormItem>
                            )}
                        />
                        <Button type="submit" disabled={submitting}>
                            {submitting ? 'Verifying...' : 'Save Configuration'}
                        </Button>
                    </form>
                </Form>
            </CardContent>
        </Card>
    )
}
