import React, { useState, useRef } from "react";
import { Search, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface GraphSearchInputProps {
    onSearch: (query: string) => void;
    onClear?: () => void;
    onFocusChange?: (isFocused: boolean) => void;
    className?: string;
    isSearching?: boolean;
}

export const GraphSearchInput: React.FC<GraphSearchInputProps> = ({
    onSearch,
    onClear,
    onFocusChange,
    className,
    isSearching
}) => {
    const [query, setQuery] = useState("");
    const [isFocused, setIsFocused] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    const handleFocus = () => {
        setIsFocused(true);
        onFocusChange?.(true);
    };

    const handleBlur = () => {
        setIsFocused(false);
        onFocusChange?.(false);
    };

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (query.trim()) {
            onSearch(query);
        }
    };

    const handleClear = () => {
        setQuery("");
        onClear?.();
        inputRef.current?.focus();
    };

    return (
        <form
            onSubmit={handleSubmit}
            className={cn(
                "relative flex items-center w-full max-w-xl transition-[transform] duration-300 ease-in-out rounded-2xl",
                isFocused ? "scale-105" : "scale-100",
                className
            )}
        >
            <div className="relative w-full group">
                <div className={cn(
                    "absolute inset-0 bg-gradient-to-r from-primary/20 to-primary/10 rounded-2xl blur-xl transition-opacity duration-500",
                    isFocused ? "opacity-100" : "opacity-0"
                )} />

                <div className={cn(
                    "relative flex items-center bg-surface-900/80 backdrop-blur-xl border border-white/5 rounded-2xl shadow-2xl transition-[background-color,border-color,box-shadow] duration-300 ease-out",
                    isFocused ? "ring-2 ring-primary/50 border-primary/50 bg-surface-950/90" : "hover:bg-surface-800/80"
                )}>
                    <Search className={cn(
                        "ml-4 w-5 h-5 transition-colors duration-300",
                        isFocused ? "text-primary" : "text-muted-foreground"
                    )} />

                    <Input
                        ref={inputRef}
                        type="text"
                        placeholder="Search global knowledge graph\u2026"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onFocus={handleFocus}
                        onBlur={handleBlur}
                        name="graph-search"
                        autoComplete="off"
                        aria-label="Search global knowledge graph"
                        className="flex-1 h-14 bg-transparent border-none text-lg placeholder:text-muted-foreground/50 focus-visible:ring-0 focus-visible:ring-offset-0 px-4"
                    />

                    <div className="flex items-center gap-2 mr-2">
                        {isSearching && (
                            <Loader2 className="w-5 h-5 text-primary animate-spin" />
                        )}

                        {query && !isSearching && (
                            <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                onClick={handleClear}
                                className="h-8 w-8 hover:bg-foreground/10 rounded-full"
                                aria-label="Clear search"
                            >
                                <X className="w-4 h-4 text-muted-foreground" />
                            </Button>
                        )}

                        {!isFocused && !query && (
                            <div className="hidden sm:flex items-center gap-1 px-2 py-1 bg-foreground/5 rounded-md border border-white/5 mx-2">
                                <span className="text-xs text-muted-foreground font-mono">/</span>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </form>
    );
};
