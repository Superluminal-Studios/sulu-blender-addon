import bpy

blender_version_items = [
    ("BLENDER40", "Blender 4.0", "Use Blender 4.0 on the farm"),
    ("BLENDER41", "Blender 4.1", "Use Blender 4.1 on the farm"),
    ("BLENDER42", "Blender 4.2", "Use Blender 4.2 on the farm"),
    ("BLENDER43", "Blender 4.3", "Use Blender 4.3 on the farm"),
    ("BLENDER44", "Blender 4.4", "Use Blender 4.4 on the farm"),
]

# Build a lookup:  40 → "BLENDER40", 41 → "BLENDER41", …
_enum_by_number = {
    int(code.replace("BLENDER", "")): code
    for code, *_ in blender_version_items
}
_enum_numbers_sorted = sorted(_enum_by_number)     # e.g. [40, 41, 42, 43, 44]

def enum_from_bpy_version() -> str:
    """
    Return the enum key that best matches the running Blender version.

    • If the build is *newer* than anything in the list → return the
      **highest** enum we have.
    • If it’s *older* than anything in the list → return the **lowest**.
    • Otherwise pick the exact match or, if the minor revision isn’t
      represented, the nearest lower entry (4.2.3 maps to 4.2).
    """
    major, minor, _ = bpy.app.version
    numeric = major * 10 + minor     # 4.3 → 43

    # Clamp to list boundaries
    if numeric <= _enum_numbers_sorted[0]:
        return _enum_by_number[_enum_numbers_sorted[0]]
    if numeric >= _enum_numbers_sorted[-1]:
        return _enum_by_number[_enum_numbers_sorted[-1]]

    # Inside the known range – find the closest lower-or-equal entry
    for n in reversed(_enum_numbers_sorted):
        if n <= numeric:
            return _enum_by_number[n]

    # Fallback (shouldn’t be reached)
    return blender_version_items[0][0]

def get_blender_version_string():
    ver = bpy.app.version 
    return f"{ver[0]}.{ver[1]}"
