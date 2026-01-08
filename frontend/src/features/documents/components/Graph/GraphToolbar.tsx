import React from 'react';
import {
    MousePointer2,
    Network,
    Wand2,
    Scissors,
    Download,
    Upload,
    HelpCircle
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@/components/ui/tooltip';

export type GraphMode = 'view' | 'connect' | 'heal' | 'prune' | 'merge';

interface GraphToolbarProps {
    mode: GraphMode;
    onModeChange: (mode: GraphMode) => void;
    onBackup?: () => void;
    onRestore?: () => void;
}

export const GraphToolbar: React.FC<GraphToolbarProps> = ({
    mode,
    onModeChange,
    onBackup,
    onRestore
}) => {

    const tools = [
        {
            id: 'view',
            icon: MousePointer2,
            label: 'Select / View',
            desc: 'View node details and navigate'
        },
        {
            id: 'connect',
            icon: Network,
            label: 'Connect',
            desc: 'Draw connections between nodes'
        },
        {
            id: 'heal',
            icon: Wand2,
            label: 'Heal',
            desc: 'AI-assisted connection suggestions'
        },
        {
            id: 'prune',
            icon: Scissors,
            label: 'Prune',
            desc: 'Remove edges or nodes'
        },
        {
            id: 'merge',
            icon: Upload, // best approximation for merge
            label: 'Merge',
            desc: 'Merge duplicates nodes'
        }
    ] as const;

    return (
        <div className="absolute top-4 left-4 z-10 flex flex-col gap-2 bg-background/80 backdrop-blur-sm p-1.5 rounded-lg border shadow-sm">
            <TooltipProvider>
                {tools.map((tool) => (
                    <Tooltip key={tool.id}>
                        <TooltipTrigger asChild>
                            <Button
                                variant={mode === tool.id ? "default" : "ghost"}
                                size="icon"
                                className={`h-8 w-8 ${mode === tool.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
                                onClick={() => onModeChange(tool.id)}
                            >
                                <tool.icon className="h-4 w-4" />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="right">
                            <p className="font-semibold">{tool.label}</p>
                            <p className="text-xs text-muted-foreground">{tool.desc}</p>
                        </TooltipContent>
                    </Tooltip>
                ))}

                {(onBackup || onRestore) && <div className="h-px bg-border my-1" />}

                {onBackup && (
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground" onClick={onBackup}>
                                <Download className="h-4 w-4" />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="right">Backup Graph</TooltipContent>
                    </Tooltip>
                )}
                {onRestore && (
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground" onClick={onRestore}>
                                <Upload className="h-4 w-4" />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="right">Restore Graph</TooltipContent>
                    </Tooltip>
                )}
            </TooltipProvider>

            <div className="absolute top-0 left-full ml-2 bg-secondary/80 text-secondary-foreground text-[10px] px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
                {mode.toUpperCase()} MODE
            </div>
        </div>
    );
};
