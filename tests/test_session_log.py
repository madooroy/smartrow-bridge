import logging
import tempfile
import unittest
from pathlib import Path

from smartrow_bridge import session_log


class SessionLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state" / "sessions.log"  # directory created by install()
        self.logger = logging.getLogger("smartrow_bridge.test_session_log")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.handler = session_log.install(str(self.path), logger_name=self.logger.name)

    def tearDown(self):
        self.logger.removeHandler(self.handler)
        self.handler.close()
        self.tmp.cleanup()

    def lines(self):
        return self.path.read_text(encoding="utf-8").splitlines()

    def test_keeps_milestones_and_warnings_only(self):
        log = self.logger
        # Lines the bridge really logs (from captures/bridge.log and bridge.py).
        log.info("Connected to pulley AA:BB:CC:DD:EE:01")
        log.info("Scanning on hci0 for the SmartRow pulley...")  # routine: dropped
        log.info("SmartRow app subscribed (connection 0x0018)")
        log.info("Rower Data subscribed by AA:BB:CC:DD:EE:02 (connection 0x0019)")
        log.debug("FTMS 59 W, 19.8 spm, 38 m, 178 s/500m")  # per-second: dropped
        log.info("Data flow, last 60 s: 600 pulley packets in, 600 forwarded to SmartRow app, "
                 "60 FTMS updates to fitness app | 236 m, 44 strokes")
        log.warning("Pulley connection failed (TimeoutError); retrying in 5 s")

        lines = self.lines()
        self.assertTrue(lines[0].startswith(session_log.START_MARKER))
        body = "\n".join(lines[1:])
        for kept in ("Connected to pulley", "SmartRow app subscribed", "Rower Data subscribed",
                     "Data flow", "WARNING"):
            self.assertIn(kept, body)
        self.assertNotIn("Scanning", body)
        self.assertNotIn("FTMS 59 W", body)
        self.assertEqual(len(lines), 6)

    def test_each_run_starts_a_new_block(self):
        self.logger.info("Data flow, last 60 s: 1 pulley packets in, 0 forwarded to SmartRow app, "
                         "0 FTMS updates to fitness app | 0 m, 0 strokes")
        second = session_log.install(str(self.path), logger_name="smartrow_bridge.second_run")
        try:
            markers = [l for l in self.lines() if l.startswith(session_log.START_MARKER)]
            self.assertEqual(len(markers), 2)
        finally:
            second.close()

    def test_unwritable_path_disables_quietly(self):
        blocker = Path(self.tmp.name) / "a_file"
        blocker.write_text("x")
        self.assertIsNone(session_log.install(str(blocker / "sessions.log"), logger_name="x"))


if __name__ == "__main__":
    unittest.main()
