
import { LucideIcon } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';

export type StatColor = 'primary' | 'amber' | 'blue' | 'green' | 'red' | 'yellow' | 'purple' | 'indigo' | 'orange';

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
    className?: string;
    color?: StatColor;
    delay?: number;
}

const colorMap: Record<StatColor, { bg: string, text: string }> = {
    primary: { bg: 'bg-primary/10', text: 'text-primary' },
    amber: { bg: 'bg-primary/10', text: 'text-primary' },
    blue: { bg: 'bg-chart-1/10', text: 'text-chart-1' },
    green: { bg: 'bg-success-muted', text: 'text-success' },
    red: { bg: 'bg-destructive/10', text: 'text-destructive' },
    yellow: { bg: 'bg-warning-muted', text: 'text-warning' },
    purple: { bg: 'bg-chart-3/10', text: 'text-chart-3' },
    indigo: { bg: 'bg-chart-4/10', text: 'text-chart-4' },
    orange: { bg: 'bg-chart-5/10', text: 'text-chart-5' },
};

export function StatCard({
    icon: Icon,
    label,
    value,
    subLabel,
    isString,
    trend,
    description,
    className,
    color = 'primary',
    delay = 0
}: StatCardProps) {
    const colors = colorMap[color];

    return (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay }} className="h-full">
            <Card className={cn("p-4 flex items-center gap-4 hover:shadow-md transition-[box-shadow] duration-300 ease-out h-full", className)}>
                <div className={cn("p-3 rounded-xl flex-shrink-0", colors.bg)}>
                    <Icon className={cn("h-5 w-5", colors.text)} />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider truncate">{label}</p>
                        {trend && (
                            <Badge variant={trend.isPositive ? 'success' : 'destructive'} className="text-[10px] h-5 px-1.5 flex-shrink-0">
                                {trend.isPositive ? '+' : ''}{trend.value}%
                            </Badge>
                        )}
                    </div>
                    <p className="text-3xl font-bold font-display tracking-tight text-foreground truncate">
                        {isString ? value : typeof value === 'number' ? value.toLocaleString() : value}
                    </p>

                    {(subLabel || description) && (
                        <div className="flex flex-col gap-0.5">
                            {subLabel && <div className="text-xs text-muted-foreground/80 line-clamp-1" title={subLabel}>{subLabel}</div>}
                            {description && <div className="text-[10px] text-muted-foreground/60 line-clamp-2" title={description}>{description}</div>}
                        </div>
                    )}
                </div>
            </Card>
        </motion.div>
    );
}

export default StatCard;
