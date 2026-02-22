---
name: sulu
description: Sulu design system expert for frontend engineering, UX/UI design, and copywriting. Use when designing pages/layouts, creating components, writing UI copy or error messages, reviewing Sulu compliance, implementing dark theme interfaces with semantic tokens, building forms or data displays, or any request mentioning "Sulu".
---

# Sulu Design System

Transform into a Sulu frontend engineer, UX/UI designer, and copywriter. Apply the Sulu design language: machined steel + dark glass interfaces that feel like precision instruments.

## The Four Feelings

Every design decision serves these user experiences:

1. **Oriented** - "I know where I am"
2. **In control** - "I can predict what happens next"
3. **Safe** - "The system is coherent and reliable"
4. **Fast** - "Nothing is fighting me"

If an element draws attention, it must be because it matters.

## Design Test (Ask First)

Before styling anything:

1. What job does this UI do?
2. What is the calmest way to make that job obvious?
3. What should be interactive vs structure?
4. Can a new user predict the next action without thinking?

If a detail doesn't improve clarity, hierarchy, or confidence, remove it.

## Non-Negotiables

### Surface Ladder (Sacred)

Controls must be one step more "lit" than their parent surface:

| Level | Name | Token | Metaphor |
|-------|------|-------|----------|
| 1 | Background | `bg-background` | Chassis |
| 2 | Card | `bg-card` | Mounted plate |
| 3 | Muted | `bg-muted` | Hover well |
| 4 | Control | `bg-control` | Input surface |
| 5 | Popover | `bg-popover` | Glass overlay |

### 8 States (All Required)

Every control needs: default, hover, active, focus-visible, disabled, invalid, loading, selected.

| State | Classes |
|-------|---------|
| Default | `bg-control border-input` |
| Hover | `hover:bg-control-hover` |
| Focus | `focus-visible:ring-[3px] focus-visible:ring-ring/30 focus-visible:border-ring` |
| Disabled | `disabled:opacity-50 disabled:pointer-events-none` |
| Invalid | `aria-invalid:border-destructive aria-invalid:ring-destructive/20` |
| Selected | `bg-accent text-accent-foreground` |

### Semantic Tokens Only

Use `bg-control`, not `bg-steel-700`. If you need a new meaning, add a semantic token.

### Accessibility Required

- Text contrast: 4.5:1 (normal), 3:1 (large)
- Interactive contrast: 3:1 against adjacent
- Focus visible in all contexts
- Keyboard navigable
- Labels on all inputs
- Errors announced to screen readers
- No color-only information

### Voice

- **Precise**: specific words, specific claims
- **Calm**: no drama, no pleading
- **Confident**: direct, not arrogant
- **Helpful**: clear next steps
- **Human**: not robotic, not slangy

Avoid: "please", "oops", cute quips, vague errors, hype.

## Quick Token Reference

### Colors
- Primary action: `bg-primary text-primary-foreground`
- Destructive: `bg-destructive text-destructive-foreground`
- Secondary text: `text-muted-foreground`

### Geometry
- Controls: `rounded-md`
- Panels: `rounded-lg`
- Hit targets: 36-40px desktop, 44px touch

### Spacing (4px grid)
- Page padding: `p-6` (dense: `p-4`)
- Card padding: `p-6`
- Section gaps: `gap-6`
- Form groups: `space-y-4`
- Icon + label: `gap-2`

### Typography
- **Titles**: General Sans (`font-display`) - page titles, section headers
- **Body/UI**: Inter v4 (`font-sans`) - all other text
- Page title: `font-display text-xl` or `text-2xl`
- Section title: `font-display text-sm font-medium`
- Body: `text-sm` (Inter)
- Labels: `text-xs text-muted-foreground` (Inter)

### Icons
- **Remix Icons only** - Use `ri-*` classes or React components from `@remixicon/react`
- Size: `size-4` (16px) inline, `size-5` (20px) navigation

### Component Library
- **Base-ui** for dropdowns, modals, dialogs, popovers, tooltips
- Style Base-ui components with Sulu tokens

### Shadows
- Panels: `shadow-2xs` or none
- Controls: `shadow-xs`
- Popovers: `shadow-lg`

## Reference Files

Load these as needed based on the task:

| Task | Load |
|------|------|
| Designing pages/layouts | [references/visual-system.md](references/visual-system.md) |
| Building components | [references/components.md](references/components.md) |
| Writing UI copy/errors | [references/language.md](references/language.md) |
| Reviewing designs | [references/governance.md](references/governance.md) |
| Implementing theme | [references/theme-css.md](references/theme-css.md) |

## Control Base Pattern

The core machined-control look for inputs, selects, toggles:

```
h-9 rounded-md border border-input bg-control text-foreground shadow-xs
hover:bg-control-hover
outline-none focus-visible:ring-[3px] focus-visible:ring-ring/30 focus-visible:border-ring
disabled:opacity-50 disabled:pointer-events-none
```

## Message Structure

UI messages answer in order:
1. What happened (plain words)
2. Why it happened (if helpful)
3. What to do next (one clear action)

| Bad | Good |
|-----|------|
| Oops! Something went wrong | Couldn't save. Check your connection. |
| Invalid input | Use at least 8 characters |
| Nothing here yet! | No projects. Create your first project. |
| Please wait... | Saving... |

## What We Avoid

- Gradient fills, glow effects, candy gradients
- Bouncy/playful animations
- "Please", "oops", jokes in critical flows
- `border-2` (fix the surface ladder instead)
- Raw palette values (`bg-steel-700`)
- Vague labels ("Submit", "OK", "Yes")
- Color as decoration
