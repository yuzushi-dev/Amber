/**
 * routes.tsx
 * ==========
 * 
 * Application routing configuration.
 * - /amber/*: Client view (focused chat, no sidebar)
 * - /admin: Dashboard
 * - /admin/chat: Analyst chat
 * - /admin/data/*: Data management (Documents, Database, Vectors)
 * - /admin/ops/*: Operations (Jobs, Queues, Tuning, Curation)
 */

import {
    createRootRoute,
    createRoute,
    createRouter,
    Outlet,
    redirect
} from '@tanstack/react-router'
import MainLayout from './components/layout/MainLayout'
import ClientLayout from './components/layout/ClientLayout'
import ChatContainer from './features/chat/components/ChatContainer'
import DocumentLibrary from './features/documents/components/DocumentLibrary'
// import JobsPage from './features/admin/pages/JobsPage' // Deprecated
// import QueuesPage from './features/admin/pages/QueuesPage' // Deprecated
import JobsAndQueuesPage from './features/admin/pages/JobsAndQueuesPage'
import TuningPage from './features/admin/pages/TuningPage'
import CurationPage from './features/admin/pages/CurationPage'
import MaintenancePage from './features/admin/pages/MaintenancePage'
import VectorStorePage from './features/admin/pages/VectorStorePage'
import DocumentDetailPage from './features/documents/pages/DocumentDetailPage'
import TokenMetricsPage from './features/admin/pages/TokenMetricsPage'
import RagasSubPanel from './features/admin/components/RagasSubPanel'
import QueryLogPage from './features/admin/pages/QueryLogPage'
import ApiKeyPage from './features/admin/pages/ApiKeyPage'
import OptionalFeaturesPage from './features/admin/pages/OptionalFeaturesPage'
import ConnectorsPage from './features/admin/pages/ConnectorsPage'
import ConnectorDetailPage from './features/admin/pages/ConnectorDetailPage'
import TenantsPage from './features/admin/pages/TenantsPage'

// =============================================================================
// Root Route
// =============================================================================

const rootRoute = createRootRoute({
    component: () => <Outlet />,
})

// =============================================================================
// Index Route (Redirect to Client Chat)
// =============================================================================

const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    beforeLoad: () => {
        throw redirect({ to: '/amber/chat' })
    },
})

// =============================================================================
// Client Routes (with ClientLayout - No Sidebar)
// =============================================================================

const clientLayoutRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/amber',
    component: () => (
        <ClientLayout>
            <Outlet />
        </ClientLayout>
    ),
})

const clientChatRoute = createRoute({
    getParentRoute: () => clientLayoutRoute,
    path: '/chat',
    component: () => <ChatContainer />,
})

// Client index redirects to chat
const clientIndexRoute = createRoute({
    getParentRoute: () => clientLayoutRoute,
    path: '/',
    beforeLoad: () => {
        throw redirect({ to: '/amber/chat' })
    },
})

// =============================================================================
// Admin/Analyst Routes (with MainLayout - Dock + Context Sidebar)
// =============================================================================

const adminLayoutRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/admin',
    component: () => (
        <MainLayout>
            <Outlet />
        </MainLayout>
    ),
})

// Admin Dashboard (index) - redirect to chat
const adminIndexRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/',
    beforeLoad: () => {
        throw redirect({ to: '/admin/chat' })
    },
})

// Chat route under admin
const adminChatRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/chat',
    component: () => <ChatContainer />,
})

const adminQueriesRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/queries',
    component: () => <QueryLogPage />,
})

// =============================================================================
// Data Section (/admin/data/*)
// =============================================================================

const dataIndexRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/data',
    beforeLoad: () => {
        throw redirect({ to: '/admin/data/documents' })
    },
})

const dataDocumentsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/data/documents',
    component: () => <DocumentLibrary />,
})

const dataDocumentDetailRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/data/documents/$documentId',
    component: () => <DocumentDetailPage />,
})

const dataMaintenanceRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/data/maintenance',
    component: () => <MaintenancePage />,
})

const dataVectorsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/data/vectors',
    component: () => <VectorStorePage />,
})

// =============================================================================
// Settings Section (/admin/settings/*)
// =============================================================================

const settingsIndexRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/settings',
    beforeLoad: () => {
        throw redirect({ to: '/admin/settings/tuning' })
    },
})

const settingsTuningRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/settings/tuning',
    component: () => <TuningPage />,
})

const settingsFeaturesRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/settings/features',
    component: () => <OptionalFeaturesPage />,
})

const settingsKeysRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/settings/keys',
    component: () => <ApiKeyPage />,
})

const settingsCurationRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/settings/curation',
    component: () => <CurationPage />,
})

const settingsConnectorsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/settings/connectors',
    component: () => <ConnectorsPage />,
})

const settingsConnectorDetailRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/settings/connectors/$connectorType',
    component: () => <ConnectorDetailPage />,
})

const settingsTenantsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/settings/tenants',
    component: () => <TenantsPage />,
})


// =============================================================================
// Metrics Section (/admin/metrics/*)
// =============================================================================

const metricsIndexRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/metrics',
    beforeLoad: () => {
        throw redirect({ to: '/admin/metrics/tokens' })
    },
})

const metricsSystemRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/metrics/system',
    component: () => <JobsAndQueuesPage />,
})

const metricsTokensRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/metrics/tokens',
    component: () => <TokenMetricsPage />,
})

const metricsRagasRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/metrics/ragas',
    component: () => <div className="p-6"><RagasSubPanel /></div>,
})

// =============================================================================
// Legacy route redirects (for backwards compatibility)
// =============================================================================

// Ops redirects
const opsIndexRedirect = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops',
    beforeLoad: () => { throw redirect({ to: '/admin/metrics/system' }) },
})
const opsJobsRedirect = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/jobs',
    beforeLoad: () => { throw redirect({ to: '/admin/metrics/system' }) },
})
const opsQueuesRedirect = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/queues',
    beforeLoad: () => { throw redirect({ to: '/admin/metrics/system' }) },
})
const opsTuningRedirect = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/tuning',
    beforeLoad: () => { throw redirect({ to: '/admin/settings/tuning' }) },
})
const opsCurationRedirect = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/curation',
    beforeLoad: () => { throw redirect({ to: '/admin/settings/curation' }) },
})
const opsMetricsRedirect = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/metrics',
    beforeLoad: () => { throw redirect({ to: '/admin/metrics/tokens' }) },
})
const opsRagasRedirect = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/ragas',
    beforeLoad: () => { throw redirect({ to: '/admin/metrics/ragas' }) },
})

// Old legacy redirects
const legacyDocumentsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/documents',
    beforeLoad: () => {
        throw redirect({ to: '/admin/data/documents' })
    },
})

const legacyDatabaseRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/database',
    beforeLoad: () => {
        throw redirect({ to: '/admin/data/maintenance' })
    },
})

const legacyJobsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/jobs',
    beforeLoad: () => {
        throw redirect({ to: '/admin/metrics/system' })
    },
})

const legacyQueuesRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/queues',
    beforeLoad: () => {
        throw redirect({ to: '/admin/metrics/system' })
    },
})

const legacyTuningRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/tuning',
    beforeLoad: () => {
        throw redirect({ to: '/admin/settings/tuning' })
    },
})

const legacyCurationRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/curation',
    beforeLoad: () => {
        throw redirect({ to: '/admin/settings/curation' })
    },
})

// =============================================================================
// Build Route Tree
// =============================================================================

const routeTree = rootRoute.addChildren([
    indexRoute,
    clientLayoutRoute.addChildren([clientIndexRoute, clientChatRoute]),
    adminLayoutRoute.addChildren([
        adminIndexRoute,
        adminChatRoute,
        adminQueriesRoute,
        // Data section
        dataIndexRoute,
        dataDocumentsRoute,
        dataDocumentDetailRoute,
        dataMaintenanceRoute,
        dataVectorsRoute,
        // Settings section
        settingsIndexRoute,
        settingsTuningRoute,
        settingsFeaturesRoute,
        settingsKeysRoute,

        settingsCurationRoute,
        settingsConnectorsRoute,
        settingsConnectorDetailRoute,
        settingsTenantsRoute,
        // Metrics section

        metricsIndexRoute,
        metricsSystemRoute,
        metricsTokensRoute,
        metricsRagasRoute,
        // Legacy redirects
        opsIndexRedirect,
        opsJobsRedirect,
        opsQueuesRedirect,
        opsTuningRedirect,
        opsCurationRedirect,
        opsMetricsRedirect,
        opsRagasRedirect,
        legacyDocumentsRoute,
        legacyDatabaseRoute,
        legacyJobsRoute,
        legacyQueuesRoute,
        legacyTuningRoute,
        legacyCurationRoute,
    ]),
])

// Create the router
export const router = createRouter({ routeTree })

// Register the router instance for type safety
declare module '@tanstack/react-router' {
    interface Register {
        router: typeof router
    }
}
