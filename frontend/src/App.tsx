import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { queryClient } from './lib/query-client'
import { router } from './routes'
import { ErrorBoundary } from './components/feedback/ErrorBoundary'
import { useAuth } from './features/auth'
import ApiKeyModal from './features/auth/components/ApiKeyModal'
import { SetupWizard } from './features/setup'
import { useSetupStatus } from './features/setup/hooks/useSetupStatus'
import { Loader2 } from 'lucide-react'
import { Toaster } from 'sonner'

function LoadingScreen() {
  return (
    <div className="fixed inset-0 flex items-center justify-center bg-background">
      <div className="text-center space-y-4">
        <Loader2 className="w-12 h-12 animate-spin mx-auto text-primary" />
        <p className="text-muted-foreground">Loading Amber...</p>
      </div>
    </div>
  )
}

import { useEffect } from 'react'

function AppContent() {
  const { isAuthenticated, apiKey, initialFetch } = useAuth()
  const { data: setupStatus, isLoading, refetch } = useSetupStatus()

  useEffect(() => {
    if (isAuthenticated && apiKey) {
      initialFetch()
    }
  }, [isAuthenticated, apiKey, initialFetch])

  // 1. Not authenticated → Show API Key modal
  if (!isAuthenticated || !apiKey) {
    return <ApiKeyModal />
  }

  // 2. Loading setup status
  if (isLoading) {
    return <LoadingScreen />
  }

  // 3. Setup not complete → Show Setup Wizard (unless all features installed)
  const allFeaturesInstalled = setupStatus?.summary.installed === setupStatus?.summary.total
  if (setupStatus && !setupStatus.setup_complete && !allFeaturesInstalled) {
    return (
      <SetupWizard
        onComplete={() => refetch()}
      />
    )
  }

  // 4. Ready → Show main app
  return <RouterProvider router={router} />
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <AppContent />
        <Toaster richColors position="top-right" closeButton />
      </ErrorBoundary>
    </QueryClientProvider>
  )
}

export default App

