# WCAG 2.1 AA Accessibility Compliance Checklist

<!-- markdownlint-disable MD013 -->

## Overview

This document tracks accessibility compliance for the Amber Analyst UI.

## Status Legend

- Compliant
- Partial (Needs Verification)
- Non-Compliant
- Not Tested

## 1. Perceivable

### 1.1 Text Alternatives

| Criteria                     | Status    | Notes                                    |
| ---------------------------- | --------- | ---------------------------------------- |
| All images have `alt` text   | Compliant | Using `aria-hidden` for decorative icons |
| Icons have accessible labels | Compliant | `aria-label` on icon-only buttons        |

### 1.2 Time-based Media

| Criteria              | Status    | Notes                        |
| --------------------- | --------- | ---------------------------- |
| No auto-playing media | Compliant | N/A - no video/audio content |

### 1.3 Adaptable

| Criteria                   | Status    | Notes                               |
| -------------------------- | --------- | ----------------------------------- |
| Semantic HTML structure    | Compliant | Using `<main>`, `<header>`, `<nav>` |
| Single `<h1>` per page     | Compliant | Fixed in ChatContainer              |
| Proper heading hierarchy   | Compliant | h1 > h2 > h3 maintained             |
| Tables have proper headers | Compliant | `scope="col"` added                 |

### 1.4 Distinguishable

| Criteria                           | Status    | Notes                                             |
| ---------------------------------- | --------- | ------------------------------------------------- |
| Color contrast ratio >= 4.5:1      | Partial   | Using design system colors - verify with DevTools |
| Status indicators use color + icon | Compliant | Badges include visual indicators                  |
| Text can be resized to 200%        | Partial   | Needs manual testing                              |

## 2. Operable

### 2.1 Keyboard Accessible

| Criteria                           | Status     | Notes                          |
| ---------------------------------- | ---------- | ------------------------------ |
| All interactive elements focusable | Compliant  | Tab order flows logically      |
| Visible focus indicators           | Compliant  | `focus:ring-2` on all elements |
| No keyboard traps                  | Compliant  | Escape closes modals           |
| Skip links available               | Not Tested | Not yet implemented            |

### 2.2 Enough Time

| Criteria                       | Status    | Notes                    |
| ------------------------------ | --------- | ------------------------ |
| No strict time limits          | Compliant | Streaming has no timeout |
| Auto-updating content pausable | Compliant | N/A - no auto-refresh    |

### 2.3 Seizures and Physical Reactions

| Criteria                         | Status    | Notes                |
| -------------------------------- | --------- | -------------------- |
| No flashing content              | Compliant | No strobe effects    |
| `prefers-reduced-motion` support | Compliant | Added to globals.css |

### 2.4 Navigable

| Criteria                     | Status    | Notes                                       |
| ---------------------------- | --------- | ------------------------------------------- |
| Page titles descriptive      | Partial   | No app-level `document.title` updates found |
| Focus order logical          | Compliant | Follows DOM order                           |
| Link purpose clear from text | Compliant | Descriptive link text                       |
| Multiple navigation methods  | Compliant | Menu + search                               |

### 2.5 Input Modalities

| Criteria                           | Status    | Notes                             |
| ---------------------------------- | --------- | --------------------------------- |
| Pointer gestures have alternatives | Compliant | All clicks trigger on Enter/Space |
| Motion actuation alternatives      | Compliant | N/A - no motion controls          |

## 3. Understandable

### 3.1 Readable

| Criteria                    | Status    | Notes                                  |
| --------------------------- | --------- | -------------------------------------- |
| Language of page identified | Compliant | `frontend/index.html` sets `lang="en"` |
| Unusual words explained     | Compliant | Technical terms in context             |

### 3.2 Predictable

| Criteria                       | Status    | Notes                     |
| ------------------------------ | --------- | ------------------------- |
| Navigation consistent          | Compliant | Same sidebar on all pages |
| Components behave consistently | Compliant | Same patterns throughout  |

### 3.3 Input Assistance

| Criteria                   | Status    | Notes                                   |
| -------------------------- | --------- | --------------------------------------- |
| Error messages clear       | Compliant | Human-readable error text               |
| Labels for inputs          | Compliant | Using `<label>` or screen-reader labels |
| Error suggestions provided | Compliant | Actionable error messages               |

## 4. Robust

### 4.1 Compatible

| Criteria                  | Status    | Notes                       |
| ------------------------- | --------- | --------------------------- |
| Valid HTML                | Partial   | Run HTML validator          |
| ARIA roles used correctly | Compliant | Following WAI-ARIA patterns |
| Screen reader compatible  | Partial   | Test with VoiceOver/NVDA    |

## Components Audited

### Chat Interface

- [x] `ChatContainer.tsx` - Live region, landmarks
- [x] `QueryInput.tsx` - Labels, describedby, keyboard
- [ ] `MessageList.tsx` - Live updates
- [ ] `SourceNode.tsx` - Citation links

### Documents

- [x] `DocumentLibrary.tsx` - Table headers, aria-labels
- [x] `EmptyState.tsx` - Role, labels
- [x] `SampleDataModal.tsx` - Dialog role, focus trap
- [x] `UploadWizard.tsx` - Step announcements

### Evidence Board

- [ ] `EvidenceBoard.tsx` - Tree role, keyboard nav
- [ ] `SourceCard.tsx` - Expandable regions
- [ ] `ChunkViewer.tsx` - Text selection

### Visualization

- [ ] `EntityGraph.tsx` - Reduced motion, alt text

## Testing Tools

### Automated

- `@axe-core/cli` - Run against dev server
- Chrome DevTools Accessibility panel
- eslint-plugin-jsx-a11y

### Manual

- Tab through entire app without mouse
- Test with screen reader (VoiceOver on Mac, NVDA on Windows)
- Zoom to 200% and verify usability
- Enable reduced motion in OS settings

## Action Items

1. [ ] Implement skip link to main content
2. [ ] Verify color contrast with DevTools
3. [ ] Add keyboard navigation to EntityGraph
4. [ ] Add app-level `document.title` updates
5. [ ] Test with screen reader
6. [ ] Run HTML validator
