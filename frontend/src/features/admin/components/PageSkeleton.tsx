
import { Skeleton } from "@/components/ui/skeleton"

interface PageSkeletonProps {
    /**
     * Optional mode to customize the skeleton layout.
     * - 'default': Standard header + cards + huge content block
     * - 'list': Header + list items
     */
    mode?: 'default' | 'list'
}

export function PageSkeleton({ mode = 'default' }: PageSkeletonProps) {
    return (
        <div className="p-8 pb-32 max-w-6xl mx-auto space-y-8 animate-in fade-in duration-500">
            {/* Header Skeleton */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="space-y-3">
                    <Skeleton className="h-10 w-64 md:w-96" />
                    <Skeleton className="h-4 w-48 md:w-[500px]" />
                </div>
                <Skeleton className="h-10 w-32" />
            </div>

            {/* Divider */}
            <div className="h-px bg-border/50 w-full" />

            {/* Content Skeleton */}
            {mode === 'default' && (
                <div className="space-y-8">
                    {/* Stats Row */}
                    <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4">
                        <Skeleton className="h-28 rounded-xl" />
                        <Skeleton className="h-28 rounded-xl" />
                        <Skeleton className="h-28 rounded-xl" />
                        <Skeleton className="h-28 rounded-xl hidden lg:block" />
                    </div>

                    {/* Main Content Area */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                        <div className="lg:col-span-2 space-y-4">
                            <Skeleton className="h-10 w-48 mb-4" />
                            <Skeleton className="h-64 rounded-xl" />
                            <Skeleton className="h-48 rounded-xl" />
                        </div>
                        <div className="space-y-4">
                            <Skeleton className="h-10 w-32 mb-4" />
                            <Skeleton className="h-96 rounded-xl" />
                        </div>
                    </div>
                </div>
            )}

            {mode === 'list' && (
                <div className="space-y-6">
                    <div className="flex gap-4">
                        <Skeleton className="h-10 flex-1" />
                        <Skeleton className="h-10 w-32" />
                    </div>
                    <div className="space-y-4">
                        {[1, 2, 3, 4, 5].map((i) => (
                            <Skeleton key={i} className="h-24 w-full rounded-xl" />
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
