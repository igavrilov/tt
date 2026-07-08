# tt

Personal time tracking with invoice-ready reports. Single Python file, stdlib only, plain-text logs.

## Install

Python 3.11+, no dependencies.

```sh
uv tool install .        # with uv (or: pipx install .)
pip install .            # with pip
```

Or skip packaging entirely and just symlink the script:

```sh
chmod +x tt.py
ln -s "$PWD/tt.py" ~/.local/bin/tt
```

You can also run it without installing: `uv run tt.py report 2026-05-01 2026-05-31`.

## Usage

```sh
tt start "backend work"         # start a task; prints a session id, shows a live timer (Ctrl+C stops)
tt start "call" --at -1:30      # backdate the start by 1h30m (no timer); see --at formats below
tt continue                     # start a new session reusing the last task's name (alias: resume)
tt stop                         # stop the running session
tt stop --session a1b2          # stop a specific session by id
tt today                        # print today's log lines + total time today (alias: t, tail)
tt log --length 20              # print the last N raw log lines (default 20)
tt report 2026-05-01 2026-05-31 # detailed report for a date range
```

- `-p/--project NAME` on any command selects the project (default: `config.default_project`, else `default`).
- Command prefixes: `s` = start, `c` = continue, `r` = resume, `t`/`tail` = today, `rep` = report.
- `--at TIME` (on `start` and `stop`) sets the timestamp instead of *now*. Accepted forms:
  - `-1` / `-1:30` → now minus 1h / 1h30m (`+` for the future)
  - `20:00` / `7` → today at that clock time
  - a full ISO timestamp, e.g. `2026-05-01T09:00:00`

  `start --at` still shows the live timer (counting from the backdated start); use `--no-timer`
  or a non-TTY to record and exit immediately.

### Interactive vs non-interactive

`start`/`continue` show a live timer when stdout is a TTY (Ctrl+C writes the `STOP`). When piped or
run with `--no-timer`, they print the session id and exit immediately — so an AI harness can do:

```sh
id=$(tt -p acme start "build feature" --no-timer)
# ...work...
tt -p acme stop --session "$id"
```

Non-interactive sessions are independent and can overlap: several harnesses can track in parallel,
and `stop` always closes a session *by id*, so they never steal each other's clock.

The **interactive timer is single-instance**: starting one takes a lock at `~/.tt/timer.lock`, so a
second `tt start` in a TTY refuses with the running task and how to clear a stale lock:

```
tt: a timer is already running (pid 1234 — build feature).
    If that's wrong (a crashed timer), remove the lock:  rm ~/.tt/timer.lock
```

The lock is released on `Ctrl+C`. A hard-killed timer leaves it behind — remove it with `rm` as
shown. `--no-timer`/harness sessions never take the lock.

## Reports

Detailed report — one row per session, grouped by start date. Formats:

```sh
tt report 2026-05-01 2026-05-31            # plain-text table (default)
tt report 2026-05-01 2026-05-31 --csv      # CSV
tt report 2026-05-01 2026-05-31 --json     # JSON
tt report 2026-05-01 2026-05-31 --html > may.html   # printable HTML → open, Cmd-P, Save as PDF
```

`end_date` defaults to today; the range is inclusive on both ends.

A session that was never stopped (crash) is counted up to *now* in a live report (`end_date >=`
today), but in a report over a **past** period it's flagged `OPEN`, excluded from totals, and a
warning is printed — fix it by editing the log or `tt stop --session ID --at <timestamp>`.

## Config

`~/.tt/config.toml` (optional):

```toml
default_project = "acme"

[user]
name = "Jane Doe"      # optional; shown as the report subtitle

[project.acme]
name = "Acme Inc."     # optional display name shown in the report header
rate.amount = 120
rate.currency = "USD"

[cmux]
tab_status = true      # optional; show the running task + time in the cmux sidebar
```

`report` multiplies hours by `rate.amount` for the amount column and total. No rate → hours only.
The report header shows the project `name` if set (else the project id) with `[user].name` as subtitle.

With `[cmux].tab_status = true`, an interactive `tt start`/`continue` running inside
[cmux](https://cmux.io) shows a sidebar status line on its workspace — `H:MM <task>` with a clock
icon, refreshed each minute — and clears it when the timer stops. It's a no-op outside cmux or
with `--no-timer`.

If a stale pill lingers (e.g. the timer was hard-killed), clear it manually with `cmux
clear-status tt` (tt uses the status key `tt`). If it persists even after `cmux list-status` shows
it gone, that's a stale client-side render — restart cmux.

## Storage

Append-only plain text under `~/.tt/<project>/logs/YYYY.log`, one file per year:

```
2026-05-31T21:30:00+03:00 START a1b2 revert deployment
2026-06-01T00:05:00+03:00 STOP a1b2
```

Timestamps carry the UTC offset. `STOP` is written into its `START`'s file, so a session crossing
midnight or year-end stays whole. The log is the single source of truth — fix any mistake by
editing it in a text editor.

## Tests

```sh
python3 test_tt.py
```
