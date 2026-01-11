import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card'

/**
 * Skeleton loader for ConnectorCard that matches the actual card layout.
 * Provides visual continuity during loading states.
 */
export function ConnectorCardSkeleton() {
    return (
        <Card className="animate-pulse">
            <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
                <div className="flex flex-col gap-2">
                    {/* Title skeleton */}
                    <Skeleton className="h-5 w-24" />
                    {/* Description skeleton */}
                    <Skeleton className="h-4 w-32" />
                </div>
                {/* Icon skeleton */}
                <Skeleton className="w-12 h-12 rounded-lg" />
            </CardHeader>
            <CardContent>
                <div className="flex flex-col gap-4 mt-2">
                    {/* Status row skeleton */}
                    <div className="flex justify-between items-center">
                        <Skeleton className="h-4 w-12" />
                        <Skeleton className="h-5 w-20 rounded-full" />
                    </div>
                    {/* Last sync row skeleton */}
                    <div className="flex justify-between items-center">
                        <Skeleton className="h-4 w-16" />
                        <Skeleton className="h-4 w-24" />
                    </div>
                </div>
            </CardContent>
            <CardFooter className="flex justify-between gap-2">
                {/* Manage button skeleton */}
                <Skeleton className="h-9 flex-1" />
                {/* Sync button skeleton */}
                <Skeleton className="h-9 w-9" />
            </CardFooter>
        </Card>
    )
}

export default ConnectorCardSkeleton
