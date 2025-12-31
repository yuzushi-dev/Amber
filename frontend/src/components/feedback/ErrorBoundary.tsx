import { Component, ReactNode } from 'react'

interface Props {
    children: ReactNode
    fallback?: ReactNode
}

interface State {
    hasError: boolean
    error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false, error: null }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error }
    }

    render() {
        if (this.state.hasError) {
            return this.props.fallback || (
                <div className="flex flex-col items-center justify-center h-full min-h-[400px] p-8 text-center text-red-100">
                    <h2 className="text-2xl font-bold text-red-600 mb-4">
                        Something went wrong
                    </h2>
                    <p className="text-muted-foreground mb-6 max-w-md">
                        {this.state.error?.message || "An unexpected error occurred while rendering this component."}
                    </p>
                    <button
                        onClick={() => window.location.reload()}
                        className="px-6 py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-opacity"
                    >
                        Reload Page
                    </button>
                </div>
            )
        }

        return this.props.children
    }
}
