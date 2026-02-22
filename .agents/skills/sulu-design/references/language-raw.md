# Sulu Style Guide

A universal, product-ready style guide for UI copy, product marketing language, help content, and technical writing. Apple-specific product names, platform conventions, and trademark details have been removed; what remains is broadly applicable across software and hardware.

---

## 1. Core principles

### Write for the reader, not the writer

* Address the reader directly as **you**.
* Describe what the reader can do and what will happen—not what “the product” or “the system” “allows.” 
* Avoid “end user.” Just say **user**—or better, use **you**. 

### Clarity beats cleverness

* Prefer plain, concrete words.
* Avoid jargon unless your audience expects it. If you must use a specialized term, define it the first time. 
* Avoid idioms and culturally specific references (they don’t translate well and can confuse).

### Be concise, but not cryptic

* Remove filler (especially in UI microcopy).
* Keep sentences short. One instruction per sentence.

### Prefer active voice

* Active voice is usually clearer and more direct. Use passive voice only when it prevents confusion in a tutorial or when the actor is unknown or irrelevant. 

### Be consistent

* Use the same term for the same thing every time.
* Don’t mix styles (for example, two different ways of referring to buttons) inside the same product or document. 

---

## 2. Voice and tone

### Default voice: calm, confident, human

* **Confident**: state what is true; avoid hedging.
* **Helpful**: anticipate the next question.
* **Respectful**: don’t talk down; don’t blame the user.

### Default tense: present tense

* Prefer “Sulu saves your changes automatically” over “Sulu will save…” unless you’re describing a future roadmap. (Avoid unnecessary future tense.) 

### Avoid “please” in instructions

In most UI and help content, “please” adds noise and can sound either stiff or passive-aggressive. Use polite tone through clarity, not “please.” 

### Avoid “optionally”

Instead of “Optionally, do X,” explain why someone would do it.

* Prefer: “If you want to ___, do X.” 

### Avoid “new” as a claim

“New” becomes wrong quickly. Prefer:

* “Available in version X.Y” (or “Introduced in…”), or
* “Now supports…” if you’re explicitly describing a change log. 

---

## 3. Writing for UI

This section covers UI labels, instructions, and references to onscreen elements.

### 3.1 Match the interface

* Use **the exact label text** the user sees (including capitalization and punctuation). 
* Don’t invent names for UI parts when you can describe the action instead.

### 3.2 Sentence case for UI labels

Default UI labels to **sentence case** (unless your brand/system uses a different convention):

* “Save changes”
* “Turn on notifications”
* “Privacy settings”

When referencing sentence-case UI elements in running text, use quotation marks to prevent misreading:

* Select the checkbox labeled “Keep lines together.”

### 3.3 Referencing UI elements

Use these conventions:

* **Buttons / commands / menu items**: Use the label exactly; if sentence case, put in quotes.

  * Click “Save.”
  * Choose File > Export.

* **Checkboxes / switches**: Refer to the label, not the control type. 

  * Select “Use two-factor authentication.” (Not: “Select the checkbox…” unless needed for clarity.)

* **Radio buttons**: Avoid saying “radio button” in user-facing content; refer to the option label. 

* **Dialogs**: Call them dialogs (not “dialog boxes”).

  * The “Save changes” dialog appears.

* **Alerts / error states**: Prefer “message” or “alert message” in user materials; avoid “error message” unless writing developer/debug-facing content. 

### 3.4 Click, tap, press: use the right verb

#### Click

* Use **click** for pointer-based interaction.
* Don’t use “click on.” 

#### Tap

* Use **tap** for touch.
* Don’t use “tap on.” 

#### Press

* Use **press** for physical buttons and keys.
* Don’t use “push” for buttons/keys. 

#### Drag

* Use **drag** for moving items or controls.
* Don’t write “click and drag” (you either click or drag; dragging implies holding input down).
* Don’t write “tap and drag.” 

#### Hover

* Avoid “hover over.” Prefer “hold the pointer over.” 

### 3.5 Turn on/off vs enable/disable vs select/deselect

* Prefer **turn on / turn off** for features. 
* Use **enable** only when you truly mean “make possible for later actions” (a prerequisite), not as a synonym for “turn on.” 
* Use **select** for choosing UI options; **deselect** for canceling a selection. 
* For checkboxes: use **select** / **clear** if that matches your UI; avoid “check/uncheck” unless the interface literally uses that language. 

### 3.6 “Share” vs “send”

These verbs mean different things:

* **Share**: give ongoing access or make something available to others.
* **Send**: transmit a copy one time. 

### 3.7 Links

* Users **click a link**. Avoid “follow a link.” 

---

## 4. Procedures, tutorials, and task steps

### 4.1 Use numbered steps for sequences

Use a numbered list when order matters; each step should be a complete sentence and end with punctuation.

Example:

1. Open Settings.
2. Select “Notifications.”
3. Turn on “Allow notifications.”

### 4.2 Use bulleted lists for non-sequential items

Use bullets for options, rules, or items where order doesn’t matter. 

List rules:

* Introduce lists with a **colon** (even if the lead-in is not a full sentence).
* Capitalize the first word of each bullet.
* Use periods only when bullet items are full sentences. 
* Keep items parallel in structure and grammar. 

### 4.3 Don’t miscue the reader

In tutorials, sometimes passive voice is acceptable when you’re describing what they should observe (not do yet). 

---

## 5. UI messaging: errors, warnings, confirmation, empty states

### 5.1 Use “message” as the default term

* Prefer “message” or “alert message” (user-facing) rather than “error message.” 

### 5.2 Message structure

A good UI message answers, in order:

1. **What happened**
2. **Why it happened** (if helpful and knowable)
3. **What to do next**

Keep it short. Avoid internal error codes unless they help support/debugging; if you show them, label them clearly.

### 5.3 Don’t blame the user

Avoid “You did X wrong.” Prefer neutral language:

* “That file can’t be uploaded because it’s larger than 20 MB.”

### 5.4 Prefer specific verbs over vague ones

Avoid “fails” and “issues” when you can say exactly what happened:

* “Upload stopped” / “Upload didn’t finish” / “Couldn’t connect”

Also avoid “bug” in user-facing copy; use “issue,” “problem,” or describe the behavior. 

Avoid “crash” in user-facing copy; describe what the user experiences (“the app quits unexpectedly,” “stops responding”). 

### 5.5 Notices: Note, Important, Warning

Use notice labels sparingly, and don’t stack multiple notices.

* **Note**: helpful extra context.
* **Important**: something the reader must not miss.
* **Warning**: risk of harm, data loss, or irreversible action.

---

## 6. Capitalization

### 6.1 Use sentence case by default

* UI labels: sentence case.
* Help center article titles: sentence case is acceptable and modern; if your brand prefers title case, use it consistently.

### 6.2 Title case rules (if you choose title case)

If you use title-style capitalization in headings, apply it consistently. Keep your rules explicit (articles, short prepositions, conjunctions, etc.). 

### 6.3 After colons

* In running text, capitalize after a colon **if what follows is a complete sentence**. 
* In headings with a colon, capitalize the first word after the colon. 

---

## 7. Punctuation and symbols

### 7.1 Quotation marks

* Use curly quotes in normal text.
* In code font, use straight quotes.
* Periods and commas typically go inside quotation marks in US style; other punctuation goes outside unless it’s part of the quoted material.

### 7.2 Ampersand (&)

Use **&** only when it appears in an official UI label/title; otherwise write “and.” 

### 7.3 Dashes

Use dashes intentionally:

* **Em dash** (—) for breaks in thought.
* **En dash** (–) for ranges in compact contexts (tables, UI). 

### 7.4 Avoid “and/or”

Rewrite to remove ambiguity. 

### 7.5 Serial comma

Use the Oxford comma for clarity in lists. 

---

## 8. Common word choices

These choices reduce ambiguity and improve scannability.

* Use **more than** (not “over”) for quantities. 
* Use **because** for causality; reserve **since** primarily for time when possible. 
* Use **different from** (not “different than”) when comparing nouns. 
* Avoid “desired” (“the desired folder” → “the folder you want”). 
* Avoid “wish/desire”; use **want**. 
* Use **appear** rather than “show up.” 
* Don’t use “display” when you mean “appear.” 

---

## 9. Numbers

### 9.1 General rule

* Spell out **one through nine** in running text when no unit is attached.
* Use numerals for **10 and above**, and for anything with a unit, measurement, dimension, version, step, or UI value.

### 9.2 Don’t start sentences with numerals

Rewrite or spell out. 

### 9.3 Thousands separators

Use commas for 10,000 and above in US English; don’t use commas for four-digit numbers (e.g., 1024) unless your domain conventions require it.

### 9.4 Ranges

* Use **to** in running text: “3 to 5 minutes.”
* Use an **en dash** in tables/compact UI: “3–5 min.”

### 9.5 Percent

* Use numerals with percent: “50%” or “50 percent.”
* Choose **%** in UI, tables, and tight layouts; spell out “percent” in running text if it reads better.

---

## 10. Dates and times

### 10.1 Avoid ambiguity

Avoid numeric-only date formats in user-facing content for global audiences (e.g., 03/04/2026). Prefer spelled-out months or ISO format.

### 10.2 Recommended formats

Pick based on context:

**User-facing (US English default):**

* January 29, 2026 

**International / data / settings / filenames:**

* 2026-01-29 (ISO 8601)

### 10.3 Time

* Use numerals: 8:30 a.m., 6:30 p.m. (space before a.m./p.m.).
* If you include a time zone, do it consistently and only when needed.

---

## 11. Units of measure

### 11.1 General rules

* Use numerals with units: “5 km,” “12 GB,” “3.5 in.”
* Use a space between the number and the unit (except for symbols like °, %, and currency symbols where appropriate).
* Unit symbols don’t take periods in metric/SI; plural is usually the same as singular for symbols.

### 11.2 Dimensions

Use **by** in prose (“8.5 by 11 inches”) unless your domain uses “x” consistently. 

### 11.3 Data sizes and speeds

Use standard symbols (KB, MB, GB, TB) and be clear whether you mean decimal (base-10) or binary (base-2) when it matters. Use consistent abbreviations.

---

## 12. Technical notation and developer-facing writing

### 12.1 Code font rules

Use code font for:

* code
* literals
* command names
* file and directory names (in developer materials)

Don’t use code font for:

* headings/titles
* table of contents entries
* web addresses
* figure captions/callouts
* system messages (quote those in body font, in quotation marks) 

### 12.2 Syntax descriptions

* Code font for literals.
* Italics for placeholders.
* Regular text for brackets around optional items. 

Example pattern:

* `Read([file, ] var)` 

### 12.3 Don’t verb function names

Write:

* “Run `ls` on both directories,” not “`ls` both directories.” 

### 12.4 Placeholder names

Use meaningful placeholders (not foo/bar/baz) and be consistent. 

---

## 13. Inclusive and accessible language

### 13.1 Write inclusively by default

* Assume a global, diverse audience.
* If you’re unsure about a term, research it and consider whether it has harmful historical associations. 

### 13.2 Gender-inclusive language

* Use gender-neutral language when gender isn’t relevant.
* Prefer “they/them” as singular when needed.
* Avoid unnecessarily gendered job titles (“chairperson” or “chair,” not “chairman”).

### 13.3 Disability

* Mention disability only when relevant.
* Prefer respectful, commonly accepted phrasing (and follow community preferences when known).
* Avoid outdated or negative terms like “hearing impaired”; prefer “Deaf” or “hard of hearing” as appropriate. 
* Avoid “normal” to mean “nondisabled.” 

### 13.4 Replace biased technical metaphors

Avoid terms like blacklist/whitelist; use allow list/deny list (or block list/allow list, depending on context).

### 13.5 Examples and sample data

* Use diverse names, locations, and scenarios.
* Avoid stereotypes.
* Avoid culture-specific jokes, holidays, or idioms unless your content is explicitly localized.

---

## 14. Localization and international style

Write as if your text will be translated—even if you don’t translate today.

* Use short, direct sentences.
* Avoid idioms, slang, and wordplay.
* Avoid unnecessary abbreviations.
* Prefer internationally standard formats in data-heavy contexts:

  * ISO dates (YYYY-MM-DD)
  * Clear units and unit symbols
  * Locale-aware number formatting where applicable (decimal separators differ).

---

## 15. Tables, figures, and references

### 15.1 Tables

* Use sentence-style capitalization for table parts, including headings. 
* Keep headings short and descriptive.
* Reference each table in text immediately before it.

### 15.2 Table notes and footnotes

* Start table notes with “Note:” (not all caps).

### 15.3 Figure captions

* Keep titles short (aim under ~1.5 lines).
* Use sentence case and no ending punctuation, even if it’s a full sentence. 

---

## 16. Sulu “preferred terms” quick list

Use this as a default vocabulary set.

* **email** (not e-mail) 
* **Wi‑Fi** (capitalization and hyphen) 
* **web**, **internet** (generally lowercase); don’t use “WWW”
* **click** (not click on) 
* **tap** (not tap on) 
* **press** (not push) 
* **drag** (not click and drag; not tap and drag) 
* **turn on/off** for features; reserve **enable** for prerequisites 
* **message** / **alert message** (avoid “error message” in user content) 
* **dialog** (not dialog box)
* **quit** for stopping an app entirely (not exit) 
* **more than** (not over) 
* **because** for causality (avoid ambiguity with since) 
* **click a link** (not follow a link) 
