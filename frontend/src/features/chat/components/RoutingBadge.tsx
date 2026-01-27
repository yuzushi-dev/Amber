import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { GitBranch } from 'lucide-react';
import type { RoutingInfo } from '../store';
import { cn } from '@/lib/utils';

interface RoutingBadgeProps {
    routingInfo: RoutingInfo;
}

const RoutingBadge: React.FC<RoutingBadgeProps> = ({ routingInfo }) => {
    const { categories, confidence } = routingInfo;

    // Safety check
    if (!categories || categories.length === 0) {
        return null;
    }

    const confidenceTone = confidence >= 0.8 ? 'success' : confidence >= 0.6 ? 'warning' : 'destructive';
    const badgeClassName = cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium cursor-help',
        confidenceTone === 'success' && 'bg-success/10 border-success/40 text-success',
        confidenceTone === 'warning' && 'bg-warning/10 border-warning/40 text-warning',
        confidenceTone === 'destructive' && 'bg-destructive/10 border-destructive/40 text-destructive'
    );

    const getConfidenceLabel = (conf: number): string => {
        if (conf >= 0.8) return 'High confidence';
        if (conf >= 0.6) return 'Medium confidence';
        return 'Low confidence';
    };

    const confidenceLabel = getConfidenceLabel(confidence);

    // Format categories for display
    const categoryDisplay = categories.map((cat) => {
        // Capitalize and replace underscores/hyphens with spaces
        return cat
            .split(/[-_]/)
            .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    });

    return (
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger asChild>
                    <div
                        className={badgeClassName}
                    >
                        <GitBranch size={14} />
                        <span>{categoryDisplay[0]}{categories.length > 1 ? ` +${categories.length - 1}` : ''}</span>
                    </div>
                </TooltipTrigger>
                <TooltipContent>
                    <div className="text-xs">
                        <div className="font-semibold mb-1">
                            {confidenceLabel} ({(confidence * 100).toFixed(0)}%)
                        </div>
                        <div>
                            {categories.length > 1 ? 'Categories:' : 'Category:'} {categoryDisplay.join(', ')}
                        </div>
                    </div>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
};

export default RoutingBadge;
