import signal
import unittest
from datetime import datetime, timedelta
from unittest.mock import call, patch

import scheduler


class SchedulerLifecycleTests(unittest.TestCase):
    def tearDown(self):
        scheduler._shutdown_event.clear()

    def test_shutdown_signal_interrupts_sleep(self):
        scheduler._shutdown_event.clear()

        scheduler._handle_shutdown_signal(signal.SIGTERM, None)
        scheduler.smart_sleep_until(
            datetime.now(scheduler.WIB) + timedelta(hours=1),
            "test",
        )

        self.assertTrue(scheduler._shutdown_event.is_set())
        self.assertEqual(scheduler._shutdown_signal_name, "SIGTERM")

    @patch.object(scheduler.signal, "signal")
    @patch.object(scheduler, "ensure_single_scheduler_process")
    @patch.object(scheduler, "StateManager")
    @patch.object(scheduler, "send_operational_event")
    def test_main_sends_started_then_stopped(
        self,
        send_event,
        _state_manager,
        _ensure_single,
        _signal,
    ):
        def interrupt_sleep(_target, _label):
            scheduler._handle_shutdown_signal(signal.SIGTERM, None)

        with patch.object(scheduler.os.path, "exists", return_value=False), patch.object(
            scheduler, "next_event",
            return_value=(datetime.now(scheduler.WIB) + timedelta(hours=1), "test"),
        ), patch.object(scheduler, "smart_sleep_until", side_effect=interrupt_sleep):
            scheduler.main()

        events = [event_call.args[0] for event_call in send_event.call_args_list]
        self.assertEqual(events, ["STARTED", "STOPPED"])
        self.assertIn("Reason: SIGTERM", send_event.call_args_list[-1].args)


if __name__ == "__main__":
    unittest.main()
