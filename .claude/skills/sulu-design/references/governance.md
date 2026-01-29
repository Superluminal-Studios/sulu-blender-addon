# Sulu Governance

Design test, review checklists, anti-patterns, and debugging order.

## The Design Test

Before you style anything, ask:

1. **What job does this UI do?**
2. **What is the calmest way to make that job obvious?**
3. **What should be interactive, and what should be structure?**
4. **Can a new user predict the next action without thinking?**

If a detail doesn't improve clarity, hierarchy, or confidence, remove it.

## Pass vs Fail Examples

| Scenario | Fails | Passes |
|----------|-------|--------|
| Button styling | Gradient fill, glow effect, custom shadow | Solid primary color, standard shadow-xs |
| Empty state | Cute illustration, joke copy | Clear explanation, single action |
| Error message | "Oops! Something went wrong" | "Couldn't save. Check your connection." |
| Form label | "Please enter your email address below:" | "Email" |
| Loading state | Bouncing dots, playful animation | Simple spinner, clear status text |
| Color usage | Rainbow of accent colors | Primary for actions, muted for secondary |

## Workflow for New Elements

Do this every time:

1. **Define role**: surface? control? overlay?
2. **Choose material**: card / control / popover
3. **Choose stroke**: border vs input
4. **Define states**: default/hover/focus/disabled/invalid/on/loading
5. **Set spacing**: 4px grid, consistent padding
6. **Set typography**: standard scale, mono only when needed
7. **Polish edges**: radius, seams, subtle shadow if required
8. **Test in context**: on background + inside card + inside popover

If it works in all three contexts, it's a real component.

## Review Checklist

### Design

- [ ] Surface ladder reads clearly in context
- [ ] Primary action is obvious; secondary actions don't compete
- [ ] Uses semantic tokens and standard recipes
- [ ] States exist and behave correctly
- [ ] Text and icons are readable across surfaces and states
- [ ] Focus-visible is consistent and visible
- [ ] Keyboard navigation works
- [ ] Hit targets meet minimum size (36-40px desktop, 44px touch)
- [ ] Borders read like seams, not decoration
- [ ] Shadows are restrained
- [ ] Alignment is exact

### Language

- [ ] Verbs are specific
- [ ] No "please," no fluff
- [ ] Messages explain cause + next step
- [ ] Numbers/units/dates follow rules
- [ ] Inclusive language check passes
- [ ] Terminology is consistent throughout

### Accessibility

- [ ] Text contrast: 4.5:1 for normal text, 3:1 for large text
- [ ] Interactive element contrast: 3:1 against adjacent colors
- [ ] Focus indicators visible in all contexts
- [ ] All functionality accessible via keyboard
- [ ] Form inputs have associated labels
- [ ] Error messages are announced to screen readers
- [ ] No information conveyed by color alone
- [ ] Works at 200% zoom

## Don't Fight the System

How we prevent drift:

### 1. Use semantic tokens, not raw palette values

- **Do:** `bg-control`
- **Don't:** `bg-sulu-steel-650`

### 2. Don't make controls transparent

Unless intentionally minimal (ghost buttons, etc.).

### 3. Don't solve contrast with `border-2`

Fix the surface ladder instead.

### 4. Don't introduce new radii casually

Stick to `rounded-md` for controls, `rounded-lg` for panels.

### 5. Don't invent new shadows casually

Use the shadow scale: `shadow-2xs`, `shadow-xs`, `shadow-sm`, `shadow`, `shadow-md`, `shadow-lg`.

### 6. Don't use color as decoration

Color is semantic. It answers "what state is this?"

### 7. Don't invent new terminology

Use established terms consistently.

### 8. Don't add "please" or filler words

UI copy is an instrument panel, not a conversation.

## Debugging Order

When something feels off, fix in this order:

1. **Structure** — Is the hierarchy correct?
2. **Surfaces** — Are the right materials used?
3. **Strokes** — Are borders communicating correctly?
4. **States** — Are all states defined and working?
5. **Typography** — Is the text hierarchy clear?
6. **Copy** — Is the language precise and helpful?

Don't add "style" to fix problems. Add clarity. Add engineering.

## Anti-Patterns

### Visual

| Anti-Pattern | Why It Fails | Fix |
|--------------|--------------|-----|
| Gradient fills | Decoration without meaning | Use solid semantic colors |
| Glow effects | Noise, not signal | Remove or use focus ring only |
| Bouncy animations | Entertainment over utility | Short, directional, purposeful |
| Candy gradients | Style over substance | Use muted, semantic colors |
| Blur/glass everywhere | Trendy, not functional | Use surface ladder |
| Random radii | Inconsistent, unmanufactured | Stick to `rounded-md`/`rounded-lg` |

### Language

| Anti-Pattern | Why It Fails | Fix |
|--------------|--------------|-----|
| "Oops!" / cute errors | Trivializes problems | State what happened clearly |
| "Please" in instructions | Begging adds noise | Direct imperatives |
| Vague labels ("Submit", "OK") | User can't predict action | Specific verbs ("Save changes") |
| Blame language | Creates anxiety | Neutral, helpful phrasing |
| "Something went wrong" | No actionable information | Specific cause + next step |

### Implementation

| Anti-Pattern | Why It Fails | Fix |
|--------------|--------------|-----|
| Raw palette values | Breaks theming, creates drift | Use semantic tokens |
| Missing states | Mystery behavior | Define all 8 states |
| `border-2` for contrast | Treats symptom not cause | Fix surface ladder |
| Inconsistent spacing | Unaligned, unengineered | Use 4px grid consistently |
| Color-only information | Accessibility failure | Add shape/label/icon |

## Excellence Bar

We ship when it feels inevitable.

Excellence means:

- Consistent hierarchy across contexts
- No mystery states
- No accidental contrast issues
- No ad-hoc styling that breaks the system
- Performance that supports the feeling of precision

We treat visual debt like technical debt: it compounds.
