# Amber UI Kit

## Overview

This document captures the Amber UI system as implemented in the frontend codebase. It is a practical reference for designers and frontend engineers who need to build new features quickly while keeping the product consistent.

Scope:
- Foundations (tokens, typography, motion, and data visualization)
- Component catalog with usage and accessibility notes
- Core application patterns (shells, navigation, chat, documents)
- Accessibility and visual QA checklists

This UI kit reflects the current dark theme implementation. Light mode tokens exist but are not documented here.

## Table of Contents

- Foundations
- Components
- Patterns
- Accessibility And QA
- Change Log

## Foundations

### Color Tokens

Colors are defined as CSS variables in `frontend/src/styles/globals.css` and consumed through Tailwind token aliases in `frontend/tailwind.config.js`. Use HSL tokens via Tailwind classes (for example `bg-background`, `text-foreground`, `border-border`, `bg-primary/10`). Avoid hard-coded hex values so theme changes stay centralized.

| Category | Tokens | Usage |
| --- | --- | --- |
| Core surfaces and text | background, foreground, card, popover, primary, secondary, muted, accent, border, input, ring, destructive | Base UI surfaces, text, borders, focus rings |
| Brand scale | amber-50..900, surface-950..400, accent-honey, accent-bronze, accent-copper, accent-flame, accent-rust, accent-sienna | Brand accents, rich gradients, ambient surfaces |
| Semantic states | success, success-foreground, success-muted; warning, warning-foreground, warning-muted; info, info-foreground, info-muted | Status messaging, badges, alerts |
| Data visualization | chart-1..10; node-entity, node-document, node-chunk, node-community, node-relationship; edge-default, edge-strong, edge-weak, edge-highlight | Charts and graph styling |

Guidance:
- Use semantic tokens first. Reach for brand scales only when you need non-semantic emphasis.
- Prefer opacity variants (`bg-primary/10`, `text-foreground/70`) instead of inventing new colors.
- Dark theme is the primary target. The `.light` overrides exist but are not documented here.

### Surface And Elevation

The surface system uses warm dark backgrounds with glass effects. Common layers:
- Base: `bg-background`, `text-foreground` for main pages.
- Raised: `bg-card` or `bg-background/40` with `backdrop-blur` for panels.
- Overlay: `bg-background/80` with `backdrop-blur-xl` and `border-border` for dialogs and sheets.
- Strokes: use `border-border` or subtle `border-white/5` for glass edges.

Recommended patterns:
- Use the `Card` component for consistent padding, rounding, and hover elevation.
- For floating UI (dock, tooltips, dialogs) combine background alpha, blur, and a thin border to keep hierarchy clear.

### Typography

Font families are defined in `frontend/src/styles/globals.css`:
- `--font-sans`: Inter for body text.
- `--font-display`: Plus Jakarta Sans for headings and emphasis.
- `--font-mono`: JetBrains Mono for code and IDs.

Defaults:
- Headings (`h1` to `h6`) use the display font via global styles.
- Use `font-display` for branded headings in custom components.

Type usage (recommended):
- Text labels and metadata: `text-xs` or `text-[10px]` with `font-medium`.
- Body copy: `text-sm` with `leading-relaxed` when needed.
- Section headers: `text-lg` or `text-xl` with `font-semibold`.
- Page titles and hero numbers: `text-2xl` to `text-3xl` with `font-display`.

### Spacing And Layout

Spacing follows the Tailwind 4px scale. Use `p-4`, `gap-4`, and `space-y-4` as the baseline rhythm.

Layout conventions:
- App shells use `h-screen` with `flex` and `overflow-hidden` to control scroll containers.
- Content pages often center at `max-w-6xl` with `mx-auto`.
- Stats and cards use grid layouts with consistent gaps (for example `grid-cols-2 md:grid-cols-3 lg:grid-cols-5`).

### Radius And Borders

Base radius is controlled by `--radius` (0.5rem). Tailwind aliases map to this:
- `rounded-md` for inputs, buttons, and compact controls.
- `rounded-lg` for small containers.
- `rounded-xl` for cards and major panels.
- `rounded-2xl` for dock, sheets, and hero surfaces.

Border color should use `border-border` for standard surfaces or subtle white strokes for glass (`border-white/5`).

### Shadows And Glows

Custom glow utilities are defined in `frontend/src/styles/globals.css`:
- `shadow-glow-sm`, `shadow-glow`, `shadow-glow-lg` for primary emphasis.
- `shadow-glow-success`, `shadow-glow-warning`, `shadow-glow-destructive`, `shadow-glow-info` for semantic states.

Use glows sparingly on primary CTAs, active cards, and status feedback. Prefer soft `shadow-lg` for standard elevation.

### Motion

Motion is subtle and focuses on focus, hover, and state transitions. Guidance:
- Prefer property-specific transitions over `transition-all` when possible.
- Typical durations in the UI are 150ms to 300ms. Use 500ms only for large surface transitions.
- Respect `prefers-reduced-motion` (handled in `frontend/src/styles/globals.css`).
- Use `tailwindcss-animate` for entry and exit transitions.

### Iconography

Iconography uses `lucide-react`. Standard sizes:
- 16px (`w-4 h-4`) for inline and secondary actions.
- 20px (`w-5 h-5`) for buttons and list items.
- 24px (`w-6 h-6`) for navigation and dock icons.
- 32px (`w-8 h-8`) for empty states or hero visuals.

Match icon color to the surrounding text or a semantic token.

### Data Visualization And Graphs

Data visualization tokens are defined alongside core colors:
- Charts: `chart-1` to `chart-10`.
- Graph nodes: `node-entity`, `node-document`, `node-chunk`, `node-community`, `node-relationship`.
- Graph edges: `edge-default`, `edge-strong`, `edge-weak`, `edge-highlight`.

Graph UI is primarily implemented in `frontend/src/features/graph` and `frontend/src/features/documents/components/Graph`. Use node and edge tokens for consistency, and highlight selections with primary glows and rings.

## Components

Components live in `frontend/src/components/ui`. Feedback components live in `frontend/src/components/feedback`.

### Accordion

Purpose: Collapsible content sections for dense information.
Variants:
- Radix `type="single"` or `type="multiple"` with optional `collapsible`.
Props:
- `Accordion`, `AccordionItem`, `AccordionTrigger`, `AccordionContent` forward Radix props.
Usage:
```tsx
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion"

<Accordion type="single" collapsible>
  <AccordionItem value="metadata">
    <AccordionTrigger>Metadata</AccordionTrigger>
    <AccordionContent>...</AccordionContent>
  </AccordionItem>
</Accordion>
```
Accessibility:
- Use descriptive trigger text.
- Keep heading hierarchy consistent.

### Alert

Purpose: Status messaging with semantic variants.
Variants:
- `variant`: default, destructive, success, warning, info.
- `glow`: boolean for semantic glow.
Props:
- `showIcon?: boolean`, `icon?: ReactNode`, `dismissible?: boolean`, `onDismiss?: () => void`.
- Extends `HTMLDivElement` props.
Usage:
```tsx
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"

<Alert variant="warning" glow dismissible onDismiss={() => setOpen(false)}>
  <AlertTitle>Heads up</AlertTitle>
  <AlertDescription>Check your connector settings.</AlertDescription>
</Alert>
```
Accessibility:
- Uses `role="alert"` by default. Keep text concise.

### Badge

Purpose: Compact status and metadata label.
Variants:
- `variant`: default, secondary, destructive, outline, success, warning, info.
Props:
- Extends `HTMLDivElement` props.
Usage:
```tsx
import { Badge } from "@/components/ui/badge"

<Badge variant="success">Indexed</Badge>
```
Accessibility:
- For interactive chips, use a button or link instead of `Badge`.

### Button

Purpose: Primary and secondary actions.
Variants:
- `variant`: default, destructive, outline, secondary, ghost, link.
- `size`: default, sm, lg, icon.
Props:
- `asChild?: boolean` for Slot rendering.
- Extends `ButtonHTMLAttributes`.
Usage:
```tsx
import { Button } from "@/components/ui/button"

<Button variant="secondary" size="sm">Save</Button>
```
Accessibility:
- Provide text or `aria-label` for icon-only buttons.

### Card

Purpose: Elevated content container.
Props:
- `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter`.
Usage:
```tsx
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"

<Card>
  <CardHeader><CardTitle>Summary</CardTitle></CardHeader>
  <CardContent>...</CardContent>
</Card>
```
Accessibility:
- Ensure headings are meaningful within the page structure.

### Checkbox

Purpose: Boolean selection.
Props:
- `onCheckedChange?: (checked: boolean) => void`.
- Extends `InputHTMLAttributes<HTMLInputElement>`.
Usage:
```tsx
import { Checkbox } from "@/components/ui/checkbox"

<Checkbox checked={value} onCheckedChange={setValue} />
```
Accessibility:
- Pair with a `<label>` or `aria-label`.

### Collapsible

Purpose: Show and hide content blocks without headers.
Props:
- `Collapsible`, `CollapsibleTrigger`, `CollapsibleContent` (Radix).
Usage:
```tsx
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible"

<Collapsible>
  <CollapsibleTrigger>Show details</CollapsibleTrigger>
  <CollapsibleContent>...</CollapsibleContent>
</Collapsible>
```
Accessibility:
- Ensure trigger text indicates expanded content.

### Constellation Loader

Purpose: Branded canvas loading animation.
Props:
- No props. Renders a full-size canvas that animates and responds to drag.
Usage:
```tsx
import ConstellationLoader from "@/components/ui/constellation-loader"

<div className="fixed inset-0 bg-black">
  <ConstellationLoader />
</div>
```
Accessibility:
- Pair with a text status nearby (`aria-live`) for loading states.

### Date Format

Purpose: Consistent date formatting.
Props:
- `date: string | Date | null | undefined`.
- `mode?: "full" | "short"`.
- `className?: string`.
Usage:
```tsx
import { FormatDate } from "@/components/ui/date-format"

<FormatDate date={createdAt} mode="short" />
```
Accessibility:
- Short mode includes a full date in the `title` attribute.

### Dialog

Purpose: Modal overlays and confirmations.
Props:
- `Dialog` expects `open` and `onOpenChange`.
- `DialogContent`, `DialogHeader`, `DialogTitle`, `DialogDescription`, `DialogBody`, `DialogFooter`, `DialogClose`.
- `ConfirmDialog` props: `open`, `onOpenChange`, `title`, `description`, `confirmText`, `cancelText`, `onConfirm`, `variant`, `loading`.
Usage:
```tsx
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"

<Dialog open={open} onOpenChange={setOpen}>
  <DialogContent>
    <DialogHeader><DialogTitle>Delete document</DialogTitle></DialogHeader>
    <DialogFooter>...</DialogFooter>
  </DialogContent>
</Dialog>
```
Accessibility:
- Uses `role="dialog"` and `aria-modal`. Keep focusable controls inside.

### Empty State

Purpose: Friendly placeholder when no data is present.
Props:
- `icon?: ReactNode`, `title: string`, `description?: string`, `actions?: ReactNode`, `className?: string`.
Usage:
```tsx
import EmptyState from "@/components/ui/EmptyState"

<EmptyState
  title="No documents yet"
  description="Upload a file to get started."
/>
```
Accessibility:
- Uses `role="status"`. Keep title and description concise.

### Error Boundary

Purpose: Catch rendering errors and display fallback UI.
Props:
- `children: ReactNode`, `fallback?: ReactNode`.
Usage:
```tsx
import ErrorBoundary from "@/components/ui/ErrorBoundary"

<ErrorBoundary>
  <Section />
</ErrorBoundary>
```
Accessibility:
- Default fallback uses `role="alert"` and `aria-live="assertive"`.

### Form

Purpose: React Hook Form helpers with consistent labeling and errors.
Props:
- `Form` is `FormProvider`.
- `FormField` wraps `Controller` props.
- `FormItem`, `FormLabel`, `FormControl`, `FormDescription`, `FormMessage`.
Usage:
```tsx
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form"
import { Input } from "@/components/ui/input"

<Form {...form}>
  <FormField
    name="title"
    control={form.control}
    render={({ field }) => (
      <FormItem>
        <FormLabel>Title</FormLabel>
        <FormControl><Input {...field} /></FormControl>
        <FormMessage />
      </FormItem>
    )}
  />
</Form>
```
Accessibility:
- `FormControl` sets `aria-invalid` and `aria-describedby` for errors.

### Input

Purpose: Single-line text input.
Props:
- Extends `InputHTMLAttributes`.
Usage:
```tsx
import { Input } from "@/components/ui/input"

<Input placeholder="Search" />
```
Accessibility:
- Pair with `Label` and use `id`/`htmlFor`.

### Label

Purpose: Form labels with consistent typography.
Props:
- Radix label props.
Usage:
```tsx
import { Label } from "@/components/ui/label"

<Label htmlFor="query">Query</Label>
```
Accessibility:
- Use `htmlFor` to associate with inputs.

### Progress

Purpose: Simple progress indicator.
Props:
- `value?: number` (default 0), `max?: number` (default 100).
Usage:
```tsx
import { Progress } from "@/components/ui/progress"

<Progress value={45} />
```
Accessibility:
- Sets `role="progressbar"` and `aria-valuenow`.

### Animated Progress

Purpose: Branded progress bar with staged labels.
Props:
- `value: number` (0 to 100).
- `stages?: { label: string; threshold: number }[]`.
- `showPercentage?: boolean`, `size?: "sm" | "md" | "lg"`.
Usage:
```tsx
import AnimatedProgress from "@/components/ui/animated-progress"

<AnimatedProgress
  value={62}
  stages={[{ label: "Indexing", threshold: 0 }, { label: "Finalizing", threshold: 60 }]}
/>
```
Accessibility:
- Pair with adjacent text for screen readers if used as the only indicator.

### Scroll Area

Purpose: Scroll container with custom scrollbars.
Props:
- Extends `HTMLDivElement`.
Usage:
```tsx
import { ScrollArea } from "@/components/ui/scroll-area"

<ScrollArea className="max-h-80">...</ScrollArea>
```
Accessibility:
- Ensure scrollable regions have visible focus management if interactive content is inside.

### Select

Purpose: Single selection dropdown (Radix).
Props:
- `Select`, `SelectTrigger`, `SelectValue`, `SelectContent`, `SelectItem`, `SelectLabel`, `SelectSeparator`.
Usage:
```tsx
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select"

<Select value={value} onValueChange={setValue}>
  <SelectTrigger><SelectValue placeholder="Pick one" /></SelectTrigger>
  <SelectContent>
    <SelectItem value="a">Option A</SelectItem>
  </SelectContent>
</Select>
```
Accessibility:
- Radix handles keyboard and ARIA roles. Provide clear option labels.

### Skeleton

Purpose: Loading placeholder blocks.
Props:
- Extends `HTMLDivElement`.
Usage:
```tsx
import { Skeleton } from "@/components/ui/skeleton"

<Skeleton className="h-6 w-40" />
```
Accessibility:
- Use alongside `aria-busy` on the container for clarity.

### Slider

Purpose: Numeric range control (Radix).
Props:
- `showValue?: boolean`, `formatLabel?: (value: number) => string`.
- Accepts Radix slider props (`value`, `defaultValue`, `onValueChange`).
Usage:
```tsx
import { Slider } from "@/components/ui/slider"

<Slider value={[25]} onValueChange={setValue} showValue />
```
Accessibility:
- Provide labels and min/max context near the control.

### Stat Card

Purpose: Metric display with icon and trend.
Props:
- `icon`, `label`, `value`, `subLabel?`, `trend?`, `description?`, `color?`, `delay?`.
Usage:
```tsx
import StatCard from "@/components/ui/StatCard"
import { Activity } from "lucide-react"

<StatCard icon={Activity} label="Queries" value={1240} trend={{ value: 12, isPositive: true }} />
```
Accessibility:
- Ensure labels are meaningful and not only color dependent.

### Switch

Purpose: Toggle for boolean settings (Radix).
Props:
- Accepts Radix switch props (`checked`, `onCheckedChange`, `disabled`).
Usage:
```tsx
import { Switch } from "@/components/ui/switch"

<Switch checked={enabled} onCheckedChange={setEnabled} />
```
Accessibility:
- Pair with a label or `aria-label`.

### Table

Purpose: Consistent table styling.
Props:
- `Table`, `TableHeader`, `TableBody`, `TableFooter`, `TableRow`, `TableHead`, `TableCell`, `TableCaption`.
Usage:
```tsx
import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from "@/components/ui/table"

<Table>
  <TableHeader>
    <TableRow><TableHead>Name</TableHead></TableRow>
  </TableHeader>
  <TableBody>
    <TableRow><TableCell>Amber</TableCell></TableRow>
  </TableBody>
</Table>
```
Accessibility:
- Use `TableCaption` for summaries when needed.

### Tabs

Purpose: Section switching within a view (Radix).
Props:
- `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent`.
Usage:
```tsx
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"

<Tabs defaultValue="overview">
  <TabsList>
    <TabsTrigger value="overview">Overview</TabsTrigger>
  </TabsList>
  <TabsContent value="overview">...</TabsContent>
</Tabs>
```
Accessibility:
- Use concise tab labels and avoid overflow.

### Textarea

Purpose: Multi-line input.
Props:
- Extends `TextareaHTMLAttributes`.
Usage:
```tsx
import { Textarea } from "@/components/ui/textarea"

<Textarea rows={4} placeholder="Add a note" />
```
Accessibility:
- Use `Label` and helper text for guidance.

### Tooltip

Purpose: Short contextual hint (Radix).
Props:
- `TooltipProvider`, `Tooltip`, `TooltipTrigger`, `TooltipContent`.
Usage:
```tsx
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip"

<Tooltip>
  <TooltipTrigger asChild><button>?</button></TooltipTrigger>
  <TooltipContent>More info</TooltipContent>
</Tooltip>
```
Accessibility:
- Use for short hints, not essential content.

### Feedback Components

Purpose: Page-level loading and error feedback.
Components:
- `LoadingState` with `message?: string`.
- `EmptyState` with `icon`, `title`, `description`, `action?`.
- `ErrorBoundary` with `fallback?`.
Usage:
```tsx
import LoadingState from "@/components/feedback/LoadingState"
import EmptyState from "@/components/feedback/EmptyState"
import { ErrorBoundary } from "@/components/feedback/ErrorBoundary"

<LoadingState message="Fetching data" />
```
Accessibility:
- Use `LoadingState` with a clear message and consider `aria-busy` on the parent.

## Patterns

### App Shells

Two primary shells define the product:
- Analyst/Admin shell (`MainLayout`): left contextual sidebar + bottom command dock + optional evidence board.
- Client shell (`ClientLayout`): minimal header and full-screen chat.

Structure:
- Use `h-screen` + nested `overflow-hidden` to control scroll.
- Reserve `main` as the primary scroll container.
- Floating navigation (`CommandDock`) appears at bottom, with hover reveal on desktop and bottom sheet on mobile.

Usage examples:
- Analyst routes are under `/admin/*` and wrap with `MainLayout`.
- Client routes are under `/amber/*` and wrap with `ClientLayout`.

### Navigation

Navigation uses a hybrid pattern:
- Global navigation: `CommandDock` (bottom dock).
- Contextual navigation: `ContextSidebar` (left sidebar).

Guidelines:
- Dock items should map to top-level routes only.
- Sidebar sections should reflect the current area (Data, Metrics, Settings).
- Provide keyboard shortcuts for primary sections (Cmd/Ctrl + 1-5).
- Use `aria-current="page"` on active items (handled in `CommandDock`).

When adding new sections:
- Add to `dockItems` only if it is a primary workspace.
- Update `ContextSidebar` configuration for sub-navigation.

### Chat Experience

Chat is the core interaction surface for both `/admin/chat` and `/amber/chat`.
Key elements:
- Message list with assistant/user styling (`MessageList`, `MessageItem`).
- Input with multiline support and Enter-to-send (`QueryInput`).
- Right-side references panel (`CitationExplorer`) for source inspection.

Guidelines:
- Use a fixed header inside the chat panel for conversation title and actions.
- Streamed responses should use `aria-live="polite"` to announce updates.
- Provide feedback controls (rating, routing, quality badges) only on assistant messages.
- Use `AmberAvatar` for assistant identity and a distinct user badge for user messages.

### Documents Experience

Document workflows live under `/admin/data/*`.
Primary views:
- Document Library (`DocumentLibrary`) with stats cards, search, and list rows.
- Document Detail (`DocumentDetailPage`) with summary, metadata, stats, and graph explorer.
- Upload Wizard (`UploadWizard`) for ingestion progress.

Guidelines:
- Use `Card` for summary and stats modules.
- Keep list rows compact; use a hover reveal for destructive actions.
- Use a Confirm dialog for irreversible actions.
- Show progress with `AnimatedProgress` and stage labels during ingestion.

### Admin And Settings

Admin and settings routes live under `/admin/settings/*` and `/admin/metrics/*`.
Pattern:
- Pages are content-focused and should remain within the Analyst shell.
- Use `PageHeader`/`PageSkeleton` for loading states where available.
- Avoid nested navigation in these sections beyond `ContextSidebar`.

### Forms And Validation

Forms follow a consistent React Hook Form pattern using UI helpers:
- Wrap with `Form` provider.
- Use `FormItem` + `FormLabel` + `FormControl` + `FormMessage`.
- Inputs, selects, and sliders should use `Label` or `FormLabel`.

Guidelines:
- Provide error messages that explain what to change.
- Avoid inline validation while typing unless it prevents invalid state.
- Use `ConfirmDialog` for destructive or irreversible submissions.

## Accessibility And QA

### Accessibility Checklist

Target: WCAG 2.1 AA. Track status in `docs/accessibility_checklist.md` and use this list for day to day reviews.

Checklist:
- Landmarks: one `main` per page, consistent `header` and `nav`.
- Headings: single `h1`, then logical order (`h2` to `h3`).
- Skip link: provide a skip to content link on all shells.
- Keyboard: all interactive elements reachable by Tab, no traps.
- Focus: visible focus ring on all controls, focus order matches DOM.
- Labels: all inputs have labels or `aria-label`.
- Icon-only buttons: always set `aria-label`.
- Images: `alt` text and explicit width and height.
- Color contrast: verify 4.5:1 for text, 3:1 for large text.
- Motion: respect `prefers-reduced-motion` for animations.
- Alerts: `role="alert"` where needed, avoid noisy live regions.
- Modals: trap focus, allow Escape to close, restore focus on close.
- Tables: use `TableHead` and meaningful headers.
- Chat streaming: use `aria-live="polite"` for updates.
- Graph and canvas: provide text guidance and non-visual fallback where possible.

Testing:
- Run axe or DevTools Accessibility.
- Keyboard-only pass.
- Screen reader pass (VoiceOver or NVDA).
- 200 percent zoom.

### UX And Visual QA Checklist

Checklist:
- Layout: no unexpected scrollbars, sticky headers stay visible.
- Spacing: 4px rhythm, consistent padding and gap scale.
- Typography: headings use display font, body uses `text-sm`.
- States: loading, empty, and error states are present.
- Actions: destructive actions always require confirmation.
- Forms: helper text and error messages are clear.
- Components: hover and focus states are visible.
- Motion: transitions feel subtle and consistent across pages.
- Data: numbers formatted with locale formatting where shown.
- Graphs: node and edge colors match tokens, selection is obvious.
- Mobile: dock becomes bottom sheet, touch targets are at least 44px.

## Change Log

| Date | Change | Notes |
| --- | --- | --- |
| 2026-01-27 | Initial UI kit draft | Derived from current frontend implementation |
