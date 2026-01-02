
import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { apiClient } from '@/lib/api-client';

interface Entity {
    name: string;
    type: string;
    description: string;
}

interface EntitiesTabProps {
    documentId: string;
}

const EntitiesTab: React.FC<EntitiesTabProps> = ({ documentId }) => {
    const [entities, setEntities] = useState<Entity[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchEntities = async () => {
            try {
                const response = await apiClient.get<Entity[]>(`/documents/${documentId}/entities`);
                setEntities(response.data);
            } catch (err) {
                console.error(err);
                setError('Failed to load entities');
            } finally {
                setLoading(false);
            }
        };

        if (documentId) {
            fetchEntities();
        }
    }, [documentId]);

    if (!documentId) return <div className="p-4 text-center text-yellow-500">No document ID provided</div>;
    if (loading) return <div className="p-4 text-center">Loading entities...</div>;
    if (error) return <div className="p-4 text-center text-red-500">{error}</div>;

    return (
        <Card className="border-0 shadow-none">
            <CardHeader>
                <CardTitle>Extracted Entities ({entities.length})</CardTitle>
            </CardHeader>
            <CardContent>
                <div className="rounded-md border">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Name</TableHead>
                                <TableHead>Type</TableHead>
                                <TableHead>Description</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {entities.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={3} className="text-center h-24 text-muted-foreground">
                                        No entities found via Graph Extraction.
                                    </TableCell>
                                </TableRow>
                            ) : (
                                entities.map((entity, idx) => (
                                    <TableRow key={idx}>
                                        <TableCell className="font-medium">{entity.name}</TableCell>
                                        <TableCell><Badge variant="secondary">{entity.type}</Badge></TableCell>
                                        <TableCell className="text-muted-foreground">{entity.description}</TableCell>
                                    </TableRow>
                                ))
                            )}
                        </TableBody>
                    </Table>
                </div>
            </CardContent>
        </Card>
    );
};

export default EntitiesTab;
