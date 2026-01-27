import { QualityScore } from '../store'

interface QualityBadgeProps {
    score: QualityScore
}

export default function QualityBadge({ score }: QualityBadgeProps) {
    const getColor = (value: number) => {
        if (value >= 80) return 'text-success bg-success-muted'
        if (value >= 60) return 'text-warning bg-warning-muted'
        return 'text-destructive bg-destructive/10'
    }

    const getEmoji = (value: number) => {
        if (value >= 80) return '🟢'
        if (value >= 60) return '🟡'
        return '🔴'
    }

    return (
        <div
            className="inline-flex items-center space-x-2 text-xs"
        // Adjusted transform to fit new layout if needed, keeping generic for now
        >
            <span>{getEmoji(score.total)}</span>
            <span className={`px-2 py-1 rounded-full font-medium ${getColor(score.total)}`}>
                Quality: {score.total.toFixed(0)}%
            </span>
        </div>
    )
}
