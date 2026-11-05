# tt - Time Tracking tool

## Description

`tt` is a personal time tracking tool aimed to track working hours and generate report for invoicing.

Implemented in **Python 3.11+**. The CLI uses only the standard library; the optional macOS
menu-bar interface uses `rumps` and its Cocoa bridge. Both share the existing plain-text logs.

## Menu-bar interface

`tt` with no subcommand, or `tt menubar`, launches a menu-bar-only macOS app. The menu bar shows
a monochrome clock icon and elapsed hours and minutes (`HH:MM`), or `--:--` while idle.
Logs and reports retain second-level precision.
The full session name is the first, non-clickable menu item (`No active session` while idle).
A second non-clickable item shows `Today: HH:MM:SS` for the selected project, refreshed every
second using the same start-date-based totals as `tt today` (including open sessions, excluding
discarded sessions).

- **Start** prompts for a task and a start time (default: current local time), and is disabled
  while running. The selected time is logged and used to calculate elapsed time.
- **Stop** saves the active session and is disabled while stopped.
- **Discard** excludes the active session from reports and is disabled while stopped.
- **Quit** saves an active session before exiting; a save failure keeps the app open.

The app manages only sessions it starts, shares the interactive CLI timer lock, and allows
independent non-interactive CLI sessions. Only one menu-bar app runs at a time. It uses the
configured default project unless `-p/--project` is provided. Crashed sessions are recovered
through the CLI, not automatically adopted.

## CLI specs

`tt` retains the following commands:

- `tt s[tart] [optional task name]` - start tracking of a new task; prints the new session id
- `tt c[ontinue]` or `tt r[esume]` - continue last task (starts a new task reusing the last task's name)
- `tt stop [--session ID]` - stop a running session (writes a `STOP` line). With no `--session`:
  if exactly one session is open, stop it; if several are open, exit non-zero and list the open ids.
- `tt report start_date [end_date]` - build a report (see **Report**), accepts `--csv`, `--json`
  and `--html` for different output formats. Default (no flag) is a plain-text table to stdout.

All commands accept `-p`/`--project NAME` to select the project. If omitted, the project is
`config.default_project`, falling back to `default`.

### Sessions and concurrency

Every `start`/`continue` opens an independent session identified by a short random id (e.g.
`a1b2`), printed to stdout so a caller can capture it. Sessions are **not** mutually exclusive:
several may be open at once — different AI harnesses (or a human and a harness) can track in the
same project in parallel without interfering. `stop` closes a session **by id**, never "whatever
is currently open," so concurrent starts and stops can never steal each other's session.

Because every write is a pure append of a self-contained line, `O_APPEND` makes concurrent writes
atomic — no lock needed, and there is no read-then-write step to race on.

`start` no longer auto-closes anything (there is no single "current" session to close). A session
that is never stopped (e.g. a killed process) simply stays open; see **Report → Open (unclosed)
sessions** for how a report handles it. Clean up a stale open session with `tt stop --session ID`
or by editing the log.

### Interactive vs non-interactive

`start`/`continue` write the `START` line, then behave by context so the tool is usable both by a
human and by an AI harness:

- **Interactive** (stdout is a TTY): show a timer updating every second; `Ctrl+C` — or
  `tt stop --session ID` from another shell — writes the `STOP` line for this session and exits.
- **Non-interactive** (piped/no TTY, or `--no-timer`): write `START`, print the session id, and
  exit immediately without blocking. The harness later calls `tt stop --session ID`.

## Report

`start_date` and `end_date` are `YYYY-MM-DD`. `end_date` defaults to today. The range is
**inclusive** on both ends (by local calendar day) and may span multiple year log files.

A detailed report: one row per session, grouped by **start date**, sorted by start time. Sessions
are paired by id — each `START <id>` matches its `STOP <id>` regardless of interleaving. Columns:

| date | task | start | end | duration | amount |
|------|------|-------|-----|----------|--------|

- `date` — `DD/MM/YYYY` of the session start
- `start` / `end` — local clock times `HH:MM`
- `duration` — `HH:MM:SS`
- `amount` — `hours × rate.amount` in `rate.currency`; blank if the project has no rate

### Open (unclosed) sessions

A session with no `STOP` is handled by whether the report is live or historical:

- **`end_date >= today`** (live report): the session is a running timer — count its duration up to
  `now`.
- **`end_date < today`** (closed past period): the session was forgotten or the process crashed —
  its real end is unknown, so **do not fabricate a duration**. Show the row with an `OPEN` marker
  and zero duration, **exclude it from the totals**, and warn on stderr with the session id, task,
  and start time. Fix it by editing the log (or `tt stop --session ID --at <timestamp>` to backfill).

### HTML output (primary format)

`--html` is the main output — meant to be opened in a browser and printed to PDF, so it must
look clean on paper. A self-contained HTML page (inline `<style>`, no external assets), with a
header block containing:

- a **caption/title** (report + project name)
- the **date range**
- **totals**: Total duration (`HH:MM:SS`) and Amount (sum, in the project currency)

followed by the detailed table. Use print-friendly styling (readable margins, page-friendly
widths, no dark backgrounds).

`--csv`/`--json` emit the same rows for machine use. The default plain-text table and all
formats share the same header totals.

## Database

`tt` is using an append-only plain text log. Timestamps are local time **with UTC offset** so
reports stay correct across DST and travel (`datetime.now().astimezone().isoformat()`).

The menu-bar Discard action appends `<timestamp> DISCARD <id>`. This closes and excludes the
session without rewriting the log or affecting concurrent sessions.

A `START` line is `<timestamp> START <id> <task name>`; the id is a short token, the task name is
everything after it. A `STOP` line is `<timestamp> STOP <id>`. `START`/`STOP` pair by id, so
concurrent sessions can interleave freely in the log:

```log
2026-07-01T09:03:12-04:00 START a1b2 backend work
2026-07-01T09:05:00-04:00 START c3d4 writing report
2026-07-01T10:15:44-04:00 STOP a1b2
2026-07-01T10:20:00-04:00 STOP c3d4
```

Logs are written as plain text files under `~/.tt/<project>/logs`, **one file per year** named
`YYYY.log`:

`~/.tt/badger/logs/2026.log` - the 2026 log for project "badger"

A whole session lives in **one file**: `STOP` is appended to the file where its `START` was
written, so a session that crosses midnight (or a year boundary, e.g. Dec 31 → Jan 1) stays intact
in its start year's file. A single-file-per-year log means paired `START`/`STOP` and open-session
detection are done in one scan — no cross-file pairing. Files stay tiny (a personal year is a few
thousand lines).

The log is the single source of truth. "Which sessions are open?" and "what was the last task?"
are both derived by scanning the current year's log — there are no separate `current`/`last` state
files to drift out of sync. Fix a mistracked entry by editing the log in any text editor.

## Config

`~/.tt/config.toml` (optional). Global keys plus a `[project.<name>]` table per project:

```toml
default_project = "badger"

[project.badger]
rate.amount = 120
rate.currency = "USD"
```

`report` multiplies tracked hours by `rate.amount` to produce an invoice total in `rate.currency`.
A project with no rate configured reports hours only (no amount). Read-only via `tomllib`; edit by
hand.
