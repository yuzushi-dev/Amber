
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Button } from '@/components/ui/button';
import { useConnectors } from '@/lib/api-connectors';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import {
    Form,
    FormControl,
    FormDescription,
    FormField,
    FormItem,
    FormLabel,
    FormMessage,
} from '@/components/ui/form';

const formSchema = z.object({
    base_url: z.string().url("Must be a valid URL (e.g. https://domain.atlassian.net/wiki)"),
    email: z.string().email("Invalid email address"),
    api_token: z.string().min(1, "API Token is required"),
});

interface ConfluenceConfigFormProps {
    onSuccess: () => void;
}

export function ConfluenceConfigForm({ onSuccess }: ConfluenceConfigFormProps) {
    const { authenticate } = useConnectors();
    const form = useForm<z.infer<typeof formSchema>>({
        resolver: zodResolver(formSchema),
        defaultValues: {
            base_url: '',
            email: '',
            api_token: '',
        },
    });

    async function onSubmit(values: z.infer<typeof formSchema>) {
        try {
            await authenticate.mutateAsync({
                type: 'confluence',
                credentials: values,
            });
            toast.success('Successfully connected to Confluence');
            onSuccess();
        } catch (error) {
            // Error handled by mutation
            console.error(error);
        }
    }

    return (
        <div className="max-w-md space-y-6">
            <div className="space-y-2">
                <h3 className="text-lg font-medium">Confluence Configuration</h3>
                <p className="text-sm text-muted-foreground">
                    Connect your Atlassian Confluence Cloud instance.
                    You need your email and an API Token.
                </p>
            </div>

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
                                    <Input type="password" placeholder="Atlassian API Token" {...field} />
                                </FormControl>
                                <FormDescription>
                                    Generate one at <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" rel="noopener noreferrer" className="underline">id.atlassian.com</a>
                                </FormDescription>
                                <FormMessage />
                            </FormItem>
                        )}
                    />

                    <Button type="submit" disabled={authenticate.isPending}>
                        {authenticate.isPending ? 'Connecting...' : 'Connect Confluence'}
                    </Button>
                </form>
            </Form>
        </div>
    );
}
