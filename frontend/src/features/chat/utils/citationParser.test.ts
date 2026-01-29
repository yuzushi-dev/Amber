
import { describe, it, expect } from 'vitest';
import { parseCitations } from './citationParser';

describe('parseCitations', () => {
    it('parses single citation [[Source:1]]', () => {
        const { processedContent, citations } = parseCitations('Check [[Source:1]]', 'msg1');
        expect(citations).toHaveLength(1);
        expect(citations[0].label).toBe('1');
        expect(processedContent).toContain('[Source: 1](#citation-msg1-0)');
    });

    it('parses multiple IDs in one bracket [[Source:1, 2]]', () => {
        const { processedContent, citations } = parseCitations('Check [[Source:1, 2]]', 'msg1');
        expect(citations).toHaveLength(2);
        expect(citations[0].label).toBe('1');
        expect(citations[1].label).toBe('2');
        expect(processedContent).toContain('[Source: 1](#citation-msg1-0)');
        expect(processedContent).toContain('[Source: 2](#citation-msg1-1)');
    });

    it('parses redundant Source prefix inside bracket [[Source:1, Source:2]]', () => {
        const { processedContent, citations } = parseCitations('Check [[Source:1, Source:2]]', 'msg1');
        expect(citations).toHaveLength(2);
        expect(citations[0].label).toBe('1');
        expect(citations[1].label).toBe('2');
        expect(processedContent).toContain('[Source: 1](#citation-msg1-0)');
    });

    it('ignores plain text Source:1 without brackets', () => {
        const { processedContent, citations } = parseCitations('Check Source:1 inline', 'msg1');
        expect(citations).toHaveLength(0);
        expect(processedContent).toBe('Check Source:1 inline');
    });

    it('handles complex mix', () => {
        const input = 'Start [[Source:1]] then [[Source: 2, 3]] end';
        const { processedContent, citations } = parseCitations(input, 'msg1');
        expect(citations).toHaveLength(3);
        expect(citations[0].label).toBe('1');
        expect(citations[1].label).toBe('2');
        expect(citations[2].label).toBe('3');
        expect(processedContent).toContain('[Source: 1](#citation-msg1-0)');
        expect(processedContent).toContain('[Source: 2](#citation-msg1-1)');
    });
});
