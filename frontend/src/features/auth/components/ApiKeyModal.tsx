import { useState } from 'react'
import { useAuth, maskApiKey } from '../hooks/useAuth'
import { KeyRound, Eye, EyeOff, Loader2, AlertCircle, Crown } from 'lucide-react'

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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
            <div className="bg-card border shadow-2xl rounded-xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-300">
                <header className="p-6 border-b bg-muted/30">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                            <KeyRound className="w-5 h-5 text-primary" />
                        </div>
                        <div>
                            <h2 className="text-xl font-bold">
                                {mode === 'initial' ? 'Welcome to Amber' : 'Change API Key'}
                            </h2>
                            <p className="text-sm text-muted-foreground">
                                {mode === 'initial'
                                    ? 'Enter your API key to get started'
                                    : 'Enter a new API key'
                                }
                            </p>
                        </div>
                    </div>
                </header>

                <form onSubmit={handleSubmit} className="p-6 space-y-4">
                    {mode === 'change' && apiKey && (
                        <div className="p-3 bg-muted/50 rounded-lg text-sm">
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
                            <input
                                id="api-key"
                                type={showKey ? 'text' : 'password'}
                                value={inputKey}
                                onChange={(e) => setInputKey(e.target.value)}
                                placeholder="Enter your API key..."
                                className="w-full px-4 py-3 pr-12 bg-background border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1"
                                autoFocus
                                disabled={isValidating}
                            />
                            <button
                                type="button"
                                onClick={() => setShowKey(!showKey)}
                                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 hover:bg-muted rounded"
                            >
                                {showKey ? (
                                    <EyeOff className="w-4 h-4 text-muted-foreground" />
                                ) : (
                                    <Eye className="w-4 h-4 text-muted-foreground" />
                                )}
                            </button>
                        </div>
                    </div>

                    {error && (
                        <div className="flex items-center gap-2 p-3 bg-destructive/10 text-destructive rounded-lg text-sm">
                            <AlertCircle className="w-4 h-4 shrink-0" />
                            <span>{error}</span>
                        </div>
                    )}

                    <div className="flex gap-3 pt-2">
                        {mode === 'change' && onClose && (
                            <button
                                type="button"
                                onClick={onClose}
                                className="flex-1 px-4 py-3 border rounded-lg hover:bg-muted transition-colors"
                                disabled={isValidating}
                            >
                                Cancel
                            </button>
                        )}
                        <button
                            type="submit"
                            disabled={!inputKey.trim() || isValidating}
                            className="flex-1 px-4 py-3 bg-primary text-primary-foreground rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                        >
                            {isValidating ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Validating...
                                </>
                            ) : (
                                'Connect'
                            )}
                        </button>
                    </div>

                    {mode === 'initial' && (
                        <p className="text-xs text-center text-muted-foreground pt-2">
                            Your API key is stored locally and never sent to external servers.
                        </p>
                    )}
                </form>
            </div>
        </div>
    )
}
