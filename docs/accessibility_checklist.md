# WCAG 2.1 AA Accessibility Compliance Checklist

This document tracks accessibility compliance for the Amber Analyst UI.

## Status Legend
- ✅ Compliant
- ⚠️ Partial / Needs verification
- ❌ Non-compliant
- 📋 Not yet tested

---

## 1. Perceivable

### 1.1 Text Alternatives
| Criteria                     | Status | Notes                                    |
| ---------------------------- | ------ | ---------------------------------------- |
| All images have `alt` text   | ✅      | Using `aria-hidden` for decorative icons |
| Icons have accessible labels | ✅      | `aria-label` on icon-only buttons        |

### 1.2 Time-based Media
| Criteria              | Status | Notes                        |
| --------------------- | ------ | ---------------------------- |
| No auto-playing media | ✅      | N/A - no video/audio content |

### 1.3 Adaptable
| Criteria                   | Status | Notes                               |
| -------------------------- | ------ | ----------------------------------- |
| Semantic HTML structure    | ✅      | Using `<main>`, `<header>`, `<nav>` |
| Single `<h1>` per page     | ✅      | Fixed in ChatContainer              |
| Proper heading hierarchy   | ✅      | h1 > h2 > h3 maintained             |
| Tables have proper headers | ✅      | `scope="col"` added                 |

### 1.4 Distinguishable
| Criteria                           | Status | Notes                                             |
| ---------------------------------- | ------ | ------------------------------------------------- |
| Color contrast ratio ≥ 4.5:1       | ⚠️      | Using design system colors - verify with DevTools |
| Status indicators use color + icon | ✅      | Badges include visual indicators                  |
| Text can be resized to 200%        | ⚠️      | Needs manual testing                              |

---

## 2. Operable

### 2.1 Keyboard Accessible
| Criteria                           | Status | Notes                          |
| ---------------------------------- | ------ | ------------------------------ |
| All interactive elements focusable | ✅      | Tab order flows logically      |
| Visible focus indicators           | ✅      | `focus:ring-2` on all elements |
| No keyboard traps                  | ✅      | Escape closes modals           |
| Skip links available               | 📋      | Not yet implemented            |

### 2.2 Enough Time
| Criteria                       | Status | Notes                    |
| ------------------------------ | ------ | ------------------------ |
| No strict time limits          | ✅      | Streaming has no timeout |
| Auto-updating content pausable | ✅      | N/A - no auto-refresh    |

### 2.3 Seizures and Physical Reactions
| Criteria                         | Status | Notes                |
| -------------------------------- | ------ | -------------------- |
| No flashing content              | ✅      | No strobe effects    |
| `prefers-reduced-motion` support | ✅      | Added to globals.css |

### 2.4 Navigable
| Criteria                     | Status | Notes                     |
| ---------------------------- | ------ | ------------------------- |
| Page titles descriptive      | ✅      | Set via React Helmet/meta |
| Focus order logical          | ✅      | Follows DOM order         |
| Link purpose clear from text | ✅      | Descriptive link text     |
| Multiple navigation methods  | ✅      | Menu + search             |

### 2.5 Input Modalities
| Criteria                           | Status | Notes                             |
| ---------------------------------- | ------ | --------------------------------- |
| Pointer gestures have alternatives | ✅      | All clicks trigger on Enter/Space |
| Motion actuation alternatives      | ✅      | N/A - no motion controls          |

---

## 3. Understandable

### 3.1 Readable
| Criteria                    | Status | Notes                      |
| --------------------------- | ------ | -------------------------- |
| Language of page identified | ⚠️      | Add `lang="en"` to html    |
| Unusual words explained     | ✅      | Technical terms in context |

### 3.2 Predictable
| Criteria                       | Status | Notes                     |
| ------------------------------ | ------ | ------------------------- |
| Navigation consistent          | ✅      | Same sidebar on all pages |
| Components behave consistently | ✅      | Same patterns throughout  |

### 3.3 Input Assistance
| Criteria                   | Status | Notes                                   |
| -------------------------- | ------ | --------------------------------------- |
| Error messages clear       | ✅      | Human-readable error text               |
| Labels for inputs          | ✅      | Using `<label>` or screen-reader labels |
| Error suggestions provided | ✅      | Actionable error messages               |

---

## 4. Robust

### 4.1 Compatible
| Criteria                  | Status | Notes                       |
| ------------------------- | ------ | --------------------------- |
| Valid HTML                | ⚠️      | Run HTML validator          |
| ARIA roles used correctly | ✅      | Following WAI-ARIA patterns |
| Screen reader compatible  | ⚠️      | Test with VoiceOver/NVDA    |

---

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

---

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

---

## Action Items

1. [ ] Add `lang="en"` to `<html>` element
2. [ ] Implement skip link to main content
3. [ ] Verify color contrast with DevTools
4. [ ] Add keyboard navigation to EntityGraph
5. [ ] Test with screen reader
6. [ ] Run HTML validator
