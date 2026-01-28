# Blender Asset Tracer (BAT) tests
#
# These tests verify BAT's core functionality:
# - Blendfile parsing and DNA reading
# - Dependency tracing
# - Pack/rewrite operations
# - Path handling (BlendPath, bpathlib)
#
# Many tests require actual .blend files located in tests/bat/blendfiles/

from .abstract_test import AbstractBlendFileTest

__all__ = ["AbstractBlendFileTest"]
