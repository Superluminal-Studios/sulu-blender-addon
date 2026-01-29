# Sulu Theme CSS

Complete Tailwind tokens and base layer for Sulu's dark theme.

## Token Philosophy

Design tokens are the source of truth. Components consume **semantic tokens**, not raw palette values.

- **Do:** `bg-control`
- **Don't:** `bg-sulu-steel-650`

### Two Layers of Tokens

1. **Palette tokens**: chromatic families + steel neutrals
2. **Semantic tokens**: background/card/muted/control/popover, border/input/ring, etc.

Tailwind is wired to semantic tokens so components only reference semantic names.

### Non-Negotiable Implementation Rule

Components may not "reach into" palette values for convenience. If a component needs a new semantic meaning, add a **semantic token**, don't hardcode a palette step.

### Rules for New Tokens

If you need a new token:

1. Prove it appears in multiple places
2. Name it semantically (by role), not visually (by color)
3. Document it

### Naming Conventions

**Tokens:**
- Lowercase with hyphens: `--color-primary`, `--shadow-xs`
- Semantic names describe role, not appearance: `--destructive` not `--red`
- Include state in name when needed: `--control-hover`

**Components:**
- PascalCase for component names: `Button`, `CardHeader`, `NavigationMenu`
- Descriptive, not clever: `UserProfileCard` not `PersonBox`

**CSS classes (Tailwind):**
- Use semantic tokens: `bg-primary` not `bg-indigo-500`
- Group related utilities logically
- Comment complex combinations

**Files:**
- kebab-case for file names: `user-profile-card.tsx`
- Co-locate related files (component + styles + tests)

## Complete Theme CSS

```css
@import "tailwindcss";
@plugin "tailwindcss-animate";
@plugin "@tailwindcss/typography";

/*
  Dark-only, engineered to read like machined steel + dark glass.
  Supports `.dark` or `[data-theme="dark"]` if you ever reintroduce toggling.
*/
@custom-variant dark (&:where(.dark, .dark *, [data-theme=dark], [data-theme=dark] *));

/* ╔═════════════════════════════════╗
   ║  DESIGN TOKENS (PALETTES)       ║
   ╚═════════════════════════════════╝ */
@theme {
  /* Typography: General Sans for titles, Inter for body */
  --font-display: "General Sans", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-sans: "Inter", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", Roboto, Helvetica, Arial, "Noto Sans", "Apple Color Emoji", "Segoe UI Emoji",
    "Segoe UI Symbol", "Noto Color Emoji";

  /* ————— Chromatic families ————— */
  --color-sulu-indigo-50: oklch(95.65% 0.02 274.04);
  --color-sulu-indigo-100: oklch(92.18% 0.04 274.1);
  --color-sulu-indigo-200: oklch(85.67% 0.07 275.12);
  --color-sulu-indigo-300: oklch(76.26% 0.12 275.41);
  --color-sulu-indigo-400: oklch(65.01% 0.19 276.79);
  --color-sulu-indigo-500: oklch(55.09% 0.25 274.93);
  --color-sulu-indigo-600: oklch(50.05% 0.26 274.97);
  --color-sulu-indigo-700: oklch(45% 0.24 275.13);
  --color-sulu-indigo-800: oklch(39.02% 0.2 275.31);
  --color-sulu-indigo-900: oklch(34.88% 0.16 277.12);
  --color-sulu-indigo-950: oklch(25.04% 0.1 280.81);

  --color-sulu-rose-50: oklch(0.969 0.015 12.422);
  --color-sulu-rose-100: oklch(0.941 0.03 12.58);
  --color-sulu-rose-200: oklch(0.892 0.058 10.001);
  --color-sulu-rose-300: oklch(0.81 0.117 11.638);
  --color-sulu-rose-400: oklch(0.712 0.194 13.428);
  --color-sulu-rose-500: oklch(0.645 0.246 16.439); /* destructive */
  --color-sulu-rose-600: oklch(0.586 0.253 17.585);
  --color-sulu-rose-700: oklch(0.514 0.222 16.935);
  --color-sulu-rose-800: oklch(0.455 0.188 13.697);
  --color-sulu-rose-900: oklch(0.41 0.159 10.272);
  --color-sulu-rose-950: oklch(0.271 0.105 12.094);

  --color-sulu-amber-50: oklch(0.987 0.022 95.277);
  --color-sulu-amber-100: oklch(0.962 0.059 95.617);
  --color-sulu-amber-200: oklch(0.924 0.12 95.746);
  --color-sulu-amber-300: oklch(0.879 0.169 91.605);
  --color-sulu-amber-400: oklch(0.828 0.189 84.429);
  --color-sulu-amber-500: oklch(0.769 0.188 70.08);
  --color-sulu-amber-600: oklch(0.666 0.179 58.318);
  --color-sulu-amber-700: oklch(0.555 0.163 48.998);
  --color-sulu-amber-800: oklch(0.473 0.137 46.201);
  --color-sulu-amber-900: oklch(0.414 0.112 45.904);
  --color-sulu-amber-950: oklch(0.279 0.077 45.635);

  --color-sulu-malachite-50: oklch(98.14% 0.02 150.11);
  --color-sulu-malachite-100: oklch(96.11% 0.05 150.81);
  --color-sulu-malachite-200: oklch(92.13% 0.09 150.16);
  --color-sulu-malachite-300: oklch(86.6% 0.15 149.08);
  --color-sulu-malachite-400: oklch(79.25% 0.2 147.36);
  --color-sulu-malachite-500: oklch(70.94% 0.21 145.86);
  --color-sulu-malachite-600: oklch(61.93% 0.18 145.64);
  --color-sulu-malachite-700: oklch(51.97% 0.15 146.04);
  --color-sulu-malachite-800: oklch(44.32% 0.12 146.85);
  --color-sulu-malachite-900: oklch(38.81% 0.1 147.94);
  --color-sulu-malachite-950: oklch(26.21% 0.07 148.1);

  --color-sulu-purple-50: oklch(97.08% 0.01 290.75);
  --color-sulu-purple-100: oklch(94.57% 0.03 295.55);
  --color-sulu-purple-200: oklch(89.98% 0.05 295.57);
  --color-sulu-purple-300: oklch(81.95% 0.09 294.36);
  --color-sulu-purple-400: oklch(72.08% 0.14 295.14);
  --color-sulu-purple-500: oklch(61.84% 0.2 294.92);
  --color-sulu-purple-600: oklch(55.05% 0.23 295.9);
  --color-sulu-purple-700: oklch(49.65% 0.22 295.59);
  --color-sulu-purple-800: oklch(43.72% 0.19 295.68);
  --color-sulu-purple-900: oklch(38.57% 0.16 296.92);
  --color-sulu-purple-950: oklch(28.61% 0.12 293.45);

  /* ————— Zinc (kept for compatibility) ————— */
  --color-sulu-zinc-50: oklch(0.93 0 0);
  --color-sulu-zinc-100: oklch(0.9104 0.0008 106.4235);
  --color-sulu-zinc-200: oklch(0.9071 0.0012 0);
  --color-sulu-zinc-300: oklch(0.8928 0.003 0);
  --color-sulu-zinc-400: oklch(0.8737 0.0072 0);
  --color-sulu-zinc-500: oklch(0.8726 0.0016 0);
  --color-sulu-zinc-600: oklch(0.8705 0.0072 0);
  --color-sulu-zinc-700: oklch(0.837 0.009 0);
  --color-sulu-zinc-800: oklch(0.7968 0.0048 0);
  --color-sulu-zinc-900: oklch(0.7921 0.0072 0);
  --color-sulu-zinc-950: oklch(0.744 0.0072 0);

  /*
    ————— Steel (AIRY MACHINED DARK NEUTRALS) —————
    Monotonic, cool-leaning, tuned for a clean "anodized metal" read.
    Includes mid steps for: panels, controls, overlays.
  */
  --color-sulu-steel-50: oklch(0.54 0.014 270.17);
  --color-sulu-steel-100: oklch(0.5 0.014 270.17);
  --color-sulu-steel-200: oklch(0.46 0.014 270.17);
  --color-sulu-steel-300: oklch(0.42 0.014 270.17);
  --color-sulu-steel-400: oklch(0.38 0.014 270.17);
  --color-sulu-steel-500: oklch(0.34 0.014 270.17);
  --color-sulu-steel-550: oklch(0.32 0.014 270.17);
  --color-sulu-steel-600: oklch(0.304 0.014 270.17);
  --color-sulu-steel-650: oklch(0.288 0.014 270.17);
  --color-sulu-steel-700: oklch(0.273 0.014 270.17);
  --color-sulu-steel-750: oklch(0.258 0.014 270.17);
  --color-sulu-steel-800: oklch(0.245 0.014 270.17);
  --color-sulu-steel-850: oklch(0.225 0.014 270.17);
  --color-sulu-steel-900: oklch(0.205 0.014 270.17);
  --color-sulu-steel-950: oklch(0.18 0.014 270.17);
}

/* ╔═════════════════════════════════╗
   ║  SEMANTIC THEME (DARK ONLY)     ║
   ║  Surfaces • Strokes • Focus     ║
   ╚═════════════════════════════════╝ */
:root,
.dark,
[data-theme="dark"] {
  color-scheme: dark;

  /* Typography: General Sans for titles, Inter for body */
  --font-display: "General Sans", ui-sans-serif, system-ui, sans-serif;
  --font-sans: "Inter", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", Roboto, Helvetica, Arial, "Noto Sans", "Apple Color Emoji", "Segoe UI Emoji",
    "Segoe UI Symbol", "Noto Color Emoji";
  --font-serif: ui-serif, Georgia, Cambria, "Times New Roman", Times, serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
    "Liberation Mono", "Courier New", monospace;

  /*
    SURFACE LADDER (always consistent)
    background < card < muted < control < popover

    - background: chassis
    - card: mounted plate
    - muted: quiet highlight/hover well
    - control: machined input surface
    - popover: elevated glass
  */
  --background: var(--color-sulu-steel-900);
  --foreground: oklch(0.9 0.02 268.2);

  --card: var(--color-sulu-steel-800);
  --card-foreground: var(--foreground);

  --muted: var(--color-sulu-steel-750);
  --muted-foreground: oklch(0.725 0.014 268.2);

  --control: var(--color-sulu-steel-700);
  --control-hover: var(--color-sulu-steel-650);

  --popover: var(--color-sulu-steel-600);
  --popover-foreground: var(--foreground);

  /* Brand + state */
  --primary: var(--color-sulu-indigo-500);
  --primary-foreground: oklch(0.975 0.008 268.2);

  --secondary: var(--muted);
  --secondary-foreground: var(--foreground);

  --accent: var(--control-hover);
  --accent-foreground: var(--foreground);

  --destructive: var(--color-sulu-rose-500);
  --destructive-foreground: oklch(0.975 0.008 268.2);

  /*
    STROKES (tinted, not chalky)
    Borders communicate tolerances, not decoration.
  */
  --border: oklch(0.92 0.015 270 / 0.09); /* dividers, panel outlines */
  --input: oklch(0.92 0.015 270 / 0.15); /* control outlines */
  --border-subtle: oklch(0.92 0.015 270 / 0.06);
  --border-strong: oklch(0.92 0.015 270 / 0.2);

  /*
    Focus: crisp, calm, unmistakable.
    Use a slightly more luminous step than primary for visibility at low alpha.
  */
  --ring: var(--color-sulu-indigo-400);

  /* Micro "specular" highlight for machined edges (used in shadows below) */
  --specular: oklch(0.98 0.01 270 / 0.05);

  /* Charts */
  --chart-1: oklch(0.488 0.243 264.376);
  --chart-2: oklch(0.696 0.17 162.48);
  --chart-3: oklch(0.769 0.188 70.08);
  --chart-4: oklch(0.627 0.265 303.9);
  --chart-5: oklch(0.645 0.246 16.439);

  /* Sidebar: recessed by one step, still steel */
  --sidebar: var(--color-sulu-steel-950);
  --sidebar-foreground: var(--foreground);
  --sidebar-primary: var(--primary);
  --sidebar-primary-foreground: var(--primary-foreground);
  --sidebar-accent: var(--background);
  --sidebar-accent-foreground: var(--foreground);
  --sidebar-border: var(--border-subtle);
  --sidebar-ring: var(--ring);

  /* Geometry: slightly squarer = more machined */
  --radius: 0.45rem;

  /*
    Shadows: restrained, "machined edge" separation.
    We prefer borders first; shadows are subtle and purposeful.
  */
  --shadow-2xs: inset 0 1px 0 var(--specular), 0 1px 1px hsl(0 0% 0% / 0.28);
  --shadow-xs: inset 0 1px 0 var(--specular), 0 1px 2px hsl(0 0% 0% / 0.32);
  --shadow-sm: inset 0 1px 0 var(--specular), 0 2px 6px -2px hsl(0 0% 0% / 0.4);
  --shadow: inset 0 1px 0 var(--specular), 0 4px 12px -6px hsl(0 0% 0% / 0.48);
  --shadow-md: inset 0 1px 0 var(--specular), 0 10px 20px -14px hsl(0 0% 0% / 0.56);
  --shadow-lg: inset 0 1px 0 var(--specular), 0 18px 34px -24px hsl(0 0% 0% / 0.62);
  --shadow-xl: inset 0 1px 0 var(--specular), 0 28px 50px -36px hsl(0 0% 0% / 0.66);
  --shadow-2xl: inset 0 1px 0 var(--specular), 0 36px 64px -48px hsl(0 0% 0% / 0.7);

  --tracking-normal: 0em;
  --spacing: 0.25rem;
}

/* ╔═════════════════════════════════╗
   ║  TAILWIND SEMANTIC WIRING       ║
   ╚═════════════════════════════════╝ */
@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);

  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);

  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);

  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);

  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);

  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);

  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);

  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);

  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);

  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-chart-4: var(--chart-4);
  --color-chart-5: var(--chart-5);

  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);

  /* Control surfaces (critical for consistency) */
  --color-control: var(--control);
  --color-control-hover: var(--control-hover);

  /* Optional extra strokes */
  --color-border-subtle: var(--border-subtle);
  --color-border-strong: var(--border-strong);

  --font-display: var(--font-display);
  --font-sans: var(--font-sans);
  --font-mono: var(--font-mono);
  --font-serif: var(--font-serif);

  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);

  --shadow-2xs: var(--shadow-2xs);
  --shadow-xs: var(--shadow-xs);
  --shadow-sm: var(--shadow-sm);
  --shadow: var(--shadow);
  --shadow-md: var(--shadow-md);
  --shadow-lg: var(--shadow-lg);
  --shadow-xl: var(--shadow-xl);
  --shadow-2xl: var(--shadow-2xl);

  /* Optional ambient animation token */
  --animate-aurora: aurora 120s linear infinite;
}

/* ╔═════════════════════════════════╗
   ║  BASE LAYER                     ║
   ╚═════════════════════════════════╝ */
@layer base {
  * {
    font-family: var(--font-sans);
    -webkit-tap-highlight-color: transparent;
    @apply border-border outline-ring/50;
  }

  html {
    text-rendering: geometricPrecision;
  }

  body {
    font-family: var(--font-sans);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    @apply bg-background text-foreground;
  }

  /* Quiet, intentional selection */
  ::selection {
    background: color-mix(in oklch, var(--primary) 35%, transparent);
    color: var(--primary-foreground);
  }

  /*
    INDUSTRIAL SCROLLBARS
    Always visible, colored track, rounded thumb. Displaces content.
  */
  ::-webkit-scrollbar {
    width: 12px;
    height: 12px;
  }

  ::-webkit-scrollbar-track {
    background: color-mix(in oklch, var(--muted) 50%, transparent);
    border-radius: 4px;
  }

  ::-webkit-scrollbar-thumb {
    background: color-mix(in oklch, var(--muted-foreground) 60%, transparent);
    border-radius: 4px;
  }

  ::-webkit-scrollbar-thumb:hover {
    background: color-mix(in oklch, var(--muted-foreground) 80%, transparent);
  }

  ::-webkit-scrollbar-thumb:active {
    background: var(--muted-foreground);
    cursor: grabbing;
  }

  ::-webkit-scrollbar-corner {
    background: color-mix(in oklch, var(--muted) 50%, transparent);
  }

  /* Firefox scrollbar */
  * {
    scrollbar-width: auto;
    scrollbar-color: oklch(0.725 0.014 268.2 / 0.6) oklch(0.258 0.014 270.17 / 0.5);
  }
}

/* ╔═════════════════════════════════╗
   ║  OPTIONAL: AURORA / MARQUEE     ║
   ╚═════════════════════════════════╝ */

@keyframes aurora {
  from {
    background-position: 50% 50%, 50% 50%;
  }
  to {
    background-position: 350% 50%, 350% 50%;
  }
}

@keyframes marqueeX {
  0% {
    transform: translateX(0%);
  }
  100% {
    transform: translateX(var(--marquee-translate));
  }
}

@keyframes marqueeY {
  0% {
    transform: translateY(0%);
  }
  100% {
    transform: translateY(var(--marquee-translate));
  }
}

/* Base animation wiring */
[data-scope="marquee"][data-part="content"] {
  animation-timing-function: linear;
  animation-duration: var(--marquee-duration);
  animation-delay: var(--marquee-delay);
  animation-iteration-count: var(--marquee-loop-count);
}

[data-scope="marquee"][data-part="content"][data-side="start"],
[data-scope="marquee"][data-part="content"][data-side="end"] {
  animation-name: marqueeX;
}

[data-scope="marquee"][data-part="content"][data-side="top"],
[data-scope="marquee"][data-part="content"][data-side="bottom"] {
  animation-name: marqueeY;
}

[data-scope="marquee"][data-part="content"][data-reverse] {
  animation-direction: reverse;
}

/* Pause support */
[data-scope="marquee"][data-part="root"][data-paused] [data-part="content"] {
  animation-play-state: paused;
}

/* Respect reduced motion */
@media (prefers-reduced-motion: reduce) {
  [data-scope="marquee"][data-part="content"] {
    animation: none !important;
  }
}
```

## Keyboard & ARIA Patterns

### Keyboard Navigation Requirements

Every interactive element must be:

- Reachable via Tab (or arrow keys within composite widgets)
- Activatable via Enter or Space (as appropriate)
- Dismissible via Escape (for overlays, dialogs, menus)

### Common Patterns

| Widget | Keyboard behavior |
|--------|-------------------|
| Button | Enter or Space to activate |
| Link | Enter to activate |
| Checkbox | Space to toggle |
| Radio group | Arrow keys to move, Space to select |
| Tabs | Arrow keys to move, automatic or manual activation |
| Menu | Arrow keys to navigate, Enter to select, Escape to close |
| Dialog | Tab to cycle focus, Escape to close, focus trap active |
| Combobox | Arrow keys to navigate options, Enter to select |

### ARIA Guidelines

- Use semantic HTML first; add ARIA only when needed
- Every interactive element needs an accessible name
- Use `aria-describedby` for additional context (help text, error messages)
- Use `aria-live` regions for dynamic content updates
- Test with screen readers (VoiceOver, NVDA)

### Focus Management

- Focus should move logically through the page
- When opening a dialog, move focus to the first interactive element
- When closing a dialog, return focus to the trigger element
- Use `focus-visible` (not `focus`) for styling to avoid showing focus on click
