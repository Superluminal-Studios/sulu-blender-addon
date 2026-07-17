from __future__ import annotations

import threading
import unittest

from sulu_bridge import CancelledError, ModalPreparationWorker


class ModalPreparationWorkerTests(unittest.TestCase):
    def test_start_is_one_shot_and_publishes_result(self) -> None:
        calls: list[dict[str, object]] = []

        def prepare(settings, cancellation):  # noqa: ANN001
            self.assertFalse(cancellation.cancelled)
            calls.append(settings)
            return "prepared"

        worker = ModalPreparationWorker({"descriptor": "fixture.suluasset"}, prepare)

        self.assertTrue(worker.start())
        self.assertFalse(worker.start())
        self.assertTrue(worker.wait(timeout=2))
        self.assertEqual(calls, [{"descriptor": "fixture.suluasset"}])
        self.assertIsNotNone(worker.outcome)
        self.assertEqual(worker.outcome.result, "prepared")
        self.assertIsNone(worker.outcome.error)

    def test_settings_are_copied_before_worker_start(self) -> None:
        settings = {"descriptor": "original.suluasset"}
        worker = ModalPreparationWorker(settings, lambda copied, _: copied["descriptor"])
        settings["descriptor"] = "mutated.suluasset"

        self.assertTrue(worker.start())
        self.assertTrue(worker.wait(timeout=2))
        self.assertEqual(worker.outcome.result, "original.suluasset")

    def test_cancel_is_idempotent_and_cooperatively_stops_worker(self) -> None:
        entered = threading.Event()
        released = threading.Event()

        def prepare(settings, cancellation):  # noqa: ANN001
            del settings
            entered.set()
            cancellation.register(released.set)
            cancellation.raise_if_cancelled()
            released.wait(timeout=2)
            cancellation.raise_if_cancelled()

        worker = ModalPreparationWorker({}, prepare)
        self.assertTrue(worker.start())
        self.assertTrue(entered.wait(timeout=2))

        worker.cancel()
        worker.cancel()

        self.assertTrue(worker.wait(timeout=2))
        self.assertTrue(worker.cancellation_requested)
        self.assertIsInstance(worker.outcome.error, CancelledError)
        self.assertIsNone(worker.outcome.result)

    def test_worker_captures_unexpected_error_for_main_thread(self) -> None:
        failure = RuntimeError("worker failed")

        def prepare(settings, cancellation):  # noqa: ANN001
            del settings, cancellation
            raise failure

        worker = ModalPreparationWorker({}, prepare)
        self.assertTrue(worker.start())
        self.assertTrue(worker.wait(timeout=2))
        self.assertIs(worker.outcome.error, failure)
        self.assertIsNone(worker.outcome.result)

    def test_wait_before_start_does_not_create_or_run_worker(self) -> None:
        worker = ModalPreparationWorker({}, lambda settings, cancellation: None)

        self.assertFalse(worker.wait(timeout=0))
        self.assertFalse(worker.started)
        self.assertIsNone(worker.outcome)


if __name__ == "__main__":
    unittest.main()
