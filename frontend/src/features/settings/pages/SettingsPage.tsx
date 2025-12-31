import { useState } from 'react'
import { useAuth, maskApiKey } from '@/features/auth'
import ApiKeyModal from '@/features/auth/components/ApiKeyModal'
import { Key, LogOut, Cog, Package } from 'lucide-react'

export default function SettingsPage() {
    const { apiKey, clearApiKey } = useAuth()
    const [showKeyModal, setShowKeyModal] = useState(false)

    return (
        <div className="p-8 max-w-4xl mx-auto space-y-8">
            <header>
                <h1 className="text-3xl font-bold flex items-center gap-3">
                    <Cog className="w-8 h-8" />
                    Settings
                </h1>
                <p className="text-muted-foreground mt-2">
                    Manage your API key and application preferences.
                </p>
            </header>

            {/* API Key Section */}
            <section className="bg-card border rounded-xl overflow-hidden">
                <header className="p-4 border-b bg-muted/30">
                    <h2 className="font-semibold flex items-center gap-2">
                        <Key className="w-4 h-4" />
                        API Key
                    </h2>
                </header>
                <div className="p-6 space-y-4">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-sm text-muted-foreground">Current API Key</p>
                            <code className="font-mono text-lg">
                                {apiKey ? maskApiKey(apiKey) : 'Not set'}
                            </code>
                        </div>
                        <button
                            onClick={() => setShowKeyModal(true)}
                            className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:opacity-90 transition-opacity"
                        >
                            Change Key
                        </button>
                    </div>

                    <div className="pt-4 border-t">
                        <button
                            onClick={() => {
                                if (confirm('Are you sure you want to logout?')) {
                                    clearApiKey()
                                    window.location.reload()
                                }
                            }}
                            className="flex items-center gap-2 px-4 py-2 text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                        >
                            <LogOut className="w-4 h-4" />
                            Logout
                        </button>
                    </div>
                </div>
            </section>

            {/* Optional Features Section */}
            <section className="bg-card border rounded-xl overflow-hidden">
                <header className="p-4 border-b bg-muted/30">
                    <h2 className="font-semibold flex items-center gap-2">
                        <Package className="w-4 h-4" />
                        Optional Features
                    </h2>
                </header>
                <div className="p-6">
                    <p className="text-muted-foreground text-sm">
                        Manage optional features and dependencies.
                    </p>
                    <a
                        href="/admin/tuning"
                        className="inline-flex items-center gap-2 mt-4 px-4 py-2 border rounded-lg hover:bg-muted transition-colors"
                    >
                        Manage Features →
                    </a>
                </div>
            </section>

            {showKeyModal && (
                <ApiKeyModal
                    mode="change"
                    isOpen={showKeyModal}
                    onClose={() => setShowKeyModal(false)}
                    onSuccess={() => setShowKeyModal(false)}
                />
            )}
        </div>
    )
}
