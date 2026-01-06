
import React, { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Card, CardContent } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { apiClient } from '@/lib/api-client';
import { PDFViewer } from '../PDFViewer';

interface ContentTabProps {
    documentId: string;
}

interface DocumentData {
    content_type?: string
    [key: string]: unknown
}

interface Chunk {
    index: number
    content: string
}

const ContentTab: React.FC<ContentTabProps> = ({ documentId }) => {
    const [content, setContent] = useState<string>('');
    const [contentType, setContentType] = useState<string | null>(null);
    const [fileUrl, setFileUrl] = useState<string | { url: string; httpHeaders?: Record<string, string> } | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchContent = async () => {
            try {
                // Fetch document metadata to get content_type
                const docResponse = await apiClient.get<DocumentData>(`/documents/${documentId}`);
                const document = docResponse.data;
                const type = document.content_type || 'text/plain';

                setContentType(type);

                // For PDFs, pass direct URL with auth headers for streaming
                if (type === 'application/pdf') {
                    // Construct absolute URL (apiClient baseURL might be relative or absolute)
                    const baseUrl = apiClient.defaults.baseURL || '/v1';
                    // Clean trailing slash if present
                    const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;

                    // Construct URL: we need full path if base is relative
                    // If baseURL is '/v1', result is '/v1/documents/...'
                    const url = `${cleanBase}/documents/${documentId}/file`;

                    // Get token for auth
                    const token = localStorage.getItem('api_key');

                    // Use 'file' object format for PDFViewer
                    setFileUrl({
                        url: url,
                        httpHeaders: token ? { 'X-API-Key': token } : undefined
                    } as unknown as string); // Cast to string/object as per PDFViewer props (typed loosely as string | object)

                    setLoading(false);
                    return;
                }

                // For text-based formats, fetch chunks to reconstruct content
                const chunksResponse = await apiClient.get<{ chunks: Chunk[] } | Chunk[]>(`/documents/${documentId}/chunks`);
                const chunks = 'chunks' in chunksResponse.data ? chunksResponse.data.chunks : chunksResponse.data;

                // Sort by index and join
                const fullText = chunks
                    .sort((a, b) => a.index - b.index)
                    .map((c) => c.content)
                    .join('\n\n');

                setContent(fullText || 'No text content available.');
            } catch (err) {
                console.error('Error loading document content:', err);
                setError('Failed to load content');
            } finally {
                setLoading(false);
            }
        };

        if (documentId) {
            fetchContent();
        }

        // Cleanup function
        return () => {
            setFileUrl((prevUrl) => {
                if (typeof prevUrl === 'string' && prevUrl.startsWith('blob:')) {
                    console.log('Cleaning up blob URL:', prevUrl);
                    URL.revokeObjectURL(prevUrl);
                }
                return null;
            });
        };
    }, [documentId]);

    if (!documentId) return <div className="p-4 text-center text-yellow-500">No document ID provided</div>;
    if (loading) return <div className="p-4 text-center">Loading content...</div>;
    if (error) return <div className="p-4 text-center text-red-500">{error}</div>;

    // PDF viewer
    if (contentType === 'application/pdf' && fileUrl) {
        return (
            <Card className="border-0 shadow-none h-full flex flex-col">
                <CardContent className="flex-1 overflow-hidden p-0">
                    <PDFViewer file={fileUrl} />
                </CardContent>
            </Card>
        );
    }

    // Markdown renderer
    if (contentType?.includes('markdown')) {
        return (
            <Card className="border-0 shadow-none h-full flex flex-col">
                <CardContent className="flex-1 overflow-hidden p-0">
                    <ScrollArea className="h-full px-6 py-6">
                        <div className="max-w-4xl mx-auto prose prose-lg dark:prose-invert">
                            <ReactMarkdown>{content}</ReactMarkdown>
                        </div>
                    </ScrollArea>
                </CardContent>
            </Card>
        );
    }

    // Plain text fallback
    return (
        <Card className="border-0 shadow-none h-full flex flex-col">
            <CardContent className="flex-1 overflow-hidden p-0">
                <ScrollArea className="h-full px-6 py-6">
                    <div className="max-w-4xl mx-auto whitespace-pre-wrap font-serif text-lg leading-relaxed text-foreground/80">
                        {content}
                    </div>
                </ScrollArea>
            </CardContent>
        </Card>
    );
};

export default ContentTab;
