"""Native macOS menu-bar interface; the CLI remains dependency-free."""
import fcntl
from datetime import datetime
from pathlib import Path

import rumps
from AppKit import (
    NSAlert, NSAlertFirstButtonReturn, NSApplication, NSApplicationActivationPolicyAccessory,
    NSDatePicker, NSHourMinuteSecondDatePickerElementFlag, NSTextField,
    NSTextFieldAndStepperDatePickerStyle, NSView,
)
from Foundation import NSDate

import tt


def prompt_start(project):
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Start session")
    alert.setInformativeText_(f"Project: {project}")
    alert.addButtonWithTitle_("Start")
    alert.addButtonWithTitle_("Cancel")
    view = NSView.alloc().initWithFrame_(((0, 0), (320, 80)))
    task = NSTextField.alloc().initWithFrame_(((70, 48), (250, 24)))
    task.setStringValue_(tt.last_task(project) or "")
    task.setAccessibilityLabel_("Task")
    start_time = NSDatePicker.alloc().initWithFrame_(((70, 8), (180, 24)))
    start_time.setDatePickerStyle_(NSTextFieldAndStepperDatePickerStyle)
    start_time.setDatePickerElements_(NSHourMinuteSecondDatePickerElementFlag)
    start_time.setDateValue_(NSDate.dateWithTimeIntervalSince1970_(tt.now_local().timestamp()))
    start_time.setAccessibilityLabel_("Start time")
    for title, y in (("Task", 52), ("Time", 12)):
        label = NSTextField.labelWithString_(title)
        label.setFrame_(((0, y), (65, 20)))
        view.addSubview_(label)
    view.addSubview_(task)
    view.addSubview_(start_time)
    alert.setAccessoryView_(view)
    alert.window().setInitialFirstResponder_(task)
    if alert.runModal() != NSAlertFirstButtonReturn:
        return None
    task.validateEditing()
    start_time.validateEditing()
    at = datetime.fromtimestamp(start_time.dateValue().timeIntervalSince1970()).astimezone()
    return task.stringValue(), at.isoformat(timespec="seconds")


class TimerApp(rumps.App):
    def __init__(self, project):
        super().__init__("tt", title="--:--", quit_button=None,
                         icon=str(Path(__file__).with_name("tt_clock.png")), template=True)
        self.project = project
        self.sid = None
        self.session_item = rumps.MenuItem("No active session")
        self.today_item = rumps.MenuItem("Today: 00:00:00")
        self.start_item = rumps.MenuItem("Start", callback=self.start)
        self.stop_item = rumps.MenuItem("Stop")
        self.discard_item = rumps.MenuItem("Discard")
        self.menu = [self.session_item, self.today_item, None,
                     self.start_item, self.stop_item, self.discard_item, None,
                     rumps.MenuItem("Quit", callback=self.quit)]
        self.timer = rumps.Timer(self.refresh, 1)
        self.refresh()
        self.timer.start()

    def refresh(self, _=None):
        now = tt.now_local()
        today = now.date()
        sessions = tt.pair_sessions(tt.read_events(self.project, today.year, today.year))
        _, totals, _ = tt.build_report(sessions, today, today, None, now, today)
        self.today_item.title = f"Today: {tt.fmt_hms(totals['secs'])}"
        session = tt.open_sessions(self.project).get(self.sid) if self.sid else None
        if self.sid and session is None:  # also notice an external CLI stop/dismiss
            self.sid = None
            tt.release_lock()
        running = self.sid is not None
        self.start_item.set_callback(None if running else self.start)
        self.stop_item.set_callback(self.stop if running else None)
        self.discard_item.set_callback(self.discard if running else None)
        if session:
            elapsed = max(0, (now - session["start"]).total_seconds())
            self.title = tt.fmt_hms(elapsed).rsplit(":", 1)[0]
            self.session_item.title = session["task"]
        else:
            self.title = "--:--"
            self.session_item.title = "No active session"
        return session

    def start(self, _=None):
        try:
            self.refresh()
            if self.sid:
                return
            response = prompt_start(self.project)
            if response is None:
                return
            task, at = response
            task = " ".join(task.split()) or "(untitled)"
            tt.acquire_lock(task)
            try:
                self.sid = tt.cmd_start(self.project, task, no_timer=True, at=at)
            except BaseException:
                tt.release_lock()
                raise
            self.refresh()
        except (OSError, ValueError, SystemExit) as exc:
            rumps.alert(title="Could not start session", message=str(exc))

    def finish(self, discard=False):
        session = self.refresh()
        if session is None:
            return
        if discard:
            tt.append_line(session["file"],
                           f"{tt.now_local().isoformat(timespec='seconds')} DISCARD {self.sid}")
        else:
            tt.cmd_stop(self.project, self.sid, at=None)
        self.sid = None
        tt.release_lock()
        self.refresh()

    def stop(self, _=None):
        try:
            self.finish()
        except (OSError, ValueError, SystemExit) as exc:
            rumps.alert(title="Could not stop session", message=str(exc))

    def discard(self, _=None):
        try:
            self.finish(discard=True)
        except (OSError, ValueError, SystemExit) as exc:
            rumps.alert(title="Could not discard session", message=str(exc))

    def quit(self, _=None):
        try:
            self.finish()
        except (OSError, ValueError, SystemExit) as exc:
            rumps.alert(title="Could not save session", message=str(exc))
            return  # keep the app open so the user can retry without losing time
        self.timer.stop()
        rumps.quit_application()


def run(project):
    tt.TT_HOME.mkdir(parents=True, exist_ok=True)
    with (tt.TT_HOME / "menubar.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("tt: the menu-bar app is already running")
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        TimerApp(project).run()
