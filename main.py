import argparse
import json
from config import OURA_TOKEN, ICAL_OUTPUT_PATH, DAYS_BACK
try:
    from config import MIN_DURATION_MINUTES
except ImportError:
    MIN_DURATION_MINUTES = 0
try:
    from config import INCLUDE_SESSIONS
except ImportError:
    INCLUDE_SESSIONS = False
try:
    from config import INCLUDE_DAILY_ACTIVITY
except ImportError:
    INCLUDE_DAILY_ACTIVITY = True
try:
    from config import MONTHLY_SUMMARY
except ImportError:
    MONTHLY_SUMMARY = True
try:
    from config import CUSTOM_ACTIVITY_NAMES
except ImportError:
    CUSTOM_ACTIVITY_NAMES = {}
from oura_api.client import fetch_window, fetch_workouts, fetch_sessions, fetch_daily_activity
from ical.generator import (
    KIND_WORKOUT,
    KIND_SESSION,
    KIND_DAILY_ACTIVITY,
    generate_activity_calendar,
    save_calendar,
    load_existing_calendar,
    add_monthly_summaries,
    prune_deleted_events,
    describe_events,
    format_activity_label,
    format_session_label,
    normalize_activity,
)

def discover_activity_types(workouts: list, sessions: list):
    """Print a ready-to-paste CUSTOM_ACTIVITY_NAMES dict for all activity types found."""
    found = {}  # raw activity type -> {"kind", "count", "last"}
    for kind, objects, field in (("workout", workouts, "activity"), ("session", sessions, "type")):
        for obj in objects:
            code = obj.get(field)
            if not code:
                continue
            entry = found.setdefault(code, {"kind": kind, "count": 0, "last": ""})
            entry["count"] += 1
            ts = obj.get("start_datetime") or obj.get("day") or ""
            if ts > entry["last"]:
                entry["last"] = ts

    if not found:
        print("No activity types found in the fetched data.")
        print("Tip: try increasing DAYS_BACK in config.py to search further back.")
        return

    print(f"\nFound {len(found)} activity type(s) in the last {DAYS_BACK} days. "
          "Add this to your config.py and adjust names/icons as you like:\n")
    print("CUSTOM_ACTIVITY_NAMES = {")
    # Most frequent first; ties broken alphabetically for stable output.
    for code, entry in sorted(found.items(), key=lambda kv: (-kv[1]["count"], kv[0])):
        configured = next(
            (CUSTOM_ACTIVITY_NAMES[k] for k in (code, normalize_activity(code)) if k in CUSTOM_ACTIVITY_NAMES),
            None,
        )
        if configured is not None:
            label = configured
            comment = "  # already in config"
        else:
            if entry["kind"] == "workout":
                label = format_activity_label(code)
            else:
                label = format_session_label(code)
            count = entry["count"]
            noun = f"{entry['kind']}{'s' if count != 1 else ''}"
            comment = f"  # {count} {noun}, last seen: {entry['last']}"
        print(f"    {json.dumps(code)}: {json.dumps(label, ensure_ascii=False)},{comment}")
    print("}")

def main():
    parser = argparse.ArgumentParser(description="Sync Oura activity to iCalendar")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="List all activity types found and print a ready-to-paste CUSTOM_ACTIVITY_NAMES dict"
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Keep calendar events whose data was deleted in the Oura app (default: remove them)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and process data, print the resulting events, but do not write the calendar file"
    )
    args = parser.parse_args()

    window_start, window_end = fetch_window(DAYS_BACK)

    # A failed fetch returns None and aborts the run: continuing would treat
    # the missing data as deleted and prune the corresponding events.
    print(f"Fetching workouts for the past {DAYS_BACK} days...")
    workouts = fetch_workouts(OURA_TOKEN, window_start, window_end)
    if workouts is None:
        raise SystemExit(1)

    sessions = None
    if INCLUDE_SESSIONS:
        print(f"Fetching sessions for the past {DAYS_BACK} days...")
        sessions = fetch_sessions(OURA_TOKEN, window_start, window_end)
        if sessions is None:
            raise SystemExit(1)

    if args.discover:
        discover_activity_types(workouts, sessions or [])
        return

    daily_activity = None
    if INCLUDE_DAILY_ACTIVITY:
        print(f"Fetching daily activity for the past {DAYS_BACK} days...")
        daily_activity = fetch_daily_activity(OURA_TOKEN, window_start, window_end)
        if daily_activity is None:
            raise SystemExit(1)

    # An empty fetch still proceeds: it means every workout in the window was
    # deleted, so their events must be pruned and the summaries refreshed.
    if not workouts:
        print("No workouts found in the fetched window.")

    print("Loading existing calendar...")
    existing_calendar = load_existing_calendar(ICAL_OUTPUT_PATH)

    print(f"Generating calendar with {len(workouts)} new workout entries...")
    calendar, live_uids = generate_activity_calendar(
        workouts,
        existing_calendar,
        min_duration_minutes=MIN_DURATION_MINUTES,
        custom_activity_names=CUSTOM_ACTIVITY_NAMES,
        sessions=sessions,
        daily_activity=daily_activity,
    )

    if args.no_prune:
        print("Skipping prune of deleted events (--no-prune).")
    else:
        print("Pruning events deleted in the app...")
        kinds = {KIND_WORKOUT}
        if sessions is not None:
            kinds.add(KIND_SESSION)
        if daily_activity is not None:
            kinds.add(KIND_DAILY_ACTIVITY)
        calendar = prune_deleted_events(calendar, live_uids, window_start, window_end, kinds)

    print("Refreshing monthly activity summaries...")
    calendar = add_monthly_summaries(calendar, CUSTOM_ACTIVITY_NAMES, enabled=MONTHLY_SUMMARY)

    if args.dry_run:
        print(f"\nDry run: not writing {ICAL_OUTPUT_PATH}. Events from {window_start} to {window_end}:\n")
        for line in describe_events(calendar, window_start, window_end):
            print(f"  {line}")
        return

    print(f"Saving calendar to {ICAL_OUTPUT_PATH}...")
    if not save_calendar(calendar, ICAL_OUTPUT_PATH):
        raise SystemExit(1)

    print("Done.")

if __name__ == "__main__":
    main()
