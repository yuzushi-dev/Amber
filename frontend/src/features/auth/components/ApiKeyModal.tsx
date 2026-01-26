import { useState } from 'react'
import { useAuth, maskApiKey } from '../hooks/useAuth'
import { KeyRound, Eye, EyeOff, Loader2, AlertCircle, Crown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
} from '@/components/ui/dialog'

interface ApiKeyModalProps {
    onSuccess?: () => void
    isOpen?: boolean
    onClose?: () => void
    mode?: 'initial' | 'change'
}

export default function ApiKeyModal({
    onSuccess,
    isOpen = true,
    onClose,
    mode = 'initial'
}: ApiKeyModalProps) {
    const { setApiKey, isValidating, error, apiKey, isSuperAdmin } = useAuth()
    const [inputKey, setInputKey] = useState('')
    const [showKey, setShowKey] = useState(false)

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        const success = await setApiKey(inputKey)
        if (success) {
            setInputKey('')
            onSuccess?.()
            onClose?.()
        }
    }

    if (!isOpen) return null

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose?.()}>
            <DialogContent className="sm:max-w-md p-0 gap-0 overflow-hidden border-border shadow-2xl">
                <DialogHeader className="p-6 border-b border-white/5 bg-white/[0.02]">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                            <KeyRound className="w-5 h-5 text-primary" />
                        </div>
                        <div>
                            <DialogTitle className="text-xl font-display tracking-tight">
                                {mode === 'initial' ? 'Welcome to Amber' : 'Change API Key'}
                            </DialogTitle>
                            <DialogDescription className="text-sm text-muted-foreground mt-0.5">
                                {mode === 'initial'
                                    ? 'Enter your API key to get started'
                                    : 'Enter a new API key'
                                }
                            </DialogDescription>
                        </div>
                    </div>
                </DialogHeader>

                <div className="p-6">
                    <form onSubmit={handleSubmit} className="space-y-4">
                        {mode === 'change' && apiKey && (
                            <div className="p-3 bg-muted/50 rounded-lg text-sm border border-white/5">
                                <span className="text-muted-foreground">Current key: </span>
                                <code className="font-mono">{maskApiKey(apiKey)}</code>
                                {isSuperAdmin && (
                                    <Crown className="inline-block ml-2 w-3.5 h-3.5 text-amber-500" />
                                )}
                            </div>
                        )}

                        <div className="space-y-2">
                            <label htmlFor="api-key" className="text-sm font-medium">
                                API Key
                            </label>
                            <div className="relative">
                                <Input
                                    id="api-key"
                                    type={showKey ? 'text' : 'password'}
                                    value={inputKey}
                                    onChange={(e) => setInputKey(e.target.value)}
                                    placeholder="Enter your API key..."
                                    className="px-4 py-3 pr-12 bg-background focus-visible:ring-offset-1"
                                    autoFocus
                                    disabled={isValidating}
                                />
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => setShowKey(!showKey)}
                                    className="absolute right-1 top-1/2 -translate-y-1/2 h-8 w-8 hover:bg-muted"
                                >
                                    {showKey ? (
                                        <EyeOff className="w-4 h-4 text-muted-foreground" />
                                    ) : (
                                        <Eye className="w-4 h-4 text-muted-foreground" />
                                    )}
                                </Button>
                            </div>
                        </div>

                        {error && (
                            <div className="flex items-center gap-2 p-3 bg-destructive/10 text-destructive rounded-lg text-sm animate-in slide-in-from-top-2">
                                <AlertCircle className="w-4 h-4 shrink-0" />
                                <span>{error}</span>
                            </div>
                        )}

                        <div className="flex gap-3 pt-2">
                            {mode === 'change' && onClose && (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    onClick={onClose}
                                    className="flex-1 hover:bg-muted/50"
                                    disabled={isValidating}
                                >
                                    Cancel
                                </Button>
                            )}
                            <Button
                                type="submit"
                                disabled={!inputKey.trim() || isValidating}
                                className="flex-1 gap-2 shadow-lg shadow-primary/20"
                            >
                                {isValidating ? (
                                    <>
                                        <Loader2 className="w-4 h-4 animate-spin" />
                                        Validating...
                                    </>
                                ) : (
                                    'Connect'
                                )}
                            </Button>
                        </div>

                        {mode === 'initial' && (
                            <p className="text-xs text-center text-muted-foreground pt-2">
                                Your API key is stored locally and never sent to external servers.
                            </p>
                        )}
                    </form>
                </div>
            </DialogContent>
        </Dialog>
    )
}
