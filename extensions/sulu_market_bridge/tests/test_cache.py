from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from sulu_bridge import ArtifactCache, ArtifactSpec, CacheError


class ArtifactCacheTests(unittest.TestCase):
    def test_verified_content_is_atomically_cached_and_reused(self) -> None:
        content = b"verified blend fixture"
        spec = ArtifactSpec(hashlib.sha256(content).hexdigest(), len(content))
        with tempfile.TemporaryDirectory() as directory:
            cache = ArtifactCache(directory)
            first = cache.materialize(
                spec, lambda consume: (consume(content[:5]), consume(content[5:]))
            )
            self.assertFalse(first.reused)
            self.assertEqual(first.path.read_bytes(), content)

            called = False

            def should_not_download(consume) -> None:  # noqa: ANN001
                nonlocal called
                called = True
                consume(content)

            second = cache.materialize(spec, should_not_download)
            self.assertTrue(second.reused)
            self.assertFalse(called)
            self.assertEqual(second.path, first.path)

    def test_hash_size_and_partial_files_fail_closed(self) -> None:
        content = b"expected"
        spec = ArtifactSpec(hashlib.sha256(content).hexdigest(), len(content))
        with tempfile.TemporaryDirectory() as directory:
            cache = ArtifactCache(directory)
            with self.assertRaisesRegex(CacheError, "SHA-256"):
                cache.materialize(spec, lambda consume: consume(b"tampered"))
            target = cache.path_for(spec)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob("*.partial")), [])

            with self.assertRaisesRegex(CacheError, "declared size"):
                cache.materialize(spec, lambda consume: consume(content + b"x"))
            self.assertFalse(target.exists())

    def test_corrupt_existing_cache_entry_is_replaced(self) -> None:
        content = b"correct"
        spec = ArtifactSpec(hashlib.sha256(content).hexdigest(), len(content))
        with tempfile.TemporaryDirectory() as directory:
            cache = ArtifactCache(directory)
            target = cache.path_for(spec)
            target.parent.mkdir(parents=True)
            target.write_bytes(b"corrupt")
            result = cache.materialize(spec, lambda consume: consume(content))
            self.assertFalse(result.reused)
            self.assertEqual(target.read_bytes(), content)

    def test_invalid_content_address_cannot_escape_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = ArtifactCache(directory)
            with self.assertRaisesRegex(CacheError, "valid SHA-256"):
                cache.materialize(
                    ArtifactSpec("../../outside", 1),
                    lambda consume: consume(b"x"),
                )
            self.assertEqual(list(Path(directory).rglob("outside")), [])


if __name__ == "__main__":
    unittest.main()
