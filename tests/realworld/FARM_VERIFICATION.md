# Farm Verification Guide

After running the real-world upload tests, use this guide to verify everything worked correctly on the Superluminal render farm.

## Quick Checklist

```
□ Jobs appear in dashboard with 'SULU_TEST_' prefix
□ All expected files uploaded (check file count)
□ No drive letters (C:/, D:/) in file paths
□ No temp directory paths (AppData/Local/Temp, bat_packroot)
□ Renders start without "file not found" errors
□ Output images look correct (no pink textures)
```

## Detailed Verification Steps

### 1. Job Creation

**Go to:** Farm Dashboard → Job List

**Check:**
- [ ] Test jobs appear with names like `SULU_TEST_basic_file_abc12345`
- [ ] Job status is "queued" or "rendering"
- [ ] Job frame range matches test config (usually frame 1)

**If jobs don't appear:**
- Check the test output for errors
- Verify session.json has valid credentials
- Check network connectivity to farm

### 2. File Upload Verification

**Go to:** Click on a test job → Files/Assets tab

**Check for CORRECT paths:**
```
✓ scene.blend
✓ textures/wood.png
✓ textures/metal.png
✓ assets/character.blend
```

**Check for INCORRECT paths (bugs):**
```
✗ C:/Users/artist/project/scene.blend          # Has drive letter!
✗ AppData/Local/Temp/bat_packroot_xyz/file.png # Temp dir leaked!
✗ /absolute/path/to/file.png                   # Absolute path!
```

**Common issues:**
| Symptom | Likely Cause |
|---------|--------------|
| Drive letter in path | Project root not computed correctly |
| Temp dir in path | Using BAT file_map directly instead of relative paths |
| Missing files | Cross-drive dependencies not included |
| Wrong structure | Custom project path not respected |

### 3. Dependency Resolution

**For scenes with textures (`material_textures.blend`):**
- [ ] All texture files uploaded
- [ ] Texture paths are relative to blend file
- [ ] No absolute paths to user's machine

**For scenes with linked libraries (`doubly_linked.blend`):**
- [ ] All linked .blend files uploaded
- [ ] Library paths rewritten correctly
- [ ] Recursive dependencies included (lib → lib → lib)

**For scenes with sequences:**
- [ ] All sequence frames uploaded (check count)
- [ ] Frame numbering preserved
- [ ] UDIM tiles included if applicable

### 4. Render Output

**Go to:** Job → Render Output / Preview

**Check the rendered image for:**

| Issue | What to Look For | Indicates |
|-------|------------------|-----------|
| Pink textures | Bright pink/magenta areas | Missing texture files |
| Missing objects | Empty areas where objects should be | Linked library not resolved |
| Wrong materials | Different appearance than expected | Texture path wrong |
| Black render | Completely black output | Major error, check logs |
| Partial render | Image cut off or incomplete | Memory/crash issue |

### 5. Job Logs

**Go to:** Job → Logs

**Search for these error patterns:**

```
ERROR: "file not found"        → Missing dependency
ERROR: "cannot open"           → Path resolution failed
ERROR: "permission denied"     → File access issue
WARNING: "missing texture"     → Texture not uploaded
WARNING: "library not found"   → Linked file missing
```

**Good log patterns:**
```
INFO: "Loading blend file..."
INFO: "Found X textures"
INFO: "Starting render..."
INFO: "Render complete"
```

## Test Scenario Details

### Scenario: simple_no_deps
**File:** `basic_file.blend`

**What it tests:**
- Basic upload without dependencies
- Job creation flow
- Single file handling

**Expected on farm:**
- 1 file uploaded (just the .blend)
- Simple cube renders correctly
- No missing file warnings

### Scenario: with_textures
**File:** `material_textures.blend`

**What it tests:**
- Texture dependency discovery
- Relative path preservation
- Image file upload

**Expected on farm:**
- 4+ files uploaded (.blend + textures)
- Textures in `textures/Bricks/` subfolder
- Brick material renders with correct texture

**Failure indicators:**
- Pink/magenta bricks = textures missing
- Flat color = texture path wrong

### Scenario: linked_libraries
**File:** `doubly_linked.blend`

**What it tests:**
- Linked .blend resolution
- Recursive dependency tracking
- Library path rewriting

**Expected on farm:**
- 6+ files uploaded
- `linked_cube.blend` included
- `basic_file.blend` included (linked from linked_cube)
- `material_textures.blend` included
- All linked objects visible in render

**Failure indicators:**
- Missing objects = library not found
- "Library not found" in logs
- Objects present but wrong material = texture path issue

### Scenario: unicode_filename
**File:** `basic_file_ñønæščii.blend`

**What it tests:**
- Unicode character handling in filenames
- NFC normalization
- Cross-platform encoding

**Expected on farm:**
- File uploaded with Unicode name preserved
- No encoding errors in logs
- Renders correctly

**Failure indicators:**
- File not found (encoding mismatch)
- Garbled filename in job list
- 404 errors during download

### Scenario: image_sequence
**File:** `image_sequencer.blend`

**What it tests:**
- Image sequence detection
- Multiple file upload (sequence frames)
- VSE strip handling

**Expected on farm:**
- Many files uploaded (all sequence frames)
- Frames in `imgseq/` subfolder
- VSE plays sequence correctly in render

**Failure indicators:**
- Missing frames in sequence
- Black frames in output
- "Image not found" warnings

## Cleanup

After verification, you can delete test jobs:

1. Go to Job List
2. Select jobs starting with `SULU_TEST_`
3. Delete them to clean up

Or use the API:
```python
# This is just documentation - don't actually run
# DELETE /api/jobs/{job_id}
```

## Reporting Issues

If you find issues:

1. Note which test scenario failed
2. Screenshot the job details/files
3. Copy relevant log entries
4. Check this verification guide for known patterns
5. Report with:
   - Test scenario name
   - Expected vs actual behavior
   - Screenshots/logs
   - session.json project ID (not token!)
