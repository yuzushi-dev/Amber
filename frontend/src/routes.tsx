import {
    createRootRoute,
    createRoute,
    createRouter,
    Outlet
} from '@tanstack/react-router'
import MainLayout from './components/layout/MainLayout'
import ChatContainer from './features/chat/components/ChatContainer'
import DocumentLibrary from './features/documents/components/DocumentLibrary'
import AdminLayout from './features/admin/components/AdminLayout'
import JobsPage from './features/admin/pages/JobsPage'
import QueuesPage from './features/admin/pages/QueuesPage'
import TuningPage from './features/admin/pages/TuningPage'
import CurationPage from './features/admin/pages/CurationPage'
import DatabasePage from './features/admin/pages/DatabasePage'

// Create a root route (no layout, we apply per-section)
const rootRoute = createRootRoute({
    component: () => <Outlet />,
})

// =============================================================================
// Analyst Routes (with MainLayout)
// =============================================================================

const analystLayoutRoute = createRoute({
    getParentRoute: () => rootRoute,
    id: '_analyst',
    component: () => (
        <MainLayout>
            <Outlet />
        </MainLayout>
    ),
})

const indexRoute = createRoute({
    getParentRoute: () => analystLayoutRoute,
    path: '/',
    component: () => (
        <div className="p-8">
            <h1 className="text-3xl font-bold mb-4">Dashboard</h1>
            <p className="text-muted-foreground">Welcome to Amber Analyst UI.</p>
        </div>
    ),
})

const chatRoute = createRoute({
    getParentRoute: () => analystLayoutRoute,
    path: '/chat',
    component: () => <ChatContainer />,
})

const documentsRoute = createRoute({
    getParentRoute: () => analystLayoutRoute,
    path: '/documents',
    component: () => <DocumentLibrary />,
})

// =============================================================================
// Admin Routes (with AdminLayout)
// =============================================================================

const adminLayoutRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/admin',
    component: () => (
        <AdminLayout>
            <Outlet />
        </AdminLayout>
    ),
})

const adminJobsRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/jobs',
    component: () => <JobsPage />,
})

const adminQueuesRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/queues',
    component: () => <QueuesPage />,
})

const adminTuningRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/tuning',
    component: () => <TuningPage />,
})

const adminCurationRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/curation',
    component: () => <CurationPage />,
})

const adminDatabaseRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/database',
    component: () => <DatabasePage />,
})

// Admin index redirects to jobs
const adminIndexRoute = createRoute({
    getParentRoute: () => adminLayoutRoute,
    path: '/',
    component: () => <JobsPage />,
})

// =============================================================================
// Build Route Tree
// =============================================================================

const routeTree = rootRoute.addChildren([
    analystLayoutRoute.addChildren([indexRoute, chatRoute, documentsRoute]),
    adminLayoutRoute.addChildren([
        adminIndexRoute,
        adminJobsRoute,
        adminQueuesRoute,
        adminTuningRoute,
        adminCurationRoute,
        adminDatabaseRoute,
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
