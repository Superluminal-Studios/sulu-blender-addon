"""Top-level pytest collection boundaries for independently packaged extensions."""

# Each extension owns its own Python path and test command. Collecting nested
# ``tests`` packages from the legacy add-on root causes ambiguous module names
# and weakens the independent package boundary.
collect_ignore = ["extensions"]
