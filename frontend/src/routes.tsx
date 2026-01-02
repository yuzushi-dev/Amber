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
import JobsPage from './features/admin/pages/JobsPage'
import QueuesPage from './features/admin/pages/QueuesPage'
import TuningPage from './features/admin/pages/TuningPage'
import CurationPage from './features/admin/pages/CurationPage'
import DatabasePage from './features/admin/pages/DatabasePage'
import VectorStorePage from './features/admin/pages/VectorStorePage'
import DocumentDetailPage from './features/documents/pages/DocumentDetailPage'

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

// Admin Dashboard (index)
const adminIndexRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/',
    component: () => (
        <div className="p-8">
            <h1 className="text-3xl font-bold mb-4">Dashboard</h1>
            <p className="text-muted-foreground">Welcome to Amber Control Panel.</p>
        </div>
    ),
})

// Chat route under admin
const adminChatRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/chat',
    component: () => <ChatContainer />,
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

const dataDatabaseRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/data/database',
    component: () => <DatabasePage />,
})

const dataVectorsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/data/vectors',
    component: () => <VectorStorePage />,
})

const dataMaintenanceRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/data/maintenance',
    component: () => <DatabasePage />, // Reuse DatabasePage for maintenance actions
})

// =============================================================================
// Operations Section (/admin/ops/*)
// =============================================================================

const opsIndexRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops',
    beforeLoad: () => {
        throw redirect({ to: '/admin/ops/jobs' })
    },
})

const opsJobsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/jobs',
    component: () => <JobsPage />,
})

const opsQueuesRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/queues',
    component: () => <QueuesPage />,
})

const opsTuningRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/tuning',
    component: () => <TuningPage />,
})

const opsCurationRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/ops/curation',
    component: () => <CurationPage />,
})

// =============================================================================
// Legacy route redirects (for backwards compatibility)
// =============================================================================

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
        throw redirect({ to: '/admin/data/database' })
    },
})

const legacyJobsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/jobs',
    beforeLoad: () => {
        throw redirect({ to: '/admin/ops/jobs' })
    },
})

const legacyQueuesRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/queues',
    beforeLoad: () => {
        throw redirect({ to: '/admin/ops/queues' })
    },
})

const legacyTuningRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/tuning',
    beforeLoad: () => {
        throw redirect({ to: '/admin/ops/tuning' })
    },
})

const legacyCurationRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/curation',
    beforeLoad: () => {
        throw redirect({ to: '/admin/ops/curation' })
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
        // Data section
        dataIndexRoute,
        dataDocumentsRoute,
        dataDocumentDetailRoute,
        dataDatabaseRoute,
        dataVectorsRoute,
        dataMaintenanceRoute,
        // Operations section
        opsIndexRoute,
        opsJobsRoute,
        opsQueuesRoute,
        opsTuningRoute,
        opsCurationRoute,
        // Legacy redirects
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
