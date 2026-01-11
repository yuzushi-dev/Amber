import { ReactNode } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, AlertTriangle, Loader2, Unplug } from 'lucide-react'
import { cn } from '@/lib/utils'

interface BaseConfigFormProps {
    /** Connector type for display */
    connectorType: string
    /** Form title */
    title: string
    /** Form description */
    description: string
    /** Whether the connector is currently authenticated */
    isAuthenticated?: boolean
    /** Error message if connection failed */
    errorMessage?: string
    /** Whether a test connection is in progress */
    isTesting?: boolean
    /** Handler for test connection button */
    onTestConnection?: () => void
    /** Handler for disconnect button */
    onDisconnect?: () => void
    /** Whether disconnect is in progress */
    isDisconnecting?: boolean
    /** The form content */
    children: ReactNode
}

/**
 * Standardized wrapper for connector configuration forms.
 * Provides consistent layout, connection status, and test/disconnect functionality.
 */
export function BaseConfigForm({
    title,
    description,
    isAuthenticated,
    errorMessage,
    isTesting,
    onTestConnection,
    onDisconnect,
    isDisconnecting,
    children,
}: BaseConfigFormProps) {
    return (
        <Card className="relative overflow-hidden">
            {/* Connection status indicator bar */}
            <div
                className={cn(
                    'absolute top-0 left-0 right-0 h-1 transition-colors',
                    isAuthenticated ? 'bg-green-500' : 'bg-muted',
                    errorMessage && 'bg-destructive'
                )}
            />

            <CardHeader className="pt-6">
                <div className="flex items-start justify-between">
                    <div>
                        <CardTitle className="text-xl">{title}</CardTitle>
                        <CardDescription className="mt-1.5">
                            {description}
                        </CardDescription>
                    </div>
                    {isAuthenticated && (
                        <Badge className="bg-green-600/90 text-white">
                            <CheckCircle2 className="w-3 h-3 mr-1" />
                            Connected
                        </Badge>
                    )}
                </div>

                {/* Error message */}
                {errorMessage && (
                    <div className="mt-4 p-3 bg-destructive/10 border border-destructive/20 rounded-md flex items-start gap-2 text-sm text-destructive">
                        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                        <span>{errorMessage}</span>
                    </div>
                )}
            </CardHeader>

            <CardContent className="space-y-6">
                {/* Form fields */}
                {children}

                {/* Action buttons */}
                <div className="flex items-center gap-3 pt-2">
                    {onTestConnection && (
                        <Button
                            type="button"
                            variant="outline"
                            onClick={onTestConnection}
                            disabled={isTesting}
                        >
                            {isTesting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                            Test Connection
                        </Button>
                    )}

                    {isAuthenticated && onDisconnect && (
                        <Button
                            type="button"
                            variant="ghost"
                            onClick={onDisconnect}
                            disabled={isDisconnecting}
                            className="text-muted-foreground hover:text-destructive"
                        >
                            {isDisconnecting ? (
                                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                            ) : (
                                <Unplug className="w-4 h-4 mr-2" />
                            )}
                            Disconnect
                        </Button>
                    )}
                </div>
            </CardContent>
        </Card>
    )
}

export default BaseConfigForm
