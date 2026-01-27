# UI Kit Fix Log

## Purpose
Track UX/UI kit violations and fixes applied to align the codebase with `docs/ui-kit.md`.

## Log
| Date | Category | File | Change | Notes |
|------|----------|------|--------|-------|
| 2026-01-27 | Planning | docs/ui-kit-fix-log.md | Created fix log | Initial tracking file |
| 2026-01-27 | Accessibility | frontend/src/components/layout/MainLayout.tsx | Added skip link + main id | Adds keyboard skip target |
| 2026-01-27 | Accessibility | frontend/src/components/layout/ClientLayout.tsx | Added skip link + main id | Adds keyboard skip target |
| 2026-01-27 | Accessibility | frontend/src/features/chat/components/AmberAvatar.tsx | Added width/height attributes | Meets image dimension requirement |
| 2026-01-27 | Motion | frontend/src/components/ui/button.tsx | Replaced transition-all with property-specific transition | Aligns with UI kit motion guidance |
| 2026-01-27 | Accessibility | frontend/src/components/ui/button.tsx | Auto-set aria-label from title for icon buttons | Ensures icon buttons announce labels when title exists |
| 2026-01-27 | Accessibility | frontend/src/features/admin/components/SummariesTable.tsx | Added aria-label to delete icon button | Clarifies destructive action |
| 2026-01-27 | Motion | frontend/src/features/admin/components/SummariesTable.tsx | Replaced transition-all with property-specific transition | Subtle hover transitions |
| 2026-01-27 | Accessibility | frontend/src/features/admin/components/FactsTable.tsx | Added aria-label to delete icon button | Clarifies destructive action |
| 2026-01-27 | Motion | frontend/src/features/admin/components/FactsTable.tsx | Replaced transition-all with property-specific transition | Subtle hover transitions |
| 2026-01-27 | Accessibility | frontend/src/features/admin/components/RecentActivityTable.tsx | Added aria-labels to pagination buttons | Improves keyboard/screen reader nav |
| 2026-01-27 | Accessibility | frontend/src/features/admin/components/QueryLogTable.tsx | Added aria-labels to pagination buttons | Improves keyboard/screen reader nav |
| 2026-01-27 | Accessibility | frontend/src/features/admin/components/TenantManager.tsx | Added aria-label to delete tenant button | Clarifies destructive action |
| 2026-01-27 | Motion | frontend/src/features/admin/components/TenantManager.tsx | Replaced transition-all with property-specific transition | Focused hover transitions |
| 2026-01-27 | Accessibility | frontend/src/features/admin/components/TenantLinkingModal.tsx | Added aria-label to remove tenant button | Clarifies destructive action |
| 2026-01-27 | Motion | frontend/src/features/admin/components/TenantLinkingModal.tsx | Replaced transition-all with property-specific transitions | Subtle hover transitions |
| 2026-01-27 | Accessibility | frontend/src/features/graph/components/GraphHistoryModal.tsx | Added aria-labels to history action buttons | Clarifies apply/reject/undo actions |
| 2026-01-27 | Motion | frontend/src/features/graph/components/GraphSearchInput.tsx | Replaced transition-all with property-specific transition | Aligns with motion guidance |
| 2026-01-27 | Accessibility | frontend/src/features/graph/components/GraphSearchInput.tsx | Added aria-label to clear search button | Improves screen reader support |
| 2026-01-27 | Accessibility | frontend/src/features/documents/components/Graph/GraphToolbar.tsx | Added aria-labels to graph toolbar icon buttons | Ensures tool buttons are announced |
| 2026-01-27 | Accessibility | frontend/src/features/documents/components/Graph/NodeSidebar.tsx | Added aria-label to close button | Ensures close action is announced |
| 2026-01-27 | Accessibility | frontend/src/features/documents/pages/DocumentDetailPage.tsx | Added aria-label to back button | Clarifies navigation control |
| 2026-01-27 | Accessibility | frontend/src/features/documents/components/DocumentTabs/ChunksTab.tsx | Added aria-labels to edit/delete chunk buttons | Clarifies chunk actions |
| 2026-01-27 | Accessibility | frontend/src/features/documents/components/DatabaseSidebarContent.tsx | Added aria-label to delete folder button | Clarifies folder removal |
| 2026-01-27 | Accessibility | frontend/src/features/chat/components/Rating.tsx | Added aria-labels to rating buttons | Clarifies feedback controls |
| 2026-01-27 | Accessibility | frontend/src/features/chat/components/CitationExplorer.tsx | Added aria-label to close button | Clarifies panel dismissal |
| 2026-01-27 | Motion | frontend/src/features/chat/components/CitationExplorer.tsx | Replaced transition-all with property-specific transition | Subtle hover transitions |
| 2026-01-27 | Accessibility | frontend/src/features/auth/components/ApiKeyModal.tsx | Added aria-label to toggle API key visibility | Clarifies visibility control |
| 2026-01-27 | Accessibility | frontend/src/features/graph/pages/GlobalGraphPage.tsx | Added aria-label to settings button | Clarifies maintenance access |
| 2026-01-27 | Accessibility | frontend/src/features/documents/components/UploadWizard.tsx | Added aria-label to close button | Clarifies modal dismissal |
| 2026-01-27 | Accessibility | frontend/src/features/admin/pages/RulesPage.tsx | Added aria-labels to edit/delete buttons | Clarifies rule actions |
| 2026-01-27 | Accessibility | frontend/src/features/admin/pages/CurationPage.tsx | Added aria-label to close drawer button | Clarifies drawer dismissal |
| 2026-01-27 | Accessibility | frontend/src/features/admin/pages/FeedbackPage.tsx | Added aria-labels to verify/reject buttons | Clarifies moderation actions |
| 2026-01-27 | Accessibility | frontend/src/features/admin/pages/FeedbackPage.tsx | Added aria-labels to delete/toggle buttons | Clarifies item actions |
| 2026-01-27 | Motion | frontend/src/components/ui/accordion.tsx | Replaced transition-all with targeted transitions | Keeps accordion motion subtle |
| 2026-01-27 | Motion | frontend/src/components/ui/card.tsx | Replaced transition-all with property-specific transition | Focused hover transitions |
| 2026-01-27 | Motion | frontend/src/components/ui/tabs.tsx | Replaced transition-all with property-specific transition | Aligns tab state transitions |
| 2026-01-27 | Motion | frontend/src/components/ui/progress.tsx | Replaced transition-all with width transition | Focused progress animation |
| 2026-01-27 | Motion | frontend/src/components/ui/StatCard.tsx | Replaced transition-all with box-shadow transition | Focused hover transitions |
| 2026-01-27 | Motion | frontend/src/components/layout/ContextSidebar.tsx | Replaced transition-all with property-specific transitions | Focused sidebar animation |
| 2026-01-27 | Motion | frontend/src/components/layout/CommandDock.tsx | Replaced transition-all with property-specific transitions | Focused dock animations |
| 2026-01-27 | Motion | frontend/src/features/chat/components/ChatContainer.tsx | Replaced transition-all with property-specific transition | Focused container transitions |
| 2026-01-27 | Motion | frontend/src/features/chat/components/MessageItem.tsx | Replaced transition-all with property-specific transition | Focused citation chip transitions |
| 2026-01-27 | Motion | frontend/src/features/evidence/components/SourceCard.tsx | Replaced transition-all with property-specific transition | Focused hover transitions |
| 2026-01-27 | Motion | frontend/src/features/evidence/components/EvidenceBoard.tsx | Replaced transition-all with property-specific transitions | Focused toggle transitions |
| 2026-01-27 | Motion | frontend/src/features/documents/pages/DocumentDetailPage.tsx | Replaced transition-all with property-specific transition | Focused stat card hover |
| 2026-01-27 | Motion | frontend/src/features/documents/components/DocumentLibrary.tsx | Replaced transition-all with property-specific transitions | Focused list and input transitions |
| 2026-01-27 | Motion | frontend/src/features/chat/components/CitationExplorer.tsx | Replaced transition-all with property-specific transitions | Focused citation card transitions |
| 2026-01-27 | Motion | frontend/src/features/chat/components/FeedbackDialog.tsx | Replaced transition-all with property-specific transitions | Focused feedback interactions |
| 2026-01-27 | Motion | frontend/src/features/graph/components/GraphSearchInput.tsx | Replaced transition-all with transform transition | Focused input scaling |
| 2026-01-27 | Motion | frontend/src/features/graph/pages/GlobalGraphPage.tsx | Replaced transition-all with filter transition | Focused blur/grayscale animation |
| 2026-01-27 | Motion | frontend/src/features/admin/pages/FeedbackPage.tsx | Replaced transition-all with property-specific transitions | Focused feedback card transitions |
| 2026-01-27 | Motion | frontend/src/features/admin/pages/RulesPage.tsx | Replaced transition-all with property-specific transitions | Focused stats and empty state transitions |
| 2026-01-27 | Motion | frontend/src/features/admin/components/TenantManager.tsx | Replaced transition-all with property-specific transition | Focused admin card hover |
| 2026-01-27 | Motion | frontend/src/features/admin/components/EmbeddingMigration.tsx | Replaced transition-all with property-specific transitions | Focused progress and action transitions |
| 2026-01-27 | Motion | frontend/src/features/admin/pages/VectorStorePage.tsx | Replaced transition-all with property-specific transition | Focused row hover transitions |
| 2026-01-27 | Motion | frontend/src/features/admin/pages/TokenMetricsPage.tsx | Replaced transition-all with width transition | Focused progress bar animation |
| 2026-01-27 | Motion | frontend/src/features/setup/components/FeatureSetup.tsx | Replaced transition-all with property-specific transition | Focused setup item hover |
| 2026-01-27 | Motion | frontend/src/features/admin/pages/JobsPage.tsx | Replaced transition-all with width transition | Focused job progress animation |
| 2026-01-27 | Motion | frontend/src/features/graph/pages/GlobalGraphPage.tsx | Replaced transition-all with property-specific transitions | Focused maintenance modal transitions |
| 2026-01-27 | Motion | frontend/src/features/admin/pages/LlmSettingsPage.tsx | Replaced transition-all with property-specific transition | Focused save button transitions |
| 2026-01-27 | Motion | frontend/src/features/admin/components/Connectors/ConnectorCard.tsx | Replaced transition-all with property-specific transitions | Focused connector hover effects |
| 2026-01-27 | Motion | frontend/src/features/admin/components/llm/StepConfigDialog.tsx | Replaced transition-all with property-specific transitions | Focused dialog button transitions |
| 2026-01-27 | Motion | frontend/src/features/admin/components/Connectors/ConnectorCard.tsx | Replaced transition-all in action class | Focused connector action hover |
| 2026-01-27 | Motion | frontend/src/features/admin/components/RagasSubPanel.tsx | Replaced transition-all with width transition | Focused progress animation |
| 2026-01-27 | Motion | frontend/src/features/admin/components/llm/GlobalDefaultsCard.tsx | Replaced transition-all with property-specific transition | Focused card hover |
| 2026-01-27 | Motion | frontend/src/features/admin/components/llm/EmbeddingCard.tsx | Replaced transition-all with property-specific transition | Focused card hover |
| 2026-01-27 | Motion | frontend/src/features/admin/components/llm/LlmStepRow.tsx | Replaced transition-all with property-specific transition | Focused row hover |
| 2026-01-27 | Motion | frontend/src/styles/globals.css | Replaced transition-all with property-specific transition | Focused dock item transitions |
| 2026-01-27 | Color Tokens | frontend/src/features/chat/components/Rating.tsx | Replaced green/red classes with success/destructive tokens | Aligns feedback colors to semantic tokens |
| 2026-01-27 | Color Tokens | frontend/src/features/chat/components/MessageItem.tsx | Replaced hard-coded citation colors with semantic tokens | Uses info/primary/warning tokens |
| 2026-01-27 | Color Tokens | frontend/src/features/documents/pages/DocumentDetailPage.tsx | Replaced stats colors with chart tokens | Aligns stats with data visualization palette |
| 2026-01-27 | Color Tokens | frontend/src/features/documents/components/DeleteDocumentModal.tsx | Replaced red classes/shadows with destructive tokens | Aligns destructive modal styling |
| 2026-01-27 | Color Tokens | frontend/src/features/chat/components/MessageItem.tsx | Replaced amber shadow rgba with tokenized shadow | Removes hard-coded shadow color |
| 2026-01-27 | Color Tokens | frontend/src/features/documents/components/Graph/modals/HealingSuggestionsModal.tsx | Replaced amber accents with primary tokens | Aligns healing modal with brand tokens |
| 2026-01-27 | Color Tokens | frontend/src/features/documents/components/Graph/modals/MergeNodesModal.tsx | Replaced amber accents and radio accent with primary tokens | Aligns merge modal with brand tokens |
| 2026-01-27 | Color Tokens | frontend/src/components/ui/select.tsx | Replaced amber focus/hover/check colors with primary tokens | Consistent select interactions |
| 2026-01-27 | Color Tokens | frontend/src/components/ui/StatCard.tsx | Mapped amber variant to primary tokens | Keeps StatCard variants semantic |
| 2026-01-27 | Color Tokens | frontend/src/features/graph/components/GraphSearchInput.tsx | Converted focus ring/loader/gradient to primary tokens | Consistent graph search emphasis |
| 2026-01-27 | Color Tokens | frontend/src/features/graph/components/GraphHistoryModal.tsx | Replaced status badges and action colors with semantic tokens | Aligns history status colors |
| 2026-01-27 | Color Tokens | frontend/src/features/documents/components/DocumentLibrary.tsx | Replaced stats colors with chart tokens and glow utilities | Aligns library stats with data palette |
| 2026-01-27 | Color Tokens | frontend/src/features/setup/components/DatabaseSetup.tsx | Converted maintenance state styling to warning tokens | Aligns setup states with semantics |
| 2026-01-27 | Color Tokens | frontend/src/features/documents/components/BulkDeleteModal.tsx | Replaced red/green status icons with destructive/success tokens | Consistent delete feedback |
| 2026-01-27 | Color Tokens | frontend/src/features/setup/components/FeatureSetup.tsx | Converted warning dialog/installing state to warning/info tokens | Aligns setup emphasis to semantic tokens |
| 2026-01-27 | Color Tokens | frontend/src/features/chat/components/MessageItem.tsx | Updated assistant labels/loader/shadows to primary tokens | Consistent chat branding |
| 2026-01-27 | Color Tokens | frontend/src/features/documents/components/LiveStatusBadge.tsx | Replaced green status dot with success token | Semantic status indicator |
| 2026-01-27 | Color Tokens | frontend/src/features/graph/pages/GlobalGraphPage.tsx | Converted hero/loading/maintenance colors to tokens | Aligns global graph surfaces and highlights |
| 2026-01-27 | Color Tokens | frontend/src/features/documents/components/Graph/GraphToolbar.tsx | Converted pending badge/help icons to primary tokens | Consistent toolbar emphasis |
| 2026-01-27 | Color Tokens | frontend/src/features/auth/components/ApiKeyModal.tsx | Updated super admin icon to primary token | Consistent modal accent |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/JobsAndQueuesPage.tsx | Replaced worker status/progress/cancel colors with semantic tokens | Consistent system status UI |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/JobsPage.tsx | Progress bar uses info token | Aligns job progress color |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/QueuesPage.tsx | Converted error/warning/status counts to semantic tokens | Consistent queue status colors |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/CurationPage.tsx | Converted type badges/stats/actions to semantic tokens | Aligns curation UI to semantics |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/TuningPage.tsx | Converted warning and migration dialog styling to tokens | Aligns tuning alerts to semantics |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/LlmSettingsPage.tsx | Converted warning and migration dialog styling to tokens | Aligns LLM settings alerts to semantics |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/VectorStorePage.tsx | Replaced stats colors with chart tokens | Aligns vector stats with data palette |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/ConnectorDetailPage.tsx | Connected badge uses success tokens | Consistent connector status |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/DataRetentionPage.tsx | Updated export action to primary tokens | Aligns primary CTA styling |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/OptionalFeaturesManager.tsx | Converted status badges/error state to semantic tokens | Consistent feature status styling |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/QueryLogTable.tsx | Replaced neutral/green/red/amber with semantic/surface tokens | Aligns log table palette |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/RecentActivityTable.tsx | Replaced neutral/green/red/amber with semantic/surface tokens | Aligns activity table palette |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/TenantManager.tsx | Converted global admin card to primary tokens and status chips to semantics | Consistent tenant management palette |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/ApiKeyManager.tsx | Updated super admin badge to primary tokens | Consistent API key highlighting |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/llm/StepConfigDialog.tsx | Updated focus/labels/buttons to primary tokens | Consistent LLM config styling |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/llm/GlobalDefaultsCard.tsx | Updated focus/slider labels to primary tokens | Consistent defaults styling |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/llm/LlmStepRow.tsx | Updated override highlight to primary tokens | Consistent step override styling |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/llm/EmbeddingCard.tsx | Updated icon/focus/check to primary tokens | Consistent embedding card styling |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/MetricsDashboard.tsx | Health dots use success/destructive tokens | Semantic health indicators |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/TenantLinkingModal.tsx | Global access styling uses primary tokens; active dot success | Consistent tenant linking UI |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/RulesPage.tsx | Updated inactive indicators and switches to primary tokens | Aligns rules status styling |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/EmbeddingMigration.tsx | Running status styling uses primary tokens | Consistent migration progress styling |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/TokenMetricsPage.tsx | Error state uses destructive tokens | Semantic error styling |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/pages/FeedbackPage.tsx | Converted amber/orange highlights to primary/warning tokens | Consistent feedback styling |
| 2026-01-27 | Color Tokens | frontend/src/features/chat/components/MessageList.tsx | Updated separator dot to primary token | Consistent chat accent |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/Connectors/ConnectorCard.tsx | Active badge uses success tokens | Consistent connector status |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/Connectors/BaseConfigForm.tsx | Connection bar/badge use success tokens | Consistent config status |
| 2026-01-27 | Surface Tokens | frontend/src/App.tsx | Replaced bg-black loading overlay with bg-background | Tokenized app loading surface |
| 2026-01-27 | Surface Tokens | frontend/src/components/layout/CommandDock.tsx | Converted dock/backdrop blacks to background/surface tokens | Keeps dock glass but tokenized |
| 2026-01-27 | Surface Tokens | frontend/src/features/documents/components/Graph/modals/HealingSuggestionsModal.tsx | Converted header/button white overlays to foreground tokens | Tokenized modal glass surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/documents/components/Graph/modals/MergeNodesModal.tsx | Converted header/button white overlays to foreground tokens | Tokenized modal glass surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/documents/components/DocumentTabs/RelationshipsTab.tsx | Replaced black fallback panel with muted token | Tokenized graph loading fallback |
| 2026-01-27 | Surface Tokens | frontend/src/components/ui/EmptyState.tsx | Converted white glass fills to foreground tokens | Tokenized empty state surface |
| 2026-01-27 | Surface Tokens | frontend/src/components/ui/alert.tsx | Replaced black/white hover fills with muted token | Tokenized alert close hover |
| 2026-01-27 | Surface Tokens | frontend/src/features/documents/components/DocumentLibrary.tsx | Replaced white focus fill with foreground token | Tokenized input focus surface |
| 2026-01-27 | Surface Tokens | frontend/src/features/auth/components/ApiKeyModal.tsx | Converted header glass fill to foreground token | Tokenized modal header |
| 2026-01-27 | Surface Tokens | frontend/src/features/graph/pages/GlobalGraphPage.tsx | Tokenized glass panels and hover fills | Consistent graph UI surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/graph/components/GraphSearchInput.tsx | Tokenized hover and hint surfaces | Consistent search highlight |
| 2026-01-27 | Surface Tokens | frontend/src/features/graph/components/GraphHistoryModal.tsx | Tokenized header and row hover fill | Consistent history panel surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/chat/components/CitationExplorer.tsx | Tokenized header/card/content fills and gradients | Consistent citation panel surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/chat/components/MessageList.tsx | Tokenized message list pill background | Consistent chat surface |
| 2026-01-27 | Surface Tokens | frontend/src/features/chat/components/ChatContainer.tsx | Tokenized hover background for download action | Consistent chat hover surface |
| 2026-01-27 | Surface Tokens | frontend/src/features/chat/components/FeedbackDialog.tsx | Tokenized black/white panel fills | Consistent feedback dialog surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/llm/StepConfigDialog.tsx | Tokenized header, badge, trigger, footer fills | Consistent LLM dialog surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/llm/GlobalDefaultsCard.tsx | Tokenized header and select fills | Consistent LLM defaults surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/llm/EmbeddingCard.tsx | Tokenized header and select fills | Consistent embedding surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/llm/LlmStepRow.tsx | Tokenized base row surface fills | Consistent LLM step styling |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/pages/TuningPage.tsx | Tokenized dialog header and button hover fills | Consistent tuning dialog surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/pages/LlmSettingsPage.tsx | Tokenized dialog header and button hover fills | Consistent LLM settings dialog surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/pages/RulesPage.tsx | Tokenized dialog and source badge fills | Consistent rules surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/pages/FeedbackPage.tsx | Tokenized separators and dialog fills | Consistent feedback surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/TenantLinkingModal.tsx | Tokenized modal header fill | Consistent tenant modal surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/EmbeddingMigration.tsx | Tokenized dialog fills and inline panels | Consistent migration surfaces |
| 2026-01-27 | Accessibility | frontend/src/features/admin/pages/CurationPage.tsx | Added aria-labels to view/accept/reject icon actions | Clarifies curation actions |
| 2026-01-27 | Forms | frontend/src/features/graph/components/GraphSearchInput.tsx | Added name/autocomplete and clarified placeholder | Improves search field semantics |
| 2026-01-27 | Forms | frontend/src/features/documents/components/DocumentLibrary.tsx | Added name/autocomplete and clarified placeholder | Improves filter field semantics |
| 2026-01-27 | Forms | frontend/src/features/auth/components/ApiKeyModal.tsx | Added name/autocomplete and clarified placeholder | Improves API key field semantics |
| 2026-01-27 | Forms | frontend/src/features/chat/components/FeedbackDialog.tsx | Added name/autocomplete and clarified placeholder | Improves feedback field semantics |
| 2026-01-27 | Date Format | frontend/src/features/graph/components/GraphHistoryModal.tsx | Switched time display to FormatDate | Aligns with UI kit date formatting |
| 2026-01-27 | Motion | frontend/src/features/documents/components/DatabaseSidebarContent.tsx | Replaced transition-all with property-specific transitions | Aligns sidebar motion guidance |
| 2026-01-27 | Color Tokens | frontend/src/features/admin/components/MetricsDashboard.tsx | Updated status border to success/destructive tokens | Semantic system status colors |
| 2026-01-27 | Color Tokens | frontend/src/features/chat/components/RoutingBadge.tsx | Replaced RGB colors with semantic token classes | Tokenized confidence badge |
| 2026-01-27 | Color Tokens | frontend/src/features/setup/components/FeatureSetup.tsx | Replaced installed check icon color with success-foreground | Removes text-white usage |
| 2026-01-27 | Color Tokens | frontend/src/features/setup/components/DatabaseSetup.tsx | Updated chevron icon to primary-foreground/70 | Removes text-white usage |
| 2026-01-27 | Color Tokens | frontend/src/features/chat/components/MessageList.tsx | Replaced hero gradient with foreground tokens | Removes from/to white |
| 2026-01-27 | Surface Tokens | frontend/src/features/documents/components/BulkDeleteModal.tsx | Replaced white gradient overlay with foreground token | Tokenized modal glaze |
| 2026-01-27 | Surface Tokens | frontend/src/features/documents/components/DeleteDocumentModal.tsx | Replaced overlay gradient and spinner strokes with destructive-foreground tokens | Tokenized destructive modal |
| 2026-01-27 | Surface Tokens | frontend/src/components/layout/CommandDock.tsx | Adjusted dock stroke to border-white/5 | Aligns glass stroke guidance |
| 2026-01-27 | Surface Tokens | frontend/src/components/ui/card.tsx | Adjusted hover stroke to border-border/60 | Aligns surface border tokens |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/EmbeddingMigration.tsx | Updated input border to border-border/60 | Standardized input strokes |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/pages/RulesPage.tsx | Replaced dashed border strokes with border-border/60 | Consistent empty state borders |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/pages/FeedbackPage.tsx | Replaced ring/border strokes with border tokens | Consistent card framing |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/pages/VectorStorePage.tsx | Updated hover stroke to border-border/60 | Consistent table row borders |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/llm/EmbeddingCard.tsx | Replaced select borders with border-border tokens | Consistent input strokes |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/llm/GlobalDefaultsCard.tsx | Replaced select borders with border-border tokens | Consistent input strokes |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/llm/StepConfigDialog.tsx | Replaced dialog/select/badge borders with border tokens | Consistent overlay strokes |
| 2026-01-27 | Surface Tokens | frontend/src/features/admin/components/llm/LlmStepRow.tsx | Updated hover stroke to border-border/60 | Consistent row borders |
| 2026-01-27 | Surface Tokens | frontend/src/features/chat/components/FeedbackDialog.tsx | Updated code block/textarea borders to token strokes | Consistent feedback surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/chat/components/CitationExplorer.tsx | Updated panel border and ring to border tokens | Consistent explorer framing |
| 2026-01-27 | Surface Tokens | frontend/src/features/chat/components/MessageItem.tsx | Updated ring and code block borders to tokens | Consistent message surfaces |
| 2026-01-27 | Surface Tokens | frontend/src/features/graph/components/GraphSearchInput.tsx | Updated glass border to border-white/5 | Consistent search surface |
| 2026-01-27 | Surface Tokens | frontend/src/features/graph/pages/GlobalGraphPage.tsx | Updated overlay borders to border tokens | Consistent graph panel strokes |
| 2026-01-27 | Surface Tokens | frontend/src/features/documents/components/DocumentLibrary.tsx | Updated hover stroke to border-border/60 | Consistent list row borders |
