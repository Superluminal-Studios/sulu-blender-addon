# Playbook: Add a new setting end‑to‑end (UI → submit → worker)

This is the most common integration bug: “setting exists in UI but doesn’t affect farm”.

## Step 1: Add property (source of truth)

- `properties.py`: add to `SuperluminalSceneProperties` (Scene setting) or WM props if runtime-only.
  Rules:
- if it must save in the .blend → Scene prop
- if it must _not_ persist (passwords, transient) → WindowManager prop with `options={'SKIP_SAVE'}`

## Step 2: Expose in UI

- `panels.py`: show it in the right panel section
- use `use_property_split` conventions already present

## Step 3: Thread/poll safety

- If it triggers network activity, do not do it in `draw()`.
- Prefer:
  - an Operator button
  - a timer callback
  - or a background thread that only updates Storage and triggers UI redraw

## Step 4: Send to worker

- `transfers/submit/submit_operator.py`: add the setting to `handoff` dict.
- Keep backward compat:
  - new fields optional
  - worker must default if key missing

## Step 5: Worker reads it

- In `submit_worker.py` (not shown in this excerpt), read the new handoff key.
- Make sure any API payload includes it if backend expects it.

## Step 6: Validate

Without Blender:

- run compile checks: `python -m compileall .`
- run skill sanity script: `.claude/skills/sulu/scripts/sulu_sanity.py`

With Blender:

- change the setting, submit a job, verify the worker prints the setting (no secrets)
- verify backend receives it (status page or logs)
