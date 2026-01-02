
import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
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

    useEffect(() => {
        const fetchChunks = async () => {
            try {
                const response = await apiClient.get<Chunk[]>(`/documents/${documentId}/chunks`);
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

    if (!documentId) return <div className="p-4 text-center text-yellow-500">No document ID provided</div>;
    if (loading) return <div className="p-4 text-center">Loading chunks...</div>;
    if (error) return <div className="p-4 text-center text-red-500">{error}</div>;

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
                        {chunks.map((chunk) => (
                            <div key={chunk.id} className="p-4 border rounded-lg bg-muted/20 text-sm">
                                <div className="flex justify-between items-center mb-2">
                                    <Badge variant="outline">Chunk #{chunk.index}</Badge>
                                    <span className="text-xs text-muted-foreground">{chunk.tokens} tokens</span>
                                </div>
                                <div className="whitespace-pre-wrap font-mono text-xs text-foreground/90 leading-relaxed">
                                    {chunk.content}
                                </div>
                                <div className="mt-2 flex gap-2">
                                    <Badge variant={chunk.embedding_status === 'completed' ? 'secondary' : 'outline'} className="text-[10px]">
                                        {chunk.embedding_status}
                                    </Badge>
                                </div>
                            </div>
                        ))}
                    </div>
                </ScrollArea>
            </CardContent>
        </Card>
    );
};

export default ChunksTab;
