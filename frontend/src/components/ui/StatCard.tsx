

import { LucideIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

interface StatCardProps {
    icon: LucideIcon;
    label: string;
    value: number | string;
    subLabel?: string;
    isString?: boolean;
    trend?: {
        value: number;
        isPositive: boolean;
    };
    description?: string;
    className?: string; // Allow custom styling
}

export function StatCard({
    icon: Icon,
    label,
    value,
    subLabel,
    isString,
    trend,
    description,
    className
}: StatCardProps) {
    return (
        <Card className={className}>
            <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2 text-muted-foreground">
                        <Icon className="w-4 h-4" />
                        <span className="text-sm font-medium">{label}</span>
                    </div>
                    {trend && (
                        <Badge variant={trend.isPositive ? 'success' : 'destructive'}>
                            {trend.isPositive ? '+' : ''}{trend.value}%
                        </Badge>
                    )}
                </div>
                <div className="text-2xl font-bold">
                    {isString ? value : typeof value === 'number' ? value.toLocaleString() : value}
                </div>
                {(subLabel || description) && (
                    <div className="mt-1 flex flex-col gap-0.5">
                        {subLabel && <div className="text-sm text-muted-foreground">{subLabel}</div>}
                        {description && <div className="text-xs text-muted-foreground/80">{description}</div>}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}

export default StatCard;
