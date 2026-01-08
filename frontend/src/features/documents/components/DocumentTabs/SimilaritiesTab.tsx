import React, { useEffect, useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { apiClient } from '@/lib/api-client';
import { Link } from 'lucide-react';

interface Similarity {
    source_id: string;
    source_text: string;
    target_id: string;
    target_text: string;
    score: number;
}

interface SimilaritiesTabProps {
    documentId: string;
}

const SimilaritiesTab: React.FC<SimilaritiesTabProps> = ({ documentId }) => {
    const [similarities, setSimilarities] = useState<Similarity[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchSimilarities = async () => {
            try {
                const response = await apiClient.get<Similarity[]>(`/documents/${documentId}/similarities`);
                setSimilarities(response.data);
            } catch (err) {
                console.error(err);
                setError('Failed to load similarities');
            } finally {
                setLoading(false);
            }
        };

        if (documentId) {
            fetchSimilarities();
        }
    }, [documentId]);

    if (loading) return <div className="p-8 text-center text-muted-foreground">Loading similarities...</div>;
    if (error) return <div className="p-8 text-center text-red-500">{error}</div>;

    if (similarities.length === 0) {
        return (
            <div className="p-8 text-center flex flex-col items-center justify-center text-muted-foreground min-h-[400px]">
                <Link className="h-12 w-12 mb-4 opacity-20" />
                <p className="text-lg font-medium">No similarities found</p>
                <p className="text-sm max-w-sm mt-2">
                    This document doesn't have any strong similarity connections with other chunks yet.
                    Try enriching the document or ensure embeddings are generated.
                </p>
            </div>
        );
    }

    return (
        <ScrollArea className="h-full max-h-[600px] w-full p-4">
            <div className="space-y-4">
                {similarities.map((sim, index) => (
                    <Card key={index} className="overflow-hidden hover:shadow-md transition-shadow">
                        <CardContent className="p-0">
                            <div className="grid grid-cols-1 md:grid-cols-[1fr,auto,1fr] gap-4">
                                {/* Source Chunk */}
                                <div className="p-4 bg-muted/20">
                                    <div className="text-xs font-mono text-muted-foreground mb-2 flex items-center gap-2">
                                        <div className="h-2 w-2 rounded-full bg-blue-500"></div>
                                        {sim.source_id.substring(0, 8)}...
                                    </div>
                                    <p className="text-sm line-clamp-4">{sim.source_text}</p>
                                </div>

                                {/* Link / Score */}
                                <div className="flex flex-col items-center justify-center p-2 border-y md:border-y-0 md:border-x bg-muted/50 w-full md:w-32">
                                    <Badge variant="outline" className={`mb-2 ${sim.score > 0.8 ? 'bg-green-500/10 text-green-700 border-green-200' : 'bg-blue-500/10 text-blue-700 border-blue-200'}`}>
                                        {(sim.score * 100).toFixed(0)}% Match
                                    </Badge>
                                    <Link className="h-4 w-4 text-muted-foreground" />
                                </div>

                                {/* Target Chunk */}
                                <div className="p-4 bg-muted/20">
                                    <div className="text-xs font-mono text-muted-foreground mb-2 flex items-center gap-2">
                                        <div className="h-2 w-2 rounded-full bg-orange-500"></div>
                                        {sim.target_id.substring(0, 8)}...
                                    </div>
                                    <p className="text-sm line-clamp-4">{sim.target_text}</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                ))}
            </div>
        </ScrollArea>
    );
};

export default SimilaritiesTab;
