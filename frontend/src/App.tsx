import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { queryClient } from './lib/query-client'
import { router } from './routes'
import { ErrorBoundary } from './components/feedback/ErrorBoundary'
import { useAuth } from './features/auth'
import ApiKeyModal from './features/auth/components/ApiKeyModal'
import { SetupWizard } from './features/setup'
import { useSetupStatus } from './features/setup/hooks/useSetupStatus'
import ConstellationLoader from './components/ui/constellation-loader'
import { Toaster } from 'sonner'

function LoadingScreen({ message = "Amber is waking up..." }: { message?: string }) {
  return (
    <div className="fixed inset-0 bg-black z-50">
      <div className="absolute inset-0">
        <ConstellationLoader />
      </div>
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <p
          className="text-primary text-lg font-light tracking-wider animate-pulse"
          style={{ marginTop: 'calc(min(30vmin, 200px) + 3.75rem)' }}
        >
          {message}
        </p>
      </div>
    </div>
  )
}

import { useEffect } from 'react'

function AppContent() {
  const { isAuthenticated, apiKey, initialFetch } = useAuth()
  const { data: setupStatus, isLoading, isError, error, refetch } = useSetupStatus()
  const { clearApiKey } = useAuth()

  useEffect(() => {
    if (isAuthenticated && apiKey) {
      initialFetch()
    }
  }, [isAuthenticated, apiKey, initialFetch])

  // Handle 401 from setup status (invalid key despite auth state)
  useEffect(() => {
    if (isError && error?.message === 'Unauthorized') {
      console.warn("Unauthorized access detected in App. Logging out.")
      clearApiKey()
    }
  }, [isError, error, clearApiKey])

  // 1. Not authenticated → Show API Key modal
  if (!isAuthenticated || !apiKey) {
    return <ApiKeyModal />
  }

  // 2. Loading setup status
  if (isLoading) {
    return <LoadingScreen />
  }

  // 3. Setup not complete → Show Setup Wizard (if not complete OR db migration needed)
  const allFeaturesInstalled = setupStatus?.summary.installed === setupStatus?.summary.total
  if (setupStatus && (!setupStatus.setup_complete && !allFeaturesInstalled || setupStatus.db_migration_needed)) {
    return (
      <SetupWizard
        onComplete={() => refetch()}
      />
    )
  }

  // 4. Ready → Show main app
  return <RouterProvider router={router} />
}

import { useSystemReady } from './features/setup/hooks/useSystemReady'

function AppContentWrapper() {
  const { data: systemReady, isLoading } = useSystemReady()
  const isReady = systemReady?.status === 'ready'

  if (isLoading || !isReady) {
    return (
      <LoadingScreen message={isLoading ? "Connecting to server..." : "Waiting for services... This might take a few minutes."} />
    )
  }

  return <AppContent />
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <AppContentWrapper />
        <Toaster richColors position="top-right" closeButton />
      </ErrorBoundary>
    </QueryClientProvider>
  )
}

export default App

