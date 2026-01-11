import { useState, useEffect } from 'react'
import { connectorsApi, ConnectorItem } from '@/lib/api-connectors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { Search, Loader2, ExternalLink, ChevronLeft, ChevronRight, Package } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

interface ConnectorContentBrowserProps {
    type: string
}

/**
 * Format date as relative time
 */
function formatRelativeTime(dateString: string): string {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
}

export default function ConnectorContentBrowser({ type }: ConnectorContentBrowserProps) {
    const [items, setItems] = useState<ConnectorItem[]>([])
    const [loading, setLoading] = useState(false)
    const [search, setSearch] = useState('')
    const [page, setPage] = useState(1)
    const [pageSize, setPageSize] = useState(10)
    const [hasMore, setHasMore] = useState(false)
    const [totalCount, setTotalCount] = useState<number | null>(null)
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
    const [ingesting, setIngesting] = useState(false)

    const fetchItems = async () => {
        try {
            setLoading(true)
            const res = await connectorsApi.listItems(type, page, pageSize, search)
            setItems(res.items)
            setHasMore(res.has_more)
            // Estimate total if not provided
            if (res.total_count) {
                setTotalCount(res.total_count)
            }
        } catch (err) {
            console.error(err)
            toast.error('Failed to fetch items. Please check configuration.')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchItems()
        // Clear selection on page/search change
        setSelectedIds(new Set())
    }, [page, search, pageSize])

    const handleSearch = (e: React.FormEvent) => {
        e.preventDefault()
        setPage(1)
        fetchItems()
    }

    const toggleSelection = (id: string) => {
        const next = new Set(selectedIds)
        if (next.has(id)) {
            next.delete(id)
        } else {
            next.add(id)
        }
        setSelectedIds(next)
    }

    const toggleSelectAll = () => {
        if (selectedIds.size === items.length) {
            setSelectedIds(new Set())
        } else {
            setSelectedIds(new Set(items.map(i => i.id)))
        }
    }

    const handleIngest = async () => {
        if (selectedIds.size === 0) return

        try {
            setIngesting(true)
            await connectorsApi.ingestItems(type, Array.from(selectedIds))
            toast.success(`Started ingestion for ${selectedIds.size} items`)
            setSelectedIds(new Set())
        } catch (err: any) {
            toast.error(err.response?.data?.detail || 'Ingestion failed')
        } finally {
            setIngesting(false)
        }
    }

    const showSender = type === 'carbonio'
    const columnCount = showSender ? 5 : 4

    // Calculate pagination info
    const startItem = (page - 1) * pageSize + 1
    const endItem = startItem + items.length - 1

    return (
        <div className="space-y-4">
            {/* Search and Controls */}
            <div className="flex items-center gap-3">
                <form onSubmit={handleSearch} className="flex-1 flex gap-2">
                    <div className="relative flex-1 max-w-md">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                        <Input
                            placeholder="Search content..."
                            className="pl-9"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />
                    </div>
                    <Button type="submit" variant="secondary">
                        Search
                    </Button>
                </form>

                {/* Page size selector */}
                <Select value={pageSize.toString()} onValueChange={(v: string) => { setPageSize(Number(v)); setPage(1) }}>
                    <SelectTrigger className="w-[100px]">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="10">10 / page</SelectItem>
                        <SelectItem value="25">25 / page</SelectItem>
                        <SelectItem value="50">50 / page</SelectItem>
                    </SelectContent>
                </Select>
            </div>

            {/* Table */}
            <div className="border rounded-lg overflow-hidden">
                <Table>
                    <TableHeader>
                        <TableRow className="bg-muted/30 hover:bg-muted/30">
                            <TableHead className="w-[50px]">
                                <Checkbox
                                    checked={items.length > 0 && selectedIds.size === items.length}
                                    onCheckedChange={toggleSelectAll}
                                    aria-label="Select all"
                                />
                            </TableHead>
                            <TableHead>Title</TableHead>
                            <TableHead className="w-[120px]">Updated</TableHead>
                            {showSender && <TableHead className="w-[200px]">Sender</TableHead>}
                            <TableHead className="text-right w-[80px]">Action</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading && items.length === 0 ? (
                            // Skeleton loading rows
                            Array.from({ length: 5 }).map((_, i) => (
                                <TableRow key={i}>
                                    <TableCell><Skeleton className="h-4 w-4" /></TableCell>
                                    <TableCell>
                                        <div className="space-y-2">
                                            <Skeleton className="h-4 w-3/4" />
                                            <Skeleton className="h-3 w-1/2" />
                                        </div>
                                    </TableCell>
                                    <TableCell><Skeleton className="h-4 w-16" /></TableCell>
                                    {showSender && <TableCell><Skeleton className="h-4 w-32" /></TableCell>}
                                    <TableCell className="text-right"><Skeleton className="h-4 w-10 ml-auto" /></TableCell>
                                </TableRow>
                            ))
                        ) : items.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={columnCount} className="h-40">
                                    <div className="flex flex-col items-center justify-center text-center">
                                        <div className="w-12 h-12 mb-3 rounded-full bg-muted/30 flex items-center justify-center">
                                            <Package className="w-6 h-6 text-muted-foreground" />
                                        </div>
                                        <p className="text-muted-foreground font-medium">
                                            {search ? 'No items match your search' : 'No items available'}
                                        </p>
                                        {search && (
                                            <Button
                                                variant="link"
                                                size="sm"
                                                onClick={() => setSearch('')}
                                                className="mt-1"
                                            >
                                                Clear search
                                            </Button>
                                        )}
                                    </div>
                                </TableCell>
                            </TableRow>
                        ) : (
                            items.map((item) => {
                                const isSelected = selectedIds.has(item.id)
                                return (
                                    <TableRow
                                        key={item.id}
                                        className={cn(
                                            'transition-colors cursor-pointer',
                                            isSelected && 'bg-primary/5 border-l-2 border-l-primary',
                                            !isSelected && 'hover:bg-muted/30'
                                        )}
                                        onClick={() => toggleSelection(item.id)}
                                    >
                                        <TableCell onClick={(e) => e.stopPropagation()}>
                                            <Checkbox
                                                checked={isSelected}
                                                onCheckedChange={() => toggleSelection(item.id)}
                                            />
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex flex-col gap-0.5">
                                                <span className="font-medium line-clamp-1">{item.title}</span>
                                                {item.metadata?.snippet && (
                                                    <span className="text-xs text-muted-foreground line-clamp-1">
                                                        {item.metadata.snippet}
                                                    </span>
                                                )}
                                                {type !== 'carbonio' && item.url && (
                                                    <span className="text-xs text-muted-foreground/70 truncate max-w-[300px]">
                                                        {item.url}
                                                    </span>
                                                )}
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-sm text-muted-foreground">
                                            {formatRelativeTime(item.updated_at)}
                                        </TableCell>
                                        {showSender && (
                                            <TableCell className="text-sm truncate max-w-[200px]">
                                                {item.metadata?.sender || '-'}
                                            </TableCell>
                                        )}
                                        <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                                            <a
                                                href={item.url}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="inline-flex items-center gap-1 text-sm text-primary hover:text-primary/80 hover:underline transition-colors"
                                            >
                                                View
                                                <ExternalLink className="w-3 h-3" />
                                            </a>
                                        </TableCell>
                                    </TableRow>
                                )
                            })
                        )}
                    </TableBody>
                </Table>
            </div>

            {/* Enhanced Pagination */}
            <div className="flex items-center justify-between">
                <p className="text-sm text-muted-foreground">
                    {items.length > 0 ? (
                        <>
                            Showing <span className="font-medium text-foreground">{startItem}</span> to{' '}
                            <span className="font-medium text-foreground">{endItem}</span>
                            {totalCount && (
                                <> of <span className="font-medium text-foreground">{totalCount}</span> items</>
                            )}
                        </>
                    ) : (
                        'No items to display'
                    )}
                </p>

                <div className="flex items-center gap-2">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        disabled={page === 1 || loading}
                    >
                        <ChevronLeft className="w-4 h-4 mr-1" />
                        Previous
                    </Button>

                    <div className="flex items-center gap-1">
                        {/* Page indicator */}
                        <span className="px-3 py-1 text-sm font-medium bg-muted rounded">
                            Page {page}
                        </span>
                    </div>

                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPage(p => p + 1)}
                        disabled={!hasMore || loading}
                    >
                        Next
                        <ChevronRight className="w-4 h-4 ml-1" />
                    </Button>
                </div>
            </div>

            {/* Floating Selection Bar */}
            {selectedIds.size > 0 && (
                <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-4 fade-in duration-200">
                    <div className="flex items-center gap-4 bg-surface-800/95 backdrop-blur-xl border border-primary/30 rounded-full px-6 py-3 shadow-glow">
                        <span className="text-sm font-medium">
                            <span className="text-primary">{selectedIds.size}</span> item{selectedIds.size !== 1 && 's'} selected
                        </span>
                        <div className="w-px h-5 bg-border" />
                        <Button
                            size="sm"
                            onClick={handleIngest}
                            disabled={ingesting}
                            className="rounded-full"
                        >
                            {ingesting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                            Ingest Selected
                        </Button>
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setSelectedIds(new Set())}
                            className="rounded-full text-muted-foreground hover:text-foreground"
                        >
                            Clear
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}
