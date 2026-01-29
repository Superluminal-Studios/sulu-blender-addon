# Sulu Language System

Voice, UI writing rules, error patterns, and preferred terms.

## Voice

The Sulu voice is:

- **Precise**: specific words, specific claims
- **Calm**: no drama, no pleading
- **Confident**: direct, but not arrogant
- **Helpful**: clear next steps
- **Human**: not robotic, not slangy

### We Avoid

- Hype and superlatives without proof
- Cute quips in critical flows
- Faux friendliness that adds noise ("Hey there!" everywhere)
- Hedging and weasel words
- Blame directed at the user

## Tone by Context

### UI Microcopy
- Shortest correct phrasing
- Mostly verbs and nouns
- Minimal adjectives

### Docs / Help
- Step-by-step clarity
- Anticipate failure modes
- Consistent terminology

### Product Marketing
- Still calm and rational, but with more narrative
- Show benefits with specifics, not adjectives
- "Instrument panel" confidence, not influencer energy

## Core Writing Principles

### Write for the reader, not the writer

- Address the reader directly as **you**
- Describe what the reader can do and what will happen—not what "the product" "allows"
- Avoid "end user." Just say **user**—or better, use **you**

### Clarity beats cleverness

- Prefer plain, concrete words
- Avoid jargon unless your audience expects it
- Avoid idioms and culturally specific references (they don't translate)

### Be concise, but not cryptic

- Remove filler (especially in UI microcopy)
- Keep sentences short. One instruction per sentence.

### Prefer active voice

- Active voice is usually clearer and more direct
- Use passive only when actor is unknown/irrelevant

### Be consistent

- Use the same term for the same thing every time
- Don't mix styles inside the same product

## UI Writing Rules

### Write like an instrument panel

- Prefer **short sentences** and **simple structure**
- Prefer **present tense**; use future only when something will truly happen later
- Avoid "in order to"; it bloats instructions

### Put the user as the subject

Rewrite "This feature allows you to..." into "You can..."

### Don't say "please"

Instructional text shouldn't beg. State what to do. Use polite tone through clarity, not "please."

### Don't say "optionally"

Instead of "Optionally, do X," explain why someone would do it: "If you want to ___, do X."

### Avoid "new" as a claim

"New" becomes wrong quickly. Prefer "Available in version X.Y" or "Now supports..." in change logs.

### Use the right action verbs

| Verb | Use for |
|------|---------|
| **Click** | Pointer-based interaction (not "click on") |
| **Tap** | Touch interaction (not "tap on") |
| **Press** | Physical buttons and keys (not "push") |
| **Drag** | Moving items or controls (not "click and drag") |
| **Enter** | Providing input (typed, pasted, dragged) |
| **Type** | Pressing keys to produce characters |

For hover: prefer "hold the pointer over" rather than "hover over."

### Turn on/off vs enable/disable

- Use **turn on / turn off** for immediate state changes
- Use **enable** only when configuring a prerequisite
- Use **select** for choosing UI options; **deselect** or **clear** for canceling
- Avoid "check/uncheck" unless the interface uses that language

### Share vs send

- **Share**: give ongoing access
- **Send**: transmit a copy one time

### Links

Users **click a link**. Avoid "follow a link."

### Refer to interface elements precisely

- Use **the exact label text** (including capitalization and punctuation)
- Don't invent names for UI parts when you can describe the action instead
- Menu paths: Menu > Item > Subitem
- If an icon has no name, describe what it looks like or does (lowercase)

### Don't turn nouns into verbs

Avoid "Message your team." Prefer "Send a message to your team."

## Naming & Capitalization

### Sentence case by default

- "Save changes" (not "Save Changes")
- "Turn on notifications"
- "Privacy settings"

Exception: Proper nouns and product names keep their official capitalization.

### Referencing UI elements

| Element | Convention |
|---------|------------|
| Buttons/commands/menu items | Use label exactly; if sentence case, put in quotes |
| Checkboxes/switches | Refer to the label, not the control type |
| Radio buttons | Refer to the option label (avoid "radio button") |
| Dialogs | Call them "dialogs" (not "dialog boxes") |
| Alerts | Prefer "message" or "alert message" |

### Common noun/verb forms

| Verb | Noun/Adjective |
|------|----------------|
| set up | setup |
| log in | login |
| sign in | sign-in |
| sign up | sign-up |
| back up | backup |
| check out | checkout |
| start up | startup |
| shut down | shutdown |

## Messages, Errors & Notices

### Call them "messages," not "error messages"

User-facing copy should say **message**, **alert**, or **alert message**.

### Message structure

A good message answers, in order:

1. **What happened** (plain words)
2. **Why it happened** (if helpful and knowable)
3. **What to do next** (one clear action)

Keep it short. Avoid internal error codes unless they help support/debugging.

### Don't blame the user

Avoid "You did X wrong." Prefer neutral language:
- "That file can't be uploaded because it's larger than 20 MB."

### Prefer specific verbs over vague ones

Avoid "fails" and "issues" when you can say exactly what happened:
- "Upload stopped" / "Upload didn't finish" / "Couldn't connect"

Also avoid:
- "Bug" in user-facing copy (use "issue," "problem," or describe the behavior)
- "Crash" (use "the app quits unexpectedly," "stops responding")

### Good vs Bad Examples

| Context | Bad | Good |
|---------|-----|------|
| Button | Submit | Save changes |
| Button | Yes | Delete project |
| Error | Oops! Something went wrong. | Couldn't save. Check your connection. |
| Error | Invalid input | Use at least 8 characters |
| Empty state | Nothing here yet! | No projects. Create your first project. |
| Confirmation | Are you sure? | Delete "My Project"? This can't be undone. |
| Success | Success! | Changes saved |
| Loading | Please wait... | Saving... |
| Help text | This field allows you to enter your name | Your name as it appears on your ID |
| Tooltip | Click here to learn more | View documentation |

### Notes, Important, Warning

Use notice labels sparingly; they lose impact if overused. Don't stack multiple notices.

| Label | Use for |
|-------|---------|
| **Note** | Helpful extra context |
| **Important** | Something the reader must not miss |
| **Warning** | Risk of harm, data loss, or irreversible action |

### Avoid "if necessary"

Tell the user the exact condition instead.

## Punctuation & Symbols

### Quotation marks

- Use curly quotes ("like this") in normal text
- Use straight quotes in code font
- Periods and commas go inside quotation marks (US style)

### Dashes

| Dash | Usage |
|------|-------|
| Em dash (—) | Breaks in thought, parenthetical statements |
| En dash (–) | Ranges in compact contexts: "3–5 min" |
| Hyphen (-) | Compound words: "17-inch display" |

### Serial comma

Use the Oxford comma: "Design, engineering, and copy"

### Ellipses

- Use sparingly
- In UI, ellipses indicate action requiring more input: "Save as..."
- Don't use for trailing off

## Common Word Choices

| Use | Instead of |
|-----|------------|
| **more than** | over (for quantities) |
| **because** | since (reserve "since" for time) |
| **different from** | different than |
| **the folder you want** | the desired folder |
| **want** | wish, desire |
| **appear** | show up |
| **you can** | this feature allows you to |

### Don't confuse "display" and "appear"

- Use **appear** when something becomes visible: "A message appears."
- Use **display** as noun or with object: "The dashboard displays your data."

### Respectful language

- Avoid "simply," "just," or "easy"—what's easy for you may not be for the reader
- Avoid "obviously" or "of course"—if it were obvious, you wouldn't need to say it

## Numbers, Units, Dates & Times

### Numbers in text

- Spell out **one through nine** in running prose when no unit is attached
- Use numerals for **10 and above**, and for anything with a unit, measurement, dimension, version, step, or UI value
- Don't start sentences with numerals; rewrite or spell out

### Ranges

- Use **to** in running text: "3 to 5 minutes"
- Use **en dash** in tables/compact UI: "3–5 min"

### Percent

- Use numerals: "50%" or "50 percent"
- Use **%** in UI, tables, tight layouts

### Dates

| Context | Format |
|---------|--------|
| User-facing (US) | January 29, 2026 |
| International/data | 2026-01-29 (ISO 8601) |

Avoid: 03/04/2026 (ambiguous)

### Times

- Use numerals: 8:30 a.m., 6:30 p.m. (space before a.m./p.m.)
- Include time zone only when needed

### Currency

For international contexts, use ISO codes: `1199 USD`, `1980 EUR`

## Inclusive Language

### General guidance

- Assume a global, diverse audience
- Don't write as if one group is the default "normal"
- Avoid stereotypes, "crazy," "lame," and ableist language

### Gender-inclusive

- Use gender-neutral language when gender isn't relevant
- Prefer "they/them" as singular when needed
- Avoid gendered job titles ("chairperson" not "chairman")

### Technical inclusivity

Prefer **allow list / deny list** over blacklist/whitelist.

### Examples and sample data

- Use diverse names, locations, scenarios
- Avoid stereotypes
- Avoid culture-specific jokes, holidays, or idioms unless explicitly localized

## Preferred Terms Quick List

### Interaction verbs

| Preferred | Avoid |
|-----------|-------|
| click | click on |
| tap | tap on |
| press | push |
| drag | click and drag, tap and drag |
| enter | input (as verb) |
| select | choose (for UI options) |
| turn on/off | enable/disable (for state changes) |
| click a link | follow a link |

### UI terminology

| Preferred | Avoid |
|-----------|-------|
| message, alert message | error message (user-facing) |
| dialog | dialog box |
| quit | exit (for stopping an app) |
| settings | preferences (unless branded) |
| menu | dropdown (user-facing) |

### General writing

| Preferred | Avoid |
|-----------|-------|
| email | e-mail |
| Wi-Fi | wifi, Wifi |
| web, internet | WWW |
| more than | over (for quantities) |
| because | since (for causality) |
| different from | different than |
| the folder you want | the desired folder |
| want | wish, desire |
| appear | show up |
| can | is able to |
| you can | this feature allows you to |

### Technical terms

| Preferred | Avoid |
|-----------|-------|
| allow list / deny list | blacklist / whitelist |
| main / primary | master |
| replica / secondary | slave |
