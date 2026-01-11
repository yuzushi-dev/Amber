import { useState, useEffect } from 'react'
import { connectorsApi, ConnectorItem } from '@/lib/api-connectors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'

import { Search, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

interface ConnectorContentBrowserProps {
    type: string
}

export default function ConnectorContentBrowser({ type }: ConnectorContentBrowserProps) {
    const [items, setItems] = useState<ConnectorItem[]>([])
    const [loading, setLoading] = useState(false)
    const [search, setSearch] = useState('')
    const [page, setPage] = useState(1)
    const [hasMore, setHasMore] = useState(false)
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
    const [ingesting, setIngesting] = useState(false)

    const fetchItems = async () => {
        try {
            setLoading(true)
            const res = await connectorsApi.listItems(type, page, 10, search)
            setItems(res.items)
            setHasMore(res.has_more)
        } catch (err) {
            console.error(err)
            toast.error('Failed to fetch items. Please check configuration.')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchItems()
    }, [page, search]) // Corrected dependency array behavior via debounce in real world, but simple here

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

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <form onSubmit={handleSearch} className="flex-1 flex gap-2">
                    <div className="relative flex-1">
                        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                        <Input
                            placeholder="Search articles..."
                            className="pl-8"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />
                    </div>
                    <Button type="submit" variant="secondary">Search</Button>
                </form>
                {selectedIds.size > 0 && (
                    <Button onClick={handleIngest} disabled={ingesting}>
                        {ingesting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                        Ingest {selectedIds.size} Items
                    </Button>
                )}
            </div>

            <div className="border rounded-md">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[50px]"></TableHead>
                            <TableHead>Title</TableHead>
                            <TableHead>Updated</TableHead>
                            {type === 'carbonio' && <TableHead>Sender</TableHead>}
                            <TableHead className="text-right">Action</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading && items.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={4} className="h-24 text-center">
                                    Loading...
                                </TableCell>
                            </TableRow>
                        ) : items.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={4} className="h-24 text-center text-muted-foreground">
                                    No items found.
                                </TableCell>
                            </TableRow>
                        ) : (
                            items.map((item) => (
                                <TableRow key={item.id}>
                                    <TableCell>
                                        <Checkbox
                                            checked={selectedIds.has(item.id)}
                                            onCheckedChange={() => toggleSelection(item.id)}
                                        />
                                    </TableCell>
                                    <TableCell className="font-medium">
                                        <div className="flex flex-col gap-0.5">
                                            <span>{item.title}</span>
                                            {item.metadata?.snippet && (
                                                <span className="text-xs text-muted-foreground line-clamp-1">
                                                    {item.metadata.snippet}
                                                </span>
                                            )}
                                            {/* Hide URL for Carbonio as it's less useful, keep for others */}
                                            {type !== 'carbonio' && (
                                                <div className="text-xs text-muted-foreground truncate max-w-[300px]">
                                                    {item.url}
                                                </div>
                                            )}
                                        </div>
                                    </TableCell>
                                    <TableCell>
                                        {new Date(item.updated_at).toLocaleDateString()}
                                    </TableCell>
                                    {type === 'carbonio' && (
                                        <TableCell>
                                            {item.metadata?.sender || '-'}
                                        </TableCell>
                                    )}
                                    <TableCell className="text-right">
                                        <a
                                            href={item.url}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="text-sm text-primary hover:underline"
                                        >
                                            View
                                        </a>
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </div>

            <div className="flex items-center justify-end gap-2">
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1 || loading}
                >
                    Previous
                </Button>
                <div className="text-sm font-medium">Page {page}</div>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage(p => p + 1)}
                    disabled={!hasMore || loading}
                >
                    Next
                </Button>
            </div>
        </div>
    )
}
