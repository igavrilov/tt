"""Menu actions against temporary logs, without macOS or GUI dependencies."""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tt


class MenuItem:
    def __init__(self, title, callback=None):
        self.title = title
        self.callback = callback

    def set_callback(self, callback):
        self.callback = callback


class App:
    def __init__(self, name, title, quit_button, icon, template):
        self.title = title
        self.icon = icon
        self.template = template


rumps = SimpleNamespace(App=App, MenuItem=MenuItem, Timer=Mock(),
                        alert=Mock(), quit_application=Mock())
with patch.dict(sys.modules, {
    "rumps": rumps,
    "AppKit": SimpleNamespace(
        NSApplication=Mock(), NSApplicationActivationPolicyAccessory=1,
        NSAlert=Mock(), NSAlertFirstButtonReturn=1000, NSDatePicker=Mock(),
        NSHourMinuteSecondDatePickerElementFlag=14, NSTextField=Mock(),
        NSTextFieldAndStepperDatePickerStyle=0, NSView=Mock()),
    "Foundation": SimpleNamespace(NSDate=Mock()),
}):
    import tt_menubar


class MenuBarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        for name, value in (("TT_HOME", home), ("LOCK_FILE", home / "timer.lock")):
            p = patch.object(tt, name, value)
            p.start()
            self.addCleanup(p.stop)
        rumps.alert.reset_mock()
        rumps.quit_application.reset_mock()
        self.start_input = SimpleNamespace(task="backend work", at=None, cancel=False)
        prompt = patch.object(tt_menubar, "prompt_start", side_effect=lambda project:
                              None if self.start_input.cancel else
                              (self.start_input.task, self.start_input.at or
                               tt.now_local().isoformat(timespec="seconds")))
        prompt.start()
        self.addCleanup(prompt.stop)
        self.app = tt_menubar.TimerApp("p")

    def assert_running(self, running):
        self.assertEqual(self.app.start_item.callback is None, running)
        self.assertEqual(self.app.stop_item.callback is not None, running)
        self.assertEqual(self.app.discard_item.callback is not None, running)
        self.assertEqual(tt.LOCK_FILE.exists(), running)
        self.assertIsNone(self.app.session_item.callback)
        self.assertIsNone(self.app.today_item.callback)
        if not running:
            self.assertEqual(self.app.title, "--:--")

    def sessions(self):
        year = tt.now_local().year
        return tt.pair_sessions(tt.read_events("p", year - 1, year))

    def test_initial_and_start_stop(self):
        self.assert_running(False)
        self.assertEqual(self.app.title, "--:--")
        self.assertTrue(self.app.template)
        self.assertTrue(Path(self.app.icon).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual([item.title for item in self.app.menu if item],
                         ["No active session", "Today: 00:00:00", "Start", "Stop", "Discard", "Quit"])
        self.app.start()
        self.assert_running(True)
        self.assertEqual(self.app.title, "00:00")
        self.assertEqual(self.app.menu[0].title, "backend work")
        self.app.start()  # stale/programmatic click cannot open another session
        self.assertEqual(len(self.sessions()), 1)
        self.app.stop()
        self.assert_running(False)
        self.assertIsNotNone(self.sessions()[0]["stop"])
        self.assertEqual(self.app.session_item.title, "No active session")
        self.app.stop()
        self.app.discard()
        self.assertEqual(len(self.sessions()), 1)

    def test_today_total_loads_existing_project_logs_and_rolls_over(self):
        now = datetime.fromisoformat("2026-12-31T12:00:00+00:00")
        tt.append_line(tt.year_file("p", 2026), "\n".join([
            "2026-12-30T09:00:00+00:00 START old yesterday",
            "2026-12-30T10:00:00+00:00 STOP old",
            "2026-12-31T09:00:00+00:00 START done completed",
            "2026-12-31T10:00:30+00:00 STOP done",
            "2026-12-31T10:00:00+00:00 START discarded ignored",
            "2026-12-31T11:00:00+00:00 DISCARD discarded",
            "2026-12-31T11:30:00+00:00 START cli running",
        ]))
        tt.append_line(tt.year_file("other", 2026),
                       "2026-12-31T09:00:00+00:00 START other ignored")
        with patch.object(tt, "now_local", return_value=now):
            self.app = tt_menubar.TimerApp("p")
        self.assertEqual(self.app.today_item.title, "Today: 01:30:30")
        self.assertEqual(self.app.title, "--:--")
        self.assertIsNone(self.app.sid)  # the total does not adopt CLI sessions
        with patch.object(tt, "now_local", return_value=now + timedelta(minutes=1)):
            self.app.refresh()
        self.assertEqual(self.app.today_item.title, "Today: 01:31:30")
        with patch.object(tt, "now_local", return_value=now + timedelta(days=1)):
            self.app.refresh()
        self.assertEqual(self.app.today_item.title, "Today: 00:00:00")

    def test_today_total_includes_active_stopped_and_discarded_sessions(self):
        now = datetime.fromisoformat("2026-07-01T12:00:00+00:00")
        self.start_input.at = (now - timedelta(hours=1)).isoformat()
        with patch.object(tt, "now_local", return_value=now):
            self.app.start()
            self.assertEqual(self.app.today_item.title, "Today: 01:00:00")
            self.app.stop()
            self.assertEqual(self.app.today_item.title, "Today: 01:00:00")
            self.start_input.at = (now - timedelta(minutes=30)).isoformat()
            self.app.start()
            self.assertEqual(self.app.today_item.title, "Today: 01:30:00")
            self.app.discard()
            self.assertEqual(self.app.today_item.title, "Today: 01:00:00")

    def test_long_session_name_stays_in_menu_only(self):
        task = "A long session name that should not be truncated in the menu"
        self.start_input.task = task
        self.app.start()
        self.assertEqual(self.app.session_item.title, task)
        self.assertEqual(self.app.title, "00:00")
        self.assertIsNone(self.app.session_item.callback)

    def test_cancel_does_not_write(self):
        self.start_input.cancel = True
        self.app.start()
        self.assert_running(False)
        self.assertEqual(self.sessions(), [])

    def test_task_is_single_line_and_blank_is_untitled(self):
        self.start_input.task = "task\nwith\tspaces"
        self.app.start()
        self.assertEqual(self.sessions()[0]["task"], "task with spaces")
        self.app.stop()
        self.start_input.task = "   "
        self.app.start()
        self.assertEqual(tt.open_sessions("p")[self.app.sid]["task"], "(untitled)")

    def test_selected_start_time_updates_log_and_elapsed_time(self):
        now = tt.now_local().replace(hour=14, minute=30, second=10, microsecond=0)
        started = now.replace(hour=13, minute=0, second=0)
        self.start_input.at = started.isoformat()
        with patch.object(tt, "now_local", return_value=now):
            self.app.start()
        self.assert_running(True)
        self.assertEqual(self.sessions()[0]["start"], started)
        self.assertEqual(self.app.title, "01:30")

    def test_discard_preserves_other_sessions_and_log(self):
        other = tt.cmd_start("p", "CLI task", no_timer=True)
        self.app.start()
        sid = self.app.sid
        self.app.discard()
        self.assert_running(False)
        self.assertEqual(list(tt.open_sessions("p")), [other])
        self.assertEqual([s["sid"] for s in self.sessions()], [other])
        text = tt.year_file("p", tt.now_local().year).read_text()
        self.assertIn(f"START {sid}", text)
        self.assertIn(f"DISCARD {sid}", text)

    def test_external_stop_updates_menu(self):
        self.app.start()
        tt.cmd_stop("p", self.app.sid, None)
        self.app.refresh()
        self.assert_running(False)
        self.assertEqual(self.app.title, "--:--")
        self.assertEqual(self.app.session_item.title, "No active session")

    def test_existing_timer_lock_is_not_stolen(self):
        tt.acquire_lock("another timer")
        self.app.start()
        self.assertIsNone(self.app.sid)
        self.assertIn("another timer", tt.LOCK_FILE.read_text())
        rumps.alert.assert_called_once()
        self.assertEqual(self.sessions(), [])

    def test_failed_start_releases_lock(self):
        with patch.object(tt, "append_line", side_effect=OSError("disk full")):
            self.app.start()
        self.assert_running(False)
        rumps.alert.assert_called_once()

    def test_failed_stop_and_discard_keep_session(self):
        self.app.start()
        with patch.object(tt, "append_line", side_effect=OSError("disk full")):
            self.app.stop()
            self.assert_running(True)
            self.app.discard()
            self.assert_running(True)
        self.assertIsNone(self.sessions()[0]["stop"])
        self.assertEqual(rumps.alert.call_count, 2)

    def test_quit_saves_and_exits(self):
        self.app.start()
        self.app.quit()
        self.assert_running(False)
        self.assertIsNotNone(self.sessions()[0]["stop"])
        rumps.quit_application.assert_called_once()

    def test_quit_does_not_exit_if_save_fails(self):
        self.app.start()
        with patch.object(tt, "append_line", side_effect=OSError("disk full")):
            self.app.quit()
        self.assert_running(True)
        rumps.quit_application.assert_not_called()
        rumps.alert.assert_called_once()

    def test_default_and_explicit_cli_launch(self):
        with patch.dict(sys.modules, {"tt_menubar": tt_menubar}), \
                patch.object(tt.sys, "platform", "darwin"), patch.object(tt_menubar, "run") as run:
            tt.main([])
            run.assert_called_once_with("default")
            run.reset_mock()
            tt.main(["-p", "acme", "menubar"])
            run.assert_called_once_with("acme")

    def test_single_app_lock_is_released_on_exit(self):
        with patch.object(tt_menubar, "TimerApp") as app:
            def try_second_app():
                with self.assertRaisesRegex(SystemExit, "already running"):
                    tt_menubar.run("p")
            app.return_value.run.side_effect = try_second_app
            tt_menubar.run("p")
            app.return_value.run.side_effect = None
            tt_menubar.run("p")  # OS lock releases even though the file remains

    def test_elapsed_time_and_cross_year_stop(self):
        start = tt.now_local().replace(month=12, day=31, hour=23, minute=59, second=0)
        stop = start.replace(year=start.year + 1, month=1, day=1, hour=0, minute=1)
        with patch.object(tt, "now_local", return_value=start):
            self.app.start()
        with patch.object(tt, "now_local", return_value=stop):
            self.app.refresh()
            self.assertEqual(self.app.title, "00:02")
            self.app.stop()
        self.assertIn("STOP", tt.year_file("p", start.year).read_text())
        self.assertFalse(tt.year_file("p", stop.year).exists())


class StartDialogTests(unittest.TestCase):
    def test_current_time_default_and_selected_time_result(self):
        now = tt.now_local().replace(microsecond=0)
        selected = now.replace(hour=9, minute=15, second=30)
        alert = tt_menubar.NSAlert.alloc.return_value.init.return_value
        alert.runModal.return_value = tt_menubar.NSAlertFirstButtonReturn
        picker = tt_menubar.NSDatePicker.alloc.return_value.initWithFrame_.return_value
        picker.dateValue.return_value.timeIntervalSince1970.return_value = selected.timestamp()
        task = tt_menubar.NSTextField.alloc.return_value.initWithFrame_.return_value
        task.stringValue.return_value = "selected task"
        with patch.object(tt, "now_local", return_value=now), \
                patch.object(tt, "last_task", return_value="previous task"):
            self.assertEqual(tt_menubar.prompt_start("p"),
                             ("selected task", selected.isoformat(timespec="seconds")))
        task.setStringValue_.assert_called_with("previous task")
        tt_menubar.NSDate.dateWithTimeIntervalSince1970_.assert_called_with(now.timestamp())
        picker.setDateValue_.assert_called_with(
            tt_menubar.NSDate.dateWithTimeIntervalSince1970_.return_value)

    def test_cancel_returns_no_input(self):
        alert = tt_menubar.NSAlert.alloc.return_value.init.return_value
        alert.runModal.return_value = 1001
        with patch.object(tt, "last_task", return_value=None):
            self.assertIsNone(tt_menubar.prompt_start("p"))


if __name__ == "__main__":
    unittest.main()
