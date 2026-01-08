/**
 * API Key Page
 * ============
 * 
 * Page wrapper for API Key Management.
 */


import ApiKeyManager from '../components/ApiKeyManager'

export default function ApiKeyPage() {
    return (
        <div className="p-6 pb-32 max-w-4xl mx-auto">
            <ApiKeyManager />
        </div>
    )
}
