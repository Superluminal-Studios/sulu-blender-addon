from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


_tests_dir = Path(__file__).parent
_addon_dir = _tests_dir.parent


def _load_module_directly(name: str, filepath: Path):
    """Load a single .py file as a module, bypassing package __init__.py."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_submit_worker = _load_module_directly(
    "submit_worker_render_order",
    _addon_dir / "transfers" / "submit" / "submit_worker.py",
)


class TestRenderTaskOrder(unittest.TestCase):
    def test_render_task_order(self):
        refine_1_10 = [1, 9, 5, 3, 7, 2, 4, 6, 8, 10]
        cases = [
            ((1, 5, "LINEAR"), [1, 2, 3, 4, 5]),
            ((1, 10, "LINEAR", 2), [1, 3, 5, 7, 9]),
            ((1, 5, "LINEAR", 0), [1, 2, 3, 4, 5]),
            ((1, 10, "TEMPORAL_REFINE"), refine_1_10),
            ((1, 10, "PROGRESSIVE_STEPPING"), refine_1_10),
            ((1, 10, "TEMPORAL_REFINE", 2), [1, 9, 5, 3, 7]),
            ((10, 18, "TEMPORAL_REFINE"), [10, 18, 14, 12, 16, 11, 13, 15, 17]),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(_submit_worker._build_render_tasks(*args), expected)

    def test_temporal_refine_uses_largest_clean_stride(self):
        tasks = _submit_worker._build_render_tasks(1, 34, "TEMPORAL_REFINE")
        self.assertEqual(tasks[:8], [1, 33, 17, 9, 25, 5, 13, 21])
        self.assertEqual(sorted(tasks), list(range(1, 35)))


if __name__ == "__main__":
    unittest.main()
