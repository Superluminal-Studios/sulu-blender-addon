# Real-world integration tests
#
# IMPORTANT: These tests actually upload to the Superluminal farm!
# They use the session.json credentials and will create real jobs.
#
# Only run these tests when:
# 1. You have valid session.json credentials
# 2. You want to verify end-to-end upload functionality
# 3. You understand that jobs will be created on the farm
#
# Run with:
#   python tests/realworld/test_farm_upload.py --dry-run    # Validate without uploading
#   python tests/realworld/test_farm_upload.py              # Actually upload
