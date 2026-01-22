# Documentation Style Guide

## Overview

This guide defines the standard structure and formatting for documentation in
`docs/`.

## Structure

- Title: Use `#` with Title Case. Avoid emojis.
- Overview: Include a short `## Overview` section near the top.
- Metadata (optional): Use a table when version/status/date matter.
- Table of Contents: Include when the document has many sections.
- Headings: Title Case; keep hierarchy consistent.

## Formatting

- Lists: Use `-` for bullets and `1.` for ordered steps.
- Status labels: Use ASCII terms like `Compliant`, `Partial`,
  `Non-Compliant`, `Not Tested`, `Yes`, `No`, or `Limited`.
- Notes and warnings: Use blockquotes with bold labels.
- Horizontal rules: Avoid `---`; use headings instead.
- Links: Use relative paths inside the repo; avoid `file://` URLs.
- Code fences: Always label the language (use `text` when no better fit).
- ASCII: Keep content ASCII unless non-ASCII is required.

## Examples

### Note Example

```text
> **Note:** This action is reversible.
```

### Warning Example

```text
> **Warning:** This action is destructive.
```

### Code Fence Example

````text
```bash
make test
```
````
