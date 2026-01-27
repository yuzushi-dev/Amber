
import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Pencil, Trash2, Loader2 } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface Chunk {
    id: string;
    index: number;
    content: string;
    tokens: number;
    embedding_status: string;
}

interface ChunksTabProps {
    documentId: string;
}

const ChunksTab: React.FC<ChunksTabProps> = ({ documentId }) => {
    const [chunks, setChunks] = useState<Chunk[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Editing State
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editContent, setEditContent] = useState('');
    const [actionId, setActionId] = useState<string | null>(null); // For loading states on specific chunks

    useEffect(() => {
        const fetchChunks = async () => {
            try {
                const response = await apiClient.get<Chunk[]>(`/documents/${documentId}/chunks?limit=100`);
                setChunks(response.data);
            } catch (err) {
                console.error(err);
                setError('Failed to load chunks');
            } finally {
                setLoading(false);
            }
        };

        if (documentId) {
            fetchChunks();
        }
    }, [documentId]);

    const handleEdit = (chunk: Chunk) => {
        setEditingId(chunk.id);
        setEditContent(chunk.content);
    };

    const handleCancel = () => {
        setEditingId(null);
        setEditContent('');
    };

    const handleSave = async (chunkId: string) => {
        if (!editContent.trim()) return;
        setActionId(chunkId);
        try {
            const response = await apiClient.put<Chunk>(`/documents/${documentId}/chunks/${chunkId}`, {
                content: editContent
            });

            // Update local state
            setChunks(prev => prev.map(c => c.id === chunkId ? response.data : c));
            setEditingId(null);
            setEditContent('');
        } catch (err) {
            console.error(err);
            alert('Failed to save chunk');
        } finally {
            setActionId(null);
        }
    };

    const handleDelete = async (chunkId: string) => {
        if (!confirm('Are you sure you want to delete this chunk?')) return;
        setActionId(chunkId);
        try {
            await apiClient.delete(`/documents/${documentId}/chunks/${chunkId}`);
            setChunks(prev => prev.filter(c => c.id !== chunkId));
        } catch (err) {
            console.error(err);
            alert('Failed to delete chunk');
        } finally {
            setActionId(null);
        }
    };

    if (!documentId) return <div className="p-4 text-center text-warning">No document ID provided</div>;
    if (loading) return <div className="p-4 text-center">Loading chunks...</div>;
    if (error) return <div className="p-4 text-center text-destructive">{error}</div>;

    return (
        <Card className="border-0 shadow-none h-full flex flex-col">
            <CardHeader className="py-4">
                <CardTitle className="text-sm font-medium">
                    Total Chunks: {chunks.length} | Total Tokens: {chunks.reduce((acc, c) => acc + c.tokens, 0)}
                </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 overflow-hidden p-0">
                <ScrollArea className="h-full px-6 pb-6">
                    <div className="space-y-4">
                        {chunks.map((chunk) => {
                            const isEditing = editingId === chunk.id;
                            const isLoading = actionId === chunk.id;

                            return (
                                <div key={chunk.id} className={`p-4 border rounded-lg text-sm transition-colors ${isEditing ? 'bg-background border-primary ring-1 ring-primary' : 'bg-muted/20 hover:border-primary/50'}`}>
                                    <div className="flex justify-between items-start mb-3">
                                        <div className="flex items-center gap-2">
                                            <Badge variant="outline">Chunk #{chunk.index}</Badge>
                                            <span className="text-xs text-muted-foreground">{chunk.tokens} tokens</span>
                                            <Badge variant={chunk.embedding_status === 'completed' ? 'secondary' : 'outline'} className="text-[10px]">
                                                {chunk.embedding_status}
                                            </Badge>
                                        </div>

                                        {!isEditing && (
                                            <div className="flex items-center gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    className="h-7 w-7"
                                                    onClick={() => handleEdit(chunk)}
                                                    disabled={isLoading || !!editingId}
                                                    aria-label={`Edit chunk ${chunk.index}`}
                                                >
                                                    <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    className="h-7 w-7 text-destructive hover:text-destructive"
                                                    onClick={() => handleDelete(chunk.id)}
                                                    disabled={isLoading || !!editingId}
                                                    aria-label={`Delete chunk ${chunk.index}`}
                                                >
                                                    {isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                                                </Button>
                                            </div>
                                        )}
                                    </div>

                                    {isEditing ? (
                                        <div className="space-y-3">
                                            <Textarea
                                                className="min-h-[120px] font-mono"
                                                value={editContent}
                                                onChange={(e) => setEditContent(e.target.value)}
                                                disabled={isLoading}
                                            />
                                            <div className="flex justify-end gap-2">
                                                <Button variant="ghost" size="sm" onClick={handleCancel} disabled={isLoading}>
                                                    Cancel
                                                </Button>
                                                <Button size="sm" onClick={() => handleSave(chunk.id)} disabled={isLoading}>
                                                    {isLoading && <Loader2 className="mr-2 h-3 w-3 animate-spin" />}
                                                    Save Changes
                                                </Button>
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="group relative">
                                            <div className="whitespace-pre-wrap font-mono text-xs text-foreground/90 leading-relaxed cursor-text" onClick={() => !editingId && handleEdit(chunk)}>
                                                {chunk.content}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </ScrollArea>
            </CardContent>
        </Card>
    );
};

export default ChunksTab;
