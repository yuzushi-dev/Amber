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
    host: z.string().url('Must be a valid URL'),
    email: z.string().email('Invalid email address'),
    password: z.string().min(1, 'Password is required'),
})

interface CarbonioConfigFormProps {
    onSuccess: () => void
}

export default function CarbonioConfigForm({ onSuccess }: CarbonioConfigFormProps) {
    const [submitting, setSubmitting] = useState(false)

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
            await connectorsApi.authenticate('carbonio', values)
            toast.success('Successfully authenticated with Carbonio')
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
                <CardTitle>Carbonio Configuration</CardTitle>
                <CardDescription>
                    Connect to your Zextras Carbonio instance via SOAP/JSON API.
                </CardDescription>
            </CardHeader>
            <CardContent>
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
                                        <Input type="password" placeholder="••••••••" {...field} />
                                    </FormControl>
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
