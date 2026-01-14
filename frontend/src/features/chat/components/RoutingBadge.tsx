import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { GitBranch } from 'lucide-react';
import type { RoutingInfo } from '../store';

interface RoutingBadgeProps {
    routingInfo: RoutingInfo;
}

const RoutingBadge: React.FC<RoutingBadgeProps> = ({ routingInfo }) => {
    const { categories, confidence } = routingInfo;

    // Safety check
    if (!categories || categories.length === 0) {
        return null;
    }

    // Determine confidence level and color
    const getConfidenceColor = (conf: number): string => {
        if (conf >= 0.8) return 'rgb(34, 197, 94)'; // green-500
        if (conf >= 0.6) return 'rgb(234, 179, 8)'; // yellow-500
        return 'rgb(249, 115, 22)'; // orange-500
    };

    const getConfidenceLabel = (conf: number): string => {
        if (conf >= 0.8) return 'High confidence';
        if (conf >= 0.6) return 'Medium confidence';
        return 'Low confidence';
    };

    const confidenceColor = getConfidenceColor(confidence);
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
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            padding: '2px 8px',
                            borderRadius: '12px',
                            backgroundColor: `${confidenceColor}15`,
                            border: `1px solid ${confidenceColor}40`,
                            fontSize: '0.75rem',
                            fontWeight: 500,
                            color: confidenceColor,
                            cursor: 'help',
                        }}
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
