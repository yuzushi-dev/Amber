import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import * as z from 'zod'
import { Button } from '@/components/ui/button'
import { useConnectors } from '@/lib/api-connectors'
import { toast } from 'sonner'
import { Input } from '@/components/ui/input'
import {
    Form,
    FormControl,
    FormDescription,
    FormField,
    FormItem,
    FormLabel,
    FormMessage,
} from '@/components/ui/form'
import { BaseConfigForm } from './BaseConfigForm'
import { Loader2, Eye, EyeOff, ExternalLink } from 'lucide-react'

const formSchema = z.object({
    base_url: z.string().url("Must be a valid URL (e.g. https://domain.atlassian.net/wiki)"),
    email: z.string().email("Invalid email address"),
    api_token: z.string().min(1, "API Token is required"),
})

interface ConfluenceConfigFormProps {
    onSuccess: () => void
}

export function ConfluenceConfigForm({ onSuccess }: ConfluenceConfigFormProps) {
    const { authenticate } = useConnectors()
    const [showToken, setShowToken] = useState(false)
    const [testError, setTestError] = useState<string | null>(null)

    const form = useForm<z.infer<typeof formSchema>>({
        resolver: zodResolver(formSchema),
        defaultValues: {
            base_url: '',
            email: '',
            api_token: '',
        },
    })

    async function onSubmit(values: z.infer<typeof formSchema>) {
        try {
            setTestError(null)
            await authenticate.mutateAsync({
                type: 'confluence',
                credentials: values,
            })
            toast.success('Successfully connected to Confluence')
            onSuccess()
        } catch (error: any) {
            const errorMsg = error.response?.data?.detail || 'Authentication failed'
            setTestError(errorMsg)
            console.error(error)
        }
    }

    return (
        <BaseConfigForm
            connectorType="confluence"
            title="Confluence Configuration"
            description="Connect your Atlassian Confluence Cloud instance to sync pages."
            errorMessage={testError ?? undefined}
        >
            <Form {...form}>
                <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                    <FormField
                        control={form.control}
                        name="base_url"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>Confluence Base URL</FormLabel>
                                <FormControl>
                                    <Input placeholder="https://your-domain.atlassian.net/wiki" {...field} />
                                </FormControl>
                                <FormDescription>
                                    The full URL to your Confluence instance (usually ends with /wiki for Cloud).
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
                                <FormLabel>Email Address</FormLabel>
                                <FormControl>
                                    <Input placeholder="user@example.com" {...field} />
                                </FormControl>
                                <FormDescription>
                                    The email address you use to log in to Atlassian.
                                </FormDescription>
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
                                            placeholder="Enter your Atlassian API Token"
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
                                    <a
                                        href="https://id.atlassian.com/manage-profile/security/api-tokens"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="inline-flex items-center gap-1 text-primary hover:underline"
                                    >
                                        Generate one at id.atlassian.com
                                        <ExternalLink className="w-3 h-3" />
                                    </a>
                                </FormDescription>
                                <FormMessage />
                            </FormItem>
                        )}
                    />

                    <div className="pt-2">
                        <Button type="submit" disabled={authenticate.isPending}>
                            {authenticate.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                            {authenticate.isPending ? 'Connecting...' : 'Connect Confluence'}
                        </Button>
                    </div>
                </form>
            </Form>
        </BaseConfigForm>
    )
}

export default ConfluenceConfigForm
