"""Build provenance patched into packaged add-on releases."""

# Source checkouts are development builds. deploy.py changes this value only in
# the staged release artifact, so local installs never masquerade as a release.
BUILD_CHANNEL = "development"
# Releases default to production. The lab build sets this while packaging.
BUILD_ENVIRONMENT = "production"
