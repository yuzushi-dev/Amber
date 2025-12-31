import { Component, ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
    children: ReactNode
    fallback?: ReactNode
}

interface State {
    hasError: boolean
    error: Error | null
}

/**
 * React Error Boundary for graceful error handling.
 * 
 * Catches JavaScript errors anywhere in the child component tree,
 * logs those errors, and displays a fallback UI.
 * 
 * Usage:
 * <ErrorBoundary>
 *   <MyComponent />
 * </ErrorBoundary>
 */
export default class ErrorBoundary extends Component<Props, State> {
    constructor(props: Props) {
        super(props)
        this.state = { hasError: false, error: null }
    }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error }
    }

    componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
        // Log error to console (in production, send to error tracking service)
        console.error('ErrorBoundary caught an error:', error, errorInfo)
    }

    handleReset = () => {
        this.setState({ hasError: false, error: null })
    }

    render() {
        if (this.state.hasError) {
            // Custom fallback if provided
            if (this.props.fallback) {
                return this.props.fallback
            }

            // Default error UI
            return (
                <div
                    className="flex flex-col items-center justify-center min-h-[300px] p-8 text-center"
                    role="alert"
                    aria-live="assertive"
                >
                    <div className="mb-4 p-3 rounded-full bg-destructive/10">
                        <AlertTriangle className="w-8 h-8 text-destructive" aria-hidden="true" />
                    </div>

                    <h2 className="text-xl font-semibold text-foreground mb-2">
                        Something went wrong
                    </h2>

                    <p className="text-muted-foreground mb-6 max-w-md">
                        An unexpected error occurred. Please try again or contact support if the problem persists.
                    </p>

                    {process.env.NODE_ENV === 'development' && this.state.error && (
                        <pre className="mb-6 p-4 bg-muted rounded-lg text-left text-xs overflow-auto max-w-full">
                            <code>{this.state.error.message}</code>
                        </pre>
                    )}

                    <button
                        onClick={this.handleReset}
                        className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-opacity"
                        aria-label="Try again"
                    >
                        <RefreshCw className="w-4 h-4" aria-hidden="true" />
                        <span>Try Again</span>
                    </button>
                </div>
            )
        }

        return this.props.children
    }
}
