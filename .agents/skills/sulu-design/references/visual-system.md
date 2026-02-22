# Sulu Visual System

Complete reference for surfaces, color, typography, spacing, and motion.

## The Material Model

Design like industrial objects are made: **surfaces + seams + tolerances**.

Everything is built from:
- **Surfaces** (materials with mass and presence)
- **Strokes** (seams, edges, tolerances between machined parts)

### Physical Metaphors

| UI Concept | Physical Metaphor |
|------------|-------------------|
| Surfaces | Background, panels, controls, overlays — materials with mass |
| Strokes | Seams, edges, tolerances — gaps between machined parts |
| Specular highlights | Subtle reflections on brushed metal — used sparingly |
| Elevation | Physical lift from surface — earned, not everywhere |
| Focus rings | Instrument panel indicators — calm but unmistakable |

## Surface Ladder (Non-Negotiable)

Use semantic tokens; never invent new surface colors inside components:

| Level | Name | Token | Metaphor | CSS Variable |
|-------|------|-------|----------|--------------|
| 1 | Background | `bg-background` | Chassis | `--background` (steel-900) |
| 2 | Card/Panel | `bg-card` | Mounted plate | `--card` (steel-800) |
| 3 | Muted | `bg-muted` | Quiet well/hover well | `--muted` (steel-750) |
| 4 | Control | `bg-control` | Machined input surface | `--control` (steel-700) |
| 5 | Popover | `bg-popover` | Elevated glass overlay | `--popover` (steel-600) |

**Rule:** Interactive controls must not share the same fill as the surface they sit on. Controls must be one step more "lit" than the panel under them.

## Strokes (Tolerances)

Strokes define structure and affordance:

| Purpose | Token | Opacity |
|---------|-------|---------|
| Divider/panel outline | `border-border` | 9% |
| Control outline | `border-input` | 15% |
| Subtle seam | `border-[color:var(--border-subtle)]` | 6% |
| Stronger edge | `border-[color:var(--border-strong)]` | 20% |

**Rule:** Default is **1px** strokes. If you want `border-2`, fix the surface ladder instead.

## Focus Treatment

Focus is calm but unmistakable:

```
focus-visible:ring-[3px]
focus-visible:ring-ring/30
focus-visible:border-ring
```

Uses `--ring` (indigo-400) for visibility at low alpha.

## Shadows

Borders do heavy lifting; shadows are restrained and purposeful:

| Element | Shadow | Use |
|---------|--------|-----|
| Panels | `shadow-2xs` or none | Structure, not float |
| Controls | `shadow-xs` max | Subtle machined edge |
| Popovers/modals | `shadow-lg` + border | Earned elevation |

If things feel floaty, reduce shadows first.

All shadows include a subtle specular highlight: `inset 0 1px 0 var(--specular)`.

## Color Philosophy

Color is semantic. It answers "what state is this?" not "how do we make this pretty?"

### Semantic Colors

| Role | Tokens | Usage |
|------|--------|-------|
| Primary | `bg-primary text-primary-foreground` | Main action, selection, focus |
| Destructive | `bg-destructive text-destructive-foreground` | Irreversible/risky actions |
| Muted | `text-muted-foreground` | Secondary info |
| Accent | `bg-accent text-accent-foreground` | Hover/selected states |

### Color Rules

- No saturation for decoration
- No extra accent colors for "variety"
- Fix contrast via surfaces/strokes first
- Never rely on color alone (always pair with shape/label/icon)

### Status Badge Colors

Use sparingly for status indicators:

| Status | Background | Text |
|--------|------------|------|
| Success | `bg-malachite-950` | `text-malachite-400` |
| Warning | `bg-amber-950` | `text-amber-400` |
| Error | `bg-rose-950` | `text-rose-400` |

## Typography

### Font Families

| Token | Font | Usage |
|-------|------|-------|
| `font-display` | General Sans | Titles, headings, section headers |
| `font-sans` | Inter v4 | Body text, labels, UI copy |
| `font-mono` | System mono | IDs, numbers, code, system labels |

### Scale

| Element | Classes |
|---------|---------|
| Page title | `font-display text-xl` or `text-2xl` (sparingly) |
| Section title | `font-display text-sm font-medium` or `text-base font-semibold` |
| Body | `text-sm` (Inter) |
| Labels/meta | `text-xs text-muted-foreground` (Inter) |

### Rules

- **Titles always use General Sans** (`font-display`)
- **All other text uses Inter** (`font-sans`)
- Use weight + spacing for hierarchy, not huge size jumps
- Keep prose readable: `max-w-prose` in content areas
- Don't run full-width paragraphs

## Icons

### Remix Icons Only

Use Remix Icons exclusively. Install via `@remixicon/react` or use CSS classes.

```tsx
import { RiSettingsLine, RiUserLine } from '@remixicon/react'

<RiSettingsLine className="size-5 text-muted-foreground" />
```

### Size Conventions

| Context | Size | Class |
|---------|------|-------|
| Inline with text | 16px | `size-4` |
| Buttons | 16-20px | `size-4` or `size-5` |
| Navigation | 20-24px | `size-5` or `size-6` |
| Empty states | 48px+ | `size-12` |

### Style

- Use line variants (`-line`) for default states
- Use filled variants (`-fill`) for selected/active states
- Match icon visual weight to adjacent text

## Geometry & Density

### Radii

Slightly squarer geometry = more machined feel:

| Element | Radius |
|---------|--------|
| Controls | `rounded-md` |
| Panels | `rounded-lg` |
| Micro elements | Small fixed radius (consistent) |

**Rule:** One family of radii per element type. Don't freestyle rounding.

### Hit Targets

| Context | Minimum |
|---------|---------|
| Desktop | 36–40px |
| Touch | 44px |

Default control height: `h-9` acceptable; `h-10` for touch-first.

If a control is hard to click, it fails the Sulu test.

## Layout & Spacing

Design on a **4px grid**.

### Spacing Defaults

| Context | Spacing |
|---------|---------|
| Page padding | `p-6` (or `p-4` in dense views) |
| Card padding | `p-6` (header/content), `pt-0` when stacking |
| Section gaps | `gap-6` / `space-y-6` |
| Form groups | `space-y-4` |
| Icon + label | `gap-2` |

### Rules

- Alignment is sacred
- Use empty space intentionally
- Don't compress for density unless necessary

## Motion & Effects

Motion exists to:
- Confirm causality ("I clicked this → that happened")
- Guide attention (subtly)
- Communicate state changes

### Timing

| Type | Duration | Easing |
|------|----------|--------|
| Micro-interactions (hover, focus) | 100–150ms | ease-out |
| Small transitions (expand/collapse) | 150–200ms | ease-out |
| Medium transitions (modals, panels) | 200–300ms | ease-in-out |
| Page transitions | 300–400ms | ease-in-out |

### Rules

- Short, directional, purposeful
- Never bouncy by default
- Respect `prefers-reduced-motion`

### Allowed Charm

- Subtle specular edges
- Slight cool steel bias in neutrals
- Crisp alignment and spacing
- Quiet motion (short and directional)

### Avoided

- Blur/glass everywhere
- Candy gradients
- Bouncy motion
- Oversaturated surfaces
- Glows as decoration

## Data Visualization

### Chart Colors

| Token | Usage |
|-------|-------|
| `--chart-1` | Primary data series |
| `--chart-2` | Secondary data series |
| `--chart-3` | Tertiary data series |
| `--chart-4` | Quaternary data series |
| `--chart-5` | Additional series |

For more than 5 series, consider grouping or different visualization.

### Chart Principles

- **Data-ink ratio**: Maximize ink for data. Remove chartjunk.
- **No 3D effects**: They distort perception.
- **No gratuitous animation**: Animate only to show change or guide attention.
- **Label directly**: Put labels on data points when possible, not in legends.
- **Start axes at zero** for bar charts; consider context for line charts.

### Data Display

- Use `font-mono` for data values in tables/readouts
- Align numbers to the right in tables
- Use appropriate precision (no 12 decimal places)
- Include units with values
- Show "No data" with explanation, not blank chart

## Responsive Design

### Breakpoints (Tailwind defaults)

| Breakpoint | Width |
|------------|-------|
| sm | 640px |
| md | 768px |
| lg | 1024px |
| xl | 1280px |
| 2xl | 1536px |

### Mobile Considerations

- Increase hit targets to 44px minimum
- Stack layouts vertically
- Use full-width inputs and buttons
- Consider bottom sheets instead of modals
- Test touch interactions

### Density Modes

For data-heavy applications, consider density toggle:

- **Comfortable**: Default spacing (`p-6`, `gap-6`)
- **Compact**: Reduced spacing (`p-4`, `gap-4`) for power users
