/**
 * API Key Management Component
 * ============================
 * 
 * Displays current API key status with option to change or logout.
 */

import { useState } from 'react'
import { useAuth, maskApiKey } from '@/features/auth'
import ApiKeyModal from '@/features/auth/components/ApiKeyModal'
import { Key, LogOut } from 'lucide-react'

export default function ApiKeyManager() {
    const { apiKey, clearApiKey } = useAuth()
    const [showKeyModal, setShowKeyModal] = useState(false)

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-lg font-semibold flex items-center gap-2">
                    <Key className="w-5 h-5" />
                    API Key
                </h2>
                <p className="text-sm text-muted-foreground">
                    Manage your authentication credentials.
                </p>
            </div>

            <div className="flex items-center justify-between p-4 border rounded-lg bg-card">
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
