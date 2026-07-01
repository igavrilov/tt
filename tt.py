#!/usr/bin/env python3
"""tt - personal time tracking. See PRD.md."""
import argparse
import csv
import html
import json
import secrets
import sys
import time
import tomllib
from datetime import date, datetime
from pathlib import Path

TT_HOME = Path.home() / ".tt"


# ---------- config / paths ----------

def load_config():
    p = TT_HOME / "config.toml"
    return tomllib.loads(p.read_text()) if p.exists() else {}


def resolve_project(cfg, arg):
    return arg or cfg.get("default_project") or "default"


def project_conf(cfg, project):
    return cfg.get("project", {}).get(project, {})


def get_rate(cfg, project):
    r = project_conf(cfg, project).get("rate")
    if r and "amount" in r:
        return {"amount": r["amount"], "currency": r.get("currency", "")}
    return None


def year_file(project, year):
    return TT_HOME / project / "logs" / f"{year}.log"


def append_line(path, line):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:  # append mode => O_APPEND => atomic per-line writes
        f.write(line + "\n")


def now_local():
    return datetime.now().astimezone()


# ---------- log parsing (pure, testable) ----------

def parse_line(line):
    """-> (dt, verb, sid, task) or None. task is '' for STOP / nameless START."""
    parts = line.strip().split(maxsplit=3)
    if len(parts) < 3 or parts[1] not in ("START", "STOP"):
        return None
    try:
        dt = datetime.fromisoformat(parts[0])
    except ValueError:
        return None
    return (dt, parts[1], parts[2], parts[3] if len(parts) > 3 else "")


def read_events(project, y0, y1):
    events = []
    for year in range(y0, y1 + 1):
        f = year_file(project, year)
        if f.exists():
            events += filter(None, (parse_line(l) for l in f.read_text().splitlines()))
    return events


def pair_sessions(events):
    """Pair START/STOP by id, chronologically. Unmatched STARTs stay open."""
    open_by = {}
    done = []
    for dt, verb, sid, task in sorted(events, key=lambda e: e[0]):
        if verb == "START":
            open_by[sid] = {"sid": sid, "task": task, "start": dt, "stop": None}
        elif sid in open_by:
            s = open_by.pop(sid)
            s["stop"] = dt
            done.append(s)
    return done + list(open_by.values())


def open_sessions(project):
    """Currently-open sessions -> {sid: {start, task, file}}. Scans this + last year."""
    cur = now_local().year
    open_by = {}
    for year in (cur - 1, cur):  # chronological so cross-year opens carry forward
        f = year_file(project, year)
        if not f.exists():
            continue
        for ev in filter(None, (parse_line(l) for l in f.read_text().splitlines())):
            dt, verb, sid, task = ev
            if verb == "START":
                open_by[sid] = {"start": dt, "task": task, "file": f}
            else:
                open_by.pop(sid, None)
    return open_by


def last_task(project):
    cur = now_local().year
    for year in (cur, cur - 1):
        f = year_file(project, year)
        if not f.exists():
            continue
        task = None
        for ev in filter(None, (parse_line(l) for l in f.read_text().splitlines())):
            if ev[1] == "START":
                task = ev[3]
        if task is not None:
            return task
    return None


# ---------- report building (pure, testable) ----------

def fmt_hms(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_report(sessions, start_date, end_date, rate, now, today):
    """-> (rows, {total_secs, total_amount}, warnings). Groups by start date, range-filtered."""
    live = end_date >= today
    rows, warnings = [], []
    total_secs, total_amount = 0.0, 0.0
    for s in sorted(sessions, key=lambda s: s["start"]):
        d = s["start"].date()
        if not (start_date <= d <= end_date):
            continue
        is_open = s["stop"] is None
        excluded = is_open and not live
        if is_open and live:
            stop, secs, end_str = now, max(0.0, (now - s["start"]).total_seconds()), now.strftime("%H:%M")
        elif is_open:  # historical => can't fabricate a duration
            secs, end_str = 0.0, "OPEN"
            warnings.append(
                f"session {s['sid']} \"{s['task']}\" started "
                f"{s['start'].isoformat(timespec='seconds')} was never stopped; excluded from totals")
        else:
            secs = max(0.0, (s["stop"] - s["start"]).total_seconds())
            end_str = s["stop"].strftime("%H:%M")
        amount = round(secs / 3600 * rate["amount"], 2) if rate and not excluded else None
        rows.append({
            "date": s["start"].strftime("%d/%m/%Y"), "task": s["task"],
            "start": s["start"].strftime("%H:%M"), "end": end_str,
            "duration": "—" if excluded else fmt_hms(secs), "seconds": secs,
            "amount": amount, "open": is_open, "excluded": excluded,
        })
        if not excluded:
            total_secs += secs
            if rate:
                total_amount += amount
    totals = {"secs": total_secs, "amount": round(total_amount, 2) if rate else None}
    return rows, totals, warnings


# ---------- output formats ----------

def _amount_cell(a, currency):
    return "" if a is None else f"{a:.2f} {currency}".strip()


def render_text(project, user, start_date, end_date, rows, totals, currency):
    out = [f"Time report — {project}"]
    if user:
        out.append(user)
    out.append(f"{start_date} – {end_date}")
    total = f"Total: {fmt_hms(totals['secs'])}"
    if totals["amount"] is not None:
        total += f"   Amount: {totals['amount']:.2f} {currency}"
    out += [total, ""]
    headers = ["Date", "Task", "Start", "End", "Duration", "Amount"]
    table = [headers] + [[r["date"], r["task"], r["start"], r["end"], r["duration"],
                          _amount_cell(r["amount"], currency)] for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
    for row in table:
        out.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(out) + "\n"


def render_csv(rows, currency):
    w = csv.writer(sys.stdout)
    w.writerow(["date", "task", "start", "end", "duration", "amount"])
    for r in rows:
        w.writerow([r["date"], r["task"], r["start"], r["end"], r["duration"], _amount_cell(r["amount"], currency)])
    return ""


def render_json(project, user, start_date, end_date, rows, totals, currency):
    return json.dumps({
        "project": project, "user": user, "start_date": str(start_date), "end_date": str(end_date),
        "currency": currency, "total_duration": fmt_hms(totals["secs"]),
        "total_seconds": int(totals["secs"]), "total_amount": totals["amount"],
        "sessions": [{k: r[k] for k in ("date", "task", "start", "end", "duration", "amount", "open")} for r in rows],
    }, indent=2) + "\n"


def render_html(project, user, start_date, end_date, rows, totals, currency):
    e = html.escape
    total = f"{fmt_hms(totals['secs'])}"
    amount = f"{totals['amount']:.2f} {e(currency)}" if totals["amount"] is not None else ""
    trs = "\n".join(
        "<tr{cls}><td>{date}</td><td>{task}</td><td>{start}</td><td>{end}</td>"
        "<td class='num'>{dur}</td><td class='num'>{amt}</td></tr>".format(
            cls=" class='open'" if r["open"] else "", date=e(r["date"]), task=e(r["task"]),
            start=e(r["start"]), end=e(r["end"]), dur=e(r["duration"]),
            amt=e(_amount_cell(r["amount"], currency)))
        for r in rows)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Time report — {e(project)}</title>
<style>
  @page {{ margin: 2cm; }}
  body {{ font: 13px/1.5 -apple-system, Arial, sans-serif; color: #222; max-width: 800px; margin: 2rem auto; }}
  header {{ border-bottom: 2px solid #222; padding-bottom: .75rem; margin-bottom: 1.25rem; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .25rem; }}
  .subtitle {{ font-size: 1.1rem; color: #444; margin-bottom: .15rem; }}
  .range {{ color: #666; }}
  .totals {{ margin-top: .6rem; font-size: 1.05rem; }}
  .totals b {{ font-size: 1.25rem; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; padding: .45rem .5rem; border-bottom: 1px solid #ddd; }}
  th {{ color: #666; font-weight: 600; border-bottom: 2px solid #ccc; }}
  .num {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
  tr.open td {{ color: #999; font-style: italic; }}
</style></head><body>
<header>
  <h1>Time report — {e(project)}</h1>
  {f'<div class="subtitle">{e(user)}</div>' if user else ''}
  <div class="range">{start_date} – {end_date}</div>
  <div class="totals">Total: <b>{total}</b>{f" &nbsp; Amount: <b>{amount}</b>" if amount else ""}</div>
</header>
<table>
<thead><tr><th>Date</th><th>Task</th><th>Start</th><th>End</th>
<th class="num">Duration</th><th class="num">Amount</th></tr></thead>
<tbody>
{trs}
</tbody></table>
</body></html>
"""


# ---------- commands ----------

def run_timer(task, sid, start_file):
    start = time.monotonic()
    try:
        while True:
            print(f"\r  {task}  {fmt_hms(time.monotonic() - start)}", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    append_line(start_file, f"{now_local().isoformat(timespec='seconds')} STOP {sid}")
    print(f"\n  stopped {sid}")


def cmd_start(project, task, no_timer):
    now = now_local()
    sid = secrets.token_hex(2)
    f = year_file(project, now.year)
    append_line(f, f"{now.isoformat(timespec='seconds')} START {sid} {task}")
    print(sid)
    if sys.stdout.isatty() and not no_timer:
        run_timer(task, sid, f)  # STOP lands in the START's file, even across midnight/year


def cmd_continue(project, no_timer):
    task = last_task(project)
    if task is None:
        sys.exit(f"tt: no previous task in project '{project}'")
    cmd_start(project, task, no_timer)


def cmd_stop(project, sid, at):
    opens = open_sessions(project)
    if not opens:
        sys.exit(f"tt: no running session in project '{project}'")
    if sid is None:
        if len(opens) == 1:
            sid = next(iter(opens))
        else:
            sys.exit("tt: several sessions open, use --session ID:\n  " +
                     "\n  ".join(f"{s} {v['task']}" for s, v in opens.items()))
    if sid not in opens:
        sys.exit(f"tt: session {sid} is not running")
    ts = now_local()
    if at:
        ts = datetime.fromisoformat(at)
        if ts.tzinfo is None:
            ts = ts.astimezone()
    append_line(opens[sid]["file"], f"{ts.isoformat(timespec='seconds')} STOP {sid}")
    print(f"stopped {sid}")


def cmd_report(cfg, project, start_s, end_s, fmt):
    start_date = date.fromisoformat(start_s)
    end_date = date.fromisoformat(end_s) if end_s else date.today()
    now = now_local()
    rate = get_rate(cfg, project)
    currency = rate["currency"] if rate else ""
    label = project_conf(cfg, project).get("name", project)  # display name for the report
    user = cfg.get("user", {}).get("name", "")               # report subtitle
    sessions = pair_sessions(read_events(project, start_date.year, end_date.year))
    rows, totals, warnings = build_report(sessions, start_date, end_date, rate, now, now.date())
    for w in warnings:
        print("tt: " + w, file=sys.stderr)
    if fmt == "csv":
        render_csv(rows, currency)
    elif fmt == "json":
        sys.stdout.write(render_json(label, user, start_date, end_date, rows, totals, currency))
    elif fmt == "html":
        sys.stdout.write(render_html(label, user, start_date, end_date, rows, totals, currency))
    else:
        sys.stdout.write(render_text(label, user, start_date, end_date, rows, totals, currency))


# ---------- cli ----------

def main(argv=None):
    cfg = load_config()
    ap = argparse.ArgumentParser(prog="tt", description="personal time tracking")
    ap.add_argument("-p", "--project", help="project (default: config.default_project or 'default')")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start", aliases=["s"])
    p.add_argument("task", nargs="*")
    p.add_argument("--no-timer", action="store_true")

    for name, alias in (("continue", "c"), ("resume", "r")):
        p = sub.add_parser(name, aliases=[alias])
        p.add_argument("--no-timer", action="store_true")

    p = sub.add_parser("stop")
    p.add_argument("--session")
    p.add_argument("--at", help="ISO timestamp to backfill the STOP")

    p = sub.add_parser("report", aliases=["rep"])
    p.add_argument("start_date")
    p.add_argument("end_date", nargs="?")
    g = p.add_mutually_exclusive_group()
    for f in ("csv", "json", "html"):
        g.add_argument(f"--{f}", dest="fmt", action="store_const", const=f)

    args = ap.parse_args(argv)
    project = resolve_project(cfg, args.project)
    cmd = args.cmd

    if cmd in ("start", "s"):
        cmd_start(project, " ".join(args.task).strip() or "(untitled)", args.no_timer)
    elif cmd in ("continue", "c", "resume", "r"):
        cmd_continue(project, args.no_timer)
    elif cmd == "stop":
        cmd_stop(project, args.session, args.at)
    elif cmd in ("report", "rep"):
        cmd_report(cfg, project, args.start_date, args.end_date, args.fmt)


if __name__ == "__main__":
    main()
