---
name: time-tracking
description: >
  Track time spent on tasks with the `tt` CLI. Use when an agent/harness should
  log its working time — start a session before beginning a unit of work and stop
  it when done, then generate reports. Works non-interactively and is safe to run
  from many parallel workers.
---

# Time tracking with `tt`

`tt` logs work sessions to an append-only text file and produces invoice-ready reports.
As a harness, drive it **non-interactively**: `start` prints a session id and exits (no
blocking timer), and `stop` closes that id.

## Track a unit of work

Capture the id from `start`, do the work, then `stop` that id:

```sh
id=$(tt -p PROJECT start "short task description" --no-timer)
# ...do the work...
tt -p PROJECT stop --session "$id"
```

- `-p PROJECT` selects the project (omit to use `config.default_project`). Logs live at
  `~/.tt/<project>/logs/YYYY.log`.
- `--no-timer` is optional when stdout isn't a TTY (it's auto-detected), but pass it
  explicitly to be safe — it guarantees `start` returns immediately.
- Always keep the printed id and pass it to `stop --session`. Do not use bare `tt stop`
  from a harness: it only works when exactly one session is open and will error otherwise.
- To log work whose start time already passed, backdate it with `--at` (also on `stop`):
  `-1`/`-1:30` = now minus 1h/1h30m, `20:00`/`7` = today at that clock time, or a full ISO
  timestamp. E.g. `tt -p PROJECT start "desc" --at -1:30` records the `START` 90 min ago and
  returns immediately; stop it with `stop --session ID --at <end>`.
- `tt -p PROJECT today` (alias `t`, `tail`) prints today's raw log lines — handy to check
  which sessions are currently open.

## Concurrency

Sessions are independent and identified by id, so multiple workers can track in the same
project at once without interfering — `stop --session ID` never closes another worker's
session. No coordination or locking needed.

## If a session is left open

A crashed/forgotten session stays open. It's counted up to *now* in a live report, but a
report over a past period flags it and excludes it. Fix by editing the log or backfilling
the stop time:

```sh
tt -p PROJECT stop --session ID --at 2026-06-30T18:00:00
```

## Reporting

```sh
tt -p PROJECT report 2026-06-01 2026-06-30            # plain text (default)
tt -p PROJECT report 2026-06-01 2026-06-30 --csv      # CSV
tt -p PROJECT report 2026-06-01 2026-06-30 --json     # JSON (machine-readable)
tt -p PROJECT report 2026-06-01 2026-06-30 --html     # printable HTML
```

Dates are `YYYY-MM-DD`; `end_date` defaults to today; the range is inclusive. Use `--json`
when you need to parse the result programmatically.
