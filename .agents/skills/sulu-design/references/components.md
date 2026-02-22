# Sulu Component Recipes

Component patterns and the 8-step workflow for building new elements.

## 8-Step Component Recipe

Do this every time when creating new components:

1. **Define role**: surface? control? overlay?
2. **Choose material**: card / control / popover
3. **Choose stroke**: border vs input
4. **Define states**: default/hover/focus/disabled/invalid/on/loading
5. **Set spacing**: 4px grid, consistent padding
6. **Set typography**: standard scale, mono only when needed
7. **Polish edges**: radius, seams, subtle shadow if required
8. **Test in context**: on background + inside card + inside popover

If it works in all three contexts, it's a real component.

## Control Base Pattern

The core machined-control look for inputs, select triggers, toggles:

```
h-9 rounded-md border border-input bg-control text-foreground shadow-xs
hover:bg-control-hover
outline-none focus-visible:ring-[3px] focus-visible:ring-ring/30 focus-visible:border-ring
disabled:opacity-50 disabled:pointer-events-none
```

## Interaction States

Every interactive component must define all applicable states:

| # | State | Description |
|---|-------|-------------|
| 1 | Default | Normal appearance |
| 2 | Hover | Pointer over element |
| 3 | Active/Pressed | During click/tap |
| 4 | Focus-visible | Keyboard focus |
| 5 | Disabled | Not available |
| 6 | Invalid/Error | Validation failed |
| 7 | Loading/Busy | Operation in progress |
| 8 | Selected/On | Toggles, tabs, nav |

### Standard State Mappings

| State | Classes |
|-------|---------|
| Default control | `bg-control border-input` |
| Hover | `hover:bg-control-hover` |
| Selected/on | `bg-accent text-accent-foreground` |
| Invalid | `aria-invalid:border-destructive aria-invalid:ring-destructive/20` |
| Disabled | `disabled:opacity-50 disabled:pointer-events-none` |

**Hover is subtle; focus is reliable.**

## Component Patterns

### Panel / Card

Use for coherent units of content:

```
rounded-lg border border-border bg-card text-card-foreground
```

For a hairline seam:
```
border-[color:var(--border-subtle)]
```

### Buttons

#### Primary Button

```
h-9 rounded-md bg-primary text-primary-foreground shadow-xs
hover:bg-primary/90
focus-visible:ring-[3px] focus-visible:ring-ring/30
```

#### Secondary/Outline Button

```
h-9 rounded-md border border-input bg-control text-foreground shadow-xs
hover:bg-control-hover
focus-visible:ring-[3px] focus-visible:ring-ring/30 focus-visible:border-ring
```

#### Destructive Button

```
h-9 rounded-md bg-destructive text-destructive-foreground shadow-xs
hover:bg-destructive/90
```

#### Button Label Rules

- Use verbs: "Save", "Create project", "Export CSV"
- Avoid vague labels: "OK", "Yes" (unless question is extremely clear)
- For destructive actions, name the consequence: "Delete project", "Remove member"

### Menu / List Item

```
rounded-sm px-2 py-1.5 text-sm
focus:bg-accent focus:text-accent-foreground
data-[disabled]:opacity-50 data-[disabled]:pointer-events-none
```

### Checkbox

```
size-4 rounded-[4px] border border-input bg-control shadow-xs
data-[state=checked]:bg-primary data-[state=checked]:border-primary
focus-visible:ring-[3px] focus-visible:ring-ring/30
```

### Switch / Toggle

Track:
```
h-5 w-9 rounded-full border border-input bg-control
data-[state=checked]:bg-primary
transition-colors
```

Thumb:
```
size-4 rounded-full bg-foreground shadow-xs
translate-x-0 data-[state=checked]:translate-x-4
transition-transform
```

### Select / Dropdown Trigger

Use control base styling:

```
h-9 rounded-md border border-input bg-control text-foreground shadow-xs
hover:bg-control-hover
focus-visible:ring-[3px] focus-visible:ring-ring/30 focus-visible:border-ring
```

With chevron icon aligned right, muted color.

### Tabs

Tab list:
```
inline-flex gap-1 bg-muted p-1 rounded-lg
```

Tab trigger:
```
px-3 py-1.5 text-sm rounded-md
text-muted-foreground
data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-xs
```

### Badge / Tag

```
inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium
bg-muted text-muted-foreground
```

Status variants (use sparingly):
- Success: `bg-malachite-950 text-malachite-400`
- Warning: `bg-amber-950 text-amber-400`
- Error: `bg-rose-950 text-rose-400`

### Tooltip

```
bg-popover text-popover-foreground text-xs px-2 py-1 rounded-md shadow-lg
```

Keep tooltip text short. No periods unless multiple sentences.

### Loading States

#### Spinner
- Simple, subtle spinner
- Match text color of context
- Size appropriately: 16px inline, 24px buttons

#### Skeleton
```
bg-muted animate-pulse rounded-md
```
Match shape and size of content being loaded.

#### Button Loading
- Replace text with spinner + "Loading..." or action-specific text ("Saving...")
- Disable pointer events while loading

## Form Patterns

### Form Layout

| Element | Classes |
|---------|---------|
| Label | `text-xs text-muted-foreground` |
| Input | Control base |
| Help text | `text-xs text-muted-foreground` |
| Error text | `text-xs text-destructive` |

### Form Validation

- Show inline errors near the field
- Explain the fix ("Use at least 12 characters") not the rule name ("Invalid password")
- Keep alignment consistent; avoid random widths

## Icons (Remix Icons Only)

Use **Remix Icons** exclusively via `@remixicon/react`.

```tsx
import { RiSettingsLine, RiSettings3Fill, RiUserLine } from '@remixicon/react'

// Line variant for default state
<RiSettingsLine className="size-5 text-muted-foreground" />

// Fill variant for active/selected state
<RiSettings3Fill className="size-5 text-foreground" />
```

### Size Conventions

| Context | Size | Class |
|---------|------|-------|
| Inline with text | 16px | `size-4` |
| Buttons | 16-20px | `size-4` or `size-5` |
| Navigation | 20-24px | `size-5` or `size-6` |
| Empty states | 48px+ | `size-12` |

### Style Rules

- Use `-line` variants for default states
- Use `-fill` variants for selected/active states
- Match icon visual weight to adjacent text
- Icons vertically centered with adjacent text
- Use `gap-2` between icon and label

## Base-ui Components

Use **Base-ui** (`@base-ui-components/react`) for complex interactive components:

- Dialogs/Modals
- Dropdowns/Menus
- Popovers
- Tooltips
- Select
- Combobox

### Styling Base-ui with Sulu Tokens

Base-ui components are unstyled. Apply Sulu tokens via className or render props.

#### Dialog Example

```tsx
import { Dialog } from '@base-ui-components/react/dialog'

<Dialog.Root>
  <Dialog.Trigger className="h-9 rounded-md bg-primary text-primary-foreground px-4">
    Open dialog
  </Dialog.Trigger>
  <Dialog.Portal>
    <Dialog.Backdrop className="fixed inset-0 bg-black/50" />
    <Dialog.Popup className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-card p-6 shadow-lg">
      <Dialog.Title className="font-display text-lg font-semibold">
        Dialog title
      </Dialog.Title>
      <Dialog.Description className="text-sm text-muted-foreground mt-2">
        Dialog description text.
      </Dialog.Description>
      <Dialog.Close className="absolute top-4 right-4 text-muted-foreground hover:text-foreground">
        <RiCloseLine className="size-5" />
      </Dialog.Close>
    </Dialog.Popup>
  </Dialog.Portal>
</Dialog.Root>
```

#### Menu/Dropdown Example

```tsx
import { Menu } from '@base-ui-components/react/menu'

<Menu.Root>
  <Menu.Trigger className="h-9 rounded-md border border-input bg-control px-3 shadow-xs hover:bg-control-hover">
    Options
  </Menu.Trigger>
  <Menu.Portal>
    <Menu.Positioner>
      <Menu.Popup className="rounded-lg border border-border bg-popover p-1 shadow-lg">
        <Menu.Item className="rounded-sm px-2 py-1.5 text-sm cursor-pointer data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground">
          Edit
        </Menu.Item>
        <Menu.Item className="rounded-sm px-2 py-1.5 text-sm cursor-pointer data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground">
          Duplicate
        </Menu.Item>
        <Menu.Separator className="my-1 h-px bg-border" />
        <Menu.Item className="rounded-sm px-2 py-1.5 text-sm text-destructive cursor-pointer data-[highlighted]:bg-destructive/10">
          Delete
        </Menu.Item>
      </Menu.Popup>
    </Menu.Positioner>
  </Menu.Portal>
</Menu.Root>
```

#### Select Example

```tsx
import { Select } from '@base-ui-components/react/select'

<Select.Root>
  <Select.Trigger className="h-9 rounded-md border border-input bg-control px-3 shadow-xs hover:bg-control-hover inline-flex items-center justify-between gap-2">
    <Select.Value placeholder="Select option" />
    <Select.Icon>
      <RiArrowDownSLine className="size-4 text-muted-foreground" />
    </Select.Icon>
  </Select.Trigger>
  <Select.Portal>
    <Select.Positioner>
      <Select.Popup className="rounded-lg border border-border bg-popover p-1 shadow-lg">
        <Select.Item value="1" className="rounded-sm px-2 py-1.5 text-sm cursor-pointer data-[highlighted]:bg-accent">
          Option 1
        </Select.Item>
        <Select.Item value="2" className="rounded-sm px-2 py-1.5 text-sm cursor-pointer data-[highlighted]:bg-accent">
          Option 2
        </Select.Item>
      </Select.Popup>
    </Select.Positioner>
  </Select.Portal>
</Select.Root>
```

#### Tooltip Example

```tsx
import { Tooltip } from '@base-ui-components/react/tooltip'

<Tooltip.Root>
  <Tooltip.Trigger>
    <button>Hover me</button>
  </Tooltip.Trigger>
  <Tooltip.Portal>
    <Tooltip.Positioner>
      <Tooltip.Popup className="bg-popover text-popover-foreground text-xs px-2 py-1 rounded-md shadow-lg">
        Tooltip content
      </Tooltip.Popup>
    </Tooltip.Positioner>
  </Tooltip.Portal>
</Tooltip.Root>
```

## Page Construction

### Standard Scaffold

```
bg-background p-6
```

- Header row: title left, primary action right
- Content: main column or split with secondary panel

**Rule:** One primary action per view.

### Sectioning

Use cards for:
- Distinct tasks
- Grouped settings
- Meaningful data blocks

Avoid cards for every tiny item (noise).

### Empty States

An empty state must do one of:
- Explain why it's empty
- Show how to add the first item
- Provide a safe default action

No jokes. No dead ends.

### Confirmations

Use confirmations only for:
- Irreversible actions
- Expensive actions
- Actions with delayed/hidden consequences

Prefer undo when possible.
