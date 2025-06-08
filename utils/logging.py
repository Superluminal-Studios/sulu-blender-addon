import sys
import traceback
import bpy


def report_exception(op: bpy.types.Operator, exc: Exception, message: str, cleanup=None):
    """Log *exc* with full traceback, show a concise UI message and run *cleanup* if given."""
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    op.report({"ERROR"}, message)
    if callable(cleanup):
        cleanup()
    return {"CANCELLED"}