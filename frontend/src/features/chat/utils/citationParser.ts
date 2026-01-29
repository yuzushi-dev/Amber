
import { Citation } from '../store/citationStore';

export function parseCitations(content: string, messageId: string): { processedContent: string, citations: Citation[] } {
    const citations: Citation[] = [];

    // Improved regex strategy:
    // Capture `[[ ... ]]` blocks that start with "Source" (case insensitive)
    // Then extract all numbers from that block.
    // This handles:
    // [[Source: 1, 2]]
    // [[Source: 1, Source: 2]]
    // [[Source 1 2]]

    const citationBlockRegex = /\[\[\s*(?:Source|Sources).*?\]\]/gi;

    const processedContent = content.replace(citationBlockRegex, (match) => {
        // Extract all distinct numeric sequences from the match
        // We match \d+
        const ids = match.match(/\d+/g);

        if (!ids || ids.length === 0) return match;

        // Deduplicate just in case
        const uniqueIds = Array.from(new Set(ids));

        const links = uniqueIds.map((id: string) => {
            const uniqueId = `${messageId}-${citations.length}`;
            citations.push({
                id: uniqueId,
                type: 'Source',
                label: id,
                value: id,
                content: match
            });
            return `[Source: ${id}](#citation-${uniqueId})`;
        });

        return links.join(' ');
    });

    return { processedContent, citations };
}
