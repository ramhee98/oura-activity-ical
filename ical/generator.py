from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
from collections import Counter
from calendar import monthrange
from icalendar import Calendar, Event
import os
import re

# UID prefix of the auto-generated monthly summary events. These are derived
# from the real activity events, so they are excluded from the per-month
# totals and recomputed on every run.
MONTHLY_SUMMARY_UID_PREFIX = "oura-activity-summary-"

# Kinds of Oura objects turned into events, stored in X-OURA-KIND so later runs
# can recognise (and summarise or prune) their own events straight from the
# calendar file, which is the only persistence layer.
KIND_WORKOUT = "workout"
KIND_SESSION = "session"
KIND_DAILY_ACTIVITY = "daily_activity"

# Fallback icon for workout activity types without a known mapping
FALLBACK_ACTIVITY_ICON = "🏅"

# Map known workout activity types (normalised to snake_case) to icon and name
ACTIVITY_LABELS = {
    "running": ("🏃", "Running"),
    "treadmill_running": ("🏃", "Treadmill Running"),
    "trail_running": ("🏃", "Trail Running"),
    "walking": ("🚶", "Walking"),
    "nordic_walking": ("🚶", "Nordic Walking"),
    "hiking": ("🥾", "Hiking"),
    "cycling": ("🚴", "Cycling"),
    "indoor_cycling": ("🚴", "Indoor Cycling"),
    "mountain_biking": ("🚵", "Mountain Biking"),
    "strength_training": ("🏋️", "Strength Training"),
    "weightlifting": ("🏋️", "Weightlifting"),
    "functional_training": ("🏋️", "Functional Training"),
    "crossfit": ("🏋️", "CrossFit"),
    "hiit": ("🔥", "HIIT"),
    "circuit_training": ("🔥", "Circuit Training"),
    "cardio": ("❤️", "Cardio"),
    "elliptical": ("🏃", "Elliptical"),
    "stair_exercise": ("🪜", "Stair Exercise"),
    "swimming": ("🏊", "Swimming"),
    "open_water_swimming": ("🏊", "Open Water Swimming"),
    "yoga": ("🧘", "Yoga"),
    "pilates": ("🤸", "Pilates"),
    "stretching": ("🤸", "Stretching"),
    "dancing": ("💃", "Dancing"),
    "rowing": ("🚣", "Rowing"),
    "kayaking": ("🛶", "Kayaking"),
    "canoeing": ("🛶", "Canoeing"),
    "paddling": ("🛶", "Paddling"),
    "stand_up_paddling": ("🏄", "Stand Up Paddling"),
    "surfing": ("🏄", "Surfing"),
    "skiing": ("⛷️", "Skiing"),
    "downhill_skiing": ("⛷️", "Downhill Skiing"),
    "cross_country_skiing": ("⛷️", "Cross-Country Skiing"),
    "snowboarding": ("🏂", "Snowboarding"),
    "snowshoeing": ("🥾", "Snowshoeing"),
    "ice_skating": ("⛸️", "Ice Skating"),
    "skating": ("⛸️", "Skating"),
    "inline_skating": ("🛼", "Inline Skating"),
    "climbing": ("🧗", "Climbing"),
    "bouldering": ("🧗", "Bouldering"),
    "tennis": ("🎾", "Tennis"),
    "padel": ("🎾", "Padel"),
    "squash": ("🎾", "Squash"),
    "badminton": ("🏸", "Badminton"),
    "table_tennis": ("🏓", "Table Tennis"),
    "golf": ("⛳", "Golf"),
    "soccer": ("⚽", "Soccer"),
    "football": ("⚽", "Football"),
    "american_football": ("🏈", "American Football"),
    "basketball": ("🏀", "Basketball"),
    "volleyball": ("🏐", "Volleyball"),
    "handball": ("🤾", "Handball"),
    "hockey": ("🏒", "Hockey"),
    "ice_hockey": ("🏒", "Ice Hockey"),
    "floorball": ("🏑", "Floorball"),
    "boxing": ("🥊", "Boxing"),
    "martial_arts": ("🥋", "Martial Arts"),
    "horseback_riding": ("🏇", "Horseback Riding"),
    "gardening": ("🌱", "Gardening"),
    "housework": ("🧹", "Housework"),
    "other": (FALLBACK_ACTIVITY_ICON, "Other"),
}

# Map Oura session ("Moment") types to icon and name
SESSION_LABELS = {
    "breathing": ("🌬️", "Breathing"),
    "meditation": ("🧘", "Meditation"),
    "nap": ("😴", "Nap"),
    "relaxation": ("🛀", "Relaxation"),
    "rest": ("🛋️", "Rest"),
    "body_status": ("🩺", "Body Status"),
}

# Fallback icon for session types without a known mapping
FALLBACK_SESSION_ICON = "🧘"

# Icon of the all-day daily activity events
DAILY_ACTIVITY_ICON = "👟"

# Human-readable workout sources
SOURCE_LABELS = {
    "manual": "Manual",
    "autodetected": "Autodetected",
    "confirmed": "Confirmed",
    "workout_heart_rate": "Workout Heart Rate",
    "live_third_party_heart_rate": "Live Third-Party Heart Rate",
    "live_oura_heart_rate": "Live Oura Heart Rate",
}

def convert_to_hh_mm(seconds) -> str:
    """Format a duration in seconds as H:MM."""
    minutes, _ = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return '%d:%02d' % (hours, minutes)

def normalize_activity(activity) -> str:
    """
    Normalise an Oura activity type to snake_case ("strengthTraining",
    "Strength Training" and "strength-training" all become
    "strength_training") so lookups work whatever spelling the API uses.
    """
    text = str(activity or "").strip()
    text = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', text)
    text = re.sub(r'[\s\-]+', '_', text)
    return text.lower()

def _humanize(code: str) -> str:
    return code.replace("_", " ").strip().title()

def format_activity_label(activity, custom_activity_names: dict = None) -> str:
    """
    Convert a workout activity type to an icon + name label. A user-configured
    CUSTOM_ACTIVITY_NAMES entry (matched on the raw or normalised type) wins
    and is used as-is, then the built-in mapping, then a generic fallback.
    """
    raw = str(activity or "")
    key = normalize_activity(raw)
    if custom_activity_names:
        for candidate in (raw, key):
            if candidate in custom_activity_names:
                return custom_activity_names[candidate]
    if key in ACTIVITY_LABELS:
        icon, name = ACTIVITY_LABELS[key]
        return f"{icon} {name}"
    return f"{FALLBACK_ACTIVITY_ICON} {_humanize(key) or 'Workout'}"

def format_session_label(session_type, custom_activity_names: dict = None) -> str:
    """Convert a session type to an icon + name label (custom names win)."""
    raw = str(session_type or "")
    key = normalize_activity(raw)
    if custom_activity_names:
        for candidate in (raw, key):
            if candidate in custom_activity_names:
                return custom_activity_names[candidate]
    if key in SESSION_LABELS:
        icon, name = SESSION_LABELS[key]
        return f"{icon} {name}"
    return f"{FALLBACK_SESSION_ICON} {_humanize(key) or 'Session'}"

def _empty_calendar() -> Calendar:
    cal = Calendar()
    cal.add('prodid', '-//ramhee98//oura-activity-ical//EN')
    cal.add('version', '2.0')
    cal.add('x-wr-calname', 'Oura Activity')
    return cal

def load_existing_calendar(path: str) -> Calendar:
    """
    Load an existing calendar file and return the calendar object.
    Returns a new empty calendar if the file doesn't exist or can't be parsed.
    """
    if not os.path.exists(path):
        print(f"No existing calendar found at {path}. Starting fresh.")
        return _empty_calendar()

    try:
        with open(path, 'rb') as f:
            existing_cal = Calendar.from_ical(f.read())

        event_count = sum(1 for c in existing_cal.walk('VEVENT'))
        print(f"Loaded existing calendar with {event_count} events.")
        return existing_cal

    except Exception as e:
        print(f"Error loading existing calendar: {e}. Starting fresh.")
        return _empty_calendar()

def _parse_datetime(value) -> datetime:
    """
    Parse an Oura timestamp into an aware UTC datetime. Events are stored in
    UTC so every calendar client renders them in its own local time and the
    value round-trips through the .ics file unchanged.
    """
    if not value:
        raise ValueError("missing timestamp")
    text = str(value)
    # datetime.fromisoformat() only accepts a trailing "Z" from Python 3.11.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _number(value) -> Optional[float]:
    """Return value as a float if it is a real number, otherwise None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)

def _format_int(value) -> str:
    """Format a number with thousands separators, e.g. 12345 -> 12,345."""
    return f"{int(round(value)):,}"

def _new_event(uid: str, kind: str, day: str) -> Event:
    event = Event()
    event.add('uid', uid)
    now_utc = datetime.now(timezone.utc)
    event.add('dtstamp', now_utc)
    event.add('created', now_utc)
    event.add('last-modified', now_utc)
    event.add('x-oura-kind', kind)
    if day:
        event.add('x-oura-day', str(day))
    return event

def workout_uid(workout: Dict) -> str:
    """Stable UID of a workout event, derived from the Oura object id."""
    return f"oura-workout-{workout.get('id')}"

def _build_workout_event(workout: Dict, custom_activity_names: dict = None) -> Event:
    """Build a timed event for a workout. Raises ValueError on unusable data."""
    if not workout.get("id"):
        raise ValueError("workout without id")
    start = _parse_datetime(workout.get("start_datetime"))
    end = _parse_datetime(workout.get("end_datetime"))
    if end < start:
        raise ValueError("workout ends before it starts")

    duration_seconds = (end - start).total_seconds()
    duration = convert_to_hh_mm(duration_seconds)
    activity = workout.get("activity") or "other"
    label = format_activity_label(activity, custom_activity_names)
    distance = _number(workout.get("distance"))
    calories = _number(workout.get("calories"))
    intensity = workout.get("intensity")
    source = workout.get("source")
    user_label = (workout.get("label") or "").strip()

    lines = [
        f"Activity: {label}",
        f"Duration: {duration}",
    ]
    if distance:
        lines.append(f"Distance: {distance / 1000:.2f} km")
    if calories is not None:
        lines.append(f"Calories: {_format_int(calories)} kcal")
    if intensity:
        lines.append(f"Intensity: {_humanize(str(intensity))}")
    if source:
        lines.append(f"Source: {SOURCE_LABELS.get(source, _humanize(str(source)))}")
    if user_label:
        lines.append(f"Label: {user_label}")

    event = _new_event(workout_uid(workout), KIND_WORKOUT, workout.get("day"))
    event.add('dtstart', start)
    event.add('dtend', end)
    event.add('summary', f"{label} {duration}")
    event.add('description', "\n".join(lines))

    # Machine-readable metrics so monthly summaries can be recomputed from the
    # calendar file on later runs, even for workouts outside the fetch window.
    event.add('x-oura-activity', str(activity))
    event.add('x-oura-duration', str(int(round(duration_seconds))))
    if distance is not None:
        event.add('x-oura-distance', str(int(round(distance))))
    if calories is not None:
        event.add('x-oura-calories', str(int(round(calories))))
    if intensity:
        event.add('x-oura-intensity', str(intensity))
    if source:
        event.add('x-oura-source', str(source))
    return event

def session_uid(session: Dict) -> str:
    """Stable UID of a session event, derived from the Oura object id."""
    return f"oura-session-{session.get('id')}"

def _sample_average(sample) -> Optional[float]:
    """Average of the non-null items of an Oura sample object, or None."""
    if not isinstance(sample, dict):
        return None
    values = [v for v in (_number(i) for i in sample.get("items") or []) if v is not None]
    return sum(values) / len(values) if values else None

def _build_session_event(session: Dict, custom_activity_names: dict = None) -> Event:
    """Build a timed event for a session. Raises ValueError on unusable data."""
    if not session.get("id"):
        raise ValueError("session without id")
    start = _parse_datetime(session.get("start_datetime"))
    end = _parse_datetime(session.get("end_datetime"))
    if end < start:
        raise ValueError("session ends before it starts")

    duration_seconds = (end - start).total_seconds()
    duration = convert_to_hh_mm(duration_seconds)
    session_type = session.get("type") or "session"
    label = format_session_label(session_type, custom_activity_names)
    mood = session.get("mood")
    avg_hr = _sample_average(session.get("heart_rate"))
    avg_hrv = _sample_average(session.get("heart_rate_variability"))

    lines = [
        f"Type: {label}",
        f"Duration: {duration}",
    ]
    if mood:
        lines.append(f"Mood: {_humanize(str(mood))}")
    if avg_hr is not None:
        lines.append(f"Avg Heart Rate: {round(avg_hr)} bpm")
    if avg_hrv is not None:
        lines.append(f"Avg HRV: {round(avg_hrv)} ms")

    event = _new_event(session_uid(session), KIND_SESSION, session.get("day"))
    event.add('dtstart', start)
    event.add('dtend', end)
    event.add('summary', f"{label} {duration}")
    event.add('description', "\n".join(lines))
    event.add('x-oura-type', str(session_type))
    event.add('x-oura-duration', str(int(round(duration_seconds))))
    return event

def daily_activity_uid(daily: Dict) -> str:
    """Stable UID of a daily activity event, derived from the Oura object id."""
    return f"oura-daily-activity-{daily.get('id')}"

def _build_daily_activity_event(daily: Dict) -> Event:
    """Build an all-day event for a day's activity. Raises ValueError on unusable data."""
    if not daily.get("id"):
        raise ValueError("daily activity without id")
    day = date.fromisoformat(str(daily.get("day")))

    score = _number(daily.get("score"))
    steps = _number(daily.get("steps"))
    active_calories = _number(daily.get("active_calories"))
    total_calories = _number(daily.get("total_calories"))
    walking_distance = _number(daily.get("equivalent_walking_distance"))

    title_parts = []
    if score is not None:
        title_parts.append(f"Activity {int(score)}")
    if steps is not None:
        title_parts.append(f"{_format_int(steps)} steps")
    title = f"{DAILY_ACTIVITY_ICON} {', '.join(title_parts) or 'Activity'}"

    lines = []
    if score is not None:
        lines.append(f"Activity Score: {int(score)}")
    if steps is not None:
        lines.append(f"Steps: {_format_int(steps)}")
    if active_calories is not None:
        lines.append(f"Active Calories: {_format_int(active_calories)} kcal")
    if total_calories is not None:
        lines.append(f"Total Calories: {_format_int(total_calories)} kcal")
    if walking_distance is not None:
        lines.append(f"Walking Equivalent: {walking_distance / 1000:.1f} km")

    event = _new_event(daily_activity_uid(daily), KIND_DAILY_ACTIVITY, day.isoformat())
    event.add('dtstart', day)  # date value -> all-day event
    event.add('dtend', day + timedelta(days=1))
    event.add('summary', title)
    if lines:
        event.add('description', "\n".join(lines))
    event.add('transp', 'TRANSPARENT')  # informational; don't mark as busy
    if score is not None:
        event.add('x-oura-score', str(int(score)))
    if steps is not None:
        event.add('x-oura-steps', str(int(steps)))
    if active_calories is not None:
        event.add('x-oura-active-calories', str(int(active_calories)))
    if total_calories is not None:
        event.add('x-oura-total-calories', str(int(total_calories)))
    if walking_distance is not None:
        event.add('x-oura-walking-distance', str(int(walking_distance)))
    return event

def _same_content(existing: Event, fresh: Event) -> bool:
    """True if two events have the same content (so an existing event need not
    be rewritten). Compares summary, description, the start/end values and the
    machine-readable X-OURA-* metrics, so a change to a hidden metric still
    refreshes the event."""
    def text(event, key):
        value = event.get(key)
        return None if value is None else str(value)

    keys = {'summary', 'description', 'transp'}
    keys.update(k.lower() for k in list(existing.keys()) + list(fresh.keys())
                if k.lower().startswith('x-oura-'))
    for key in keys:
        if text(existing, key) != text(fresh, key):
            return False
    for key in ('dtstart', 'dtend'):
        a, b = existing.get(key), fresh.get(key)
        if (a is None) != (b is None):
            return False
        if a is not None and a.to_ical() != b.to_ical():
            return False
    return True

def _upsert_event(cal: Calendar, existing_by_uid: Dict[str, Event], event: Event) -> str:
    """
    Add an event, or refresh the existing event with the same UID in place.
    Returns "added", "updated" or "unchanged".
    """
    uid = str(event.get('uid'))
    existing = existing_by_uid.get(uid)
    if existing is not None:
        # Unchanged: leave the original event (and its timestamps) untouched
        # so calendar clients aren't churned on every run.
        if _same_content(existing, event):
            return "unchanged"
        # Changed: refresh in place, preserving the original creation time.
        old_created = existing.get('created')
        if old_created is not None:
            event.pop('created', None)
            event.add('created', old_created.dt)
        cal.subcomponents.remove(existing)
        cal.add_component(event)
        existing_by_uid[uid] = event
        return "updated"

    cal.add_component(event)
    # Track the new event so a duplicate within the same fetch refreshes it
    # instead of producing a second event with the same UID.
    existing_by_uid[uid] = event
    return "added"

def _index_events(cal: Calendar) -> Dict[str, Event]:
    return {
        str(c.get('uid')): c
        for c in cal.walk('VEVENT')
        if c.get('uid') is not None
    }

PLURAL_NAMES = {"workout": "workouts", "session": "sessions"}

def _merge_objects(
    cal: Calendar,
    existing_by_uid: Dict[str, Event],
    live_uids: Set[str],
    objects: List[Dict],
    name: str,
    build,
    uid_of,
    min_duration_minutes: float = 0,
) -> None:
    """Build an event for each fetched object and merge it into the calendar."""
    stats = {"added": 0, "updated": 0, "unchanged": 0}
    skipped_short = 0
    skipped_invalid = 0
    for obj in objects:
        try:
            event = build(obj)
        except Exception as e:
            print(f"Skipping {name} {obj.get('id')} due to invalid data: {e}")
            skipped_invalid += 1
            # Keep the existing event of an object whose update failed to
            # parse rather than pruning it.
            if obj.get("id"):
                live_uids.add(uid_of(obj))
            continue
        duration = event.get('x-oura-duration')
        if min_duration_minutes and duration is not None \
                and int(str(duration)) / 60 < min_duration_minutes:
            skipped_short += 1
            continue
        live_uids.add(str(event.get('uid')))
        stats[_upsert_event(cal, existing_by_uid, event)] += 1

    message = (
        f"{PLURAL_NAMES.get(name, name).capitalize()}: added {stats['added']}, updated {stats['updated']}, "
        f"skipped {stats['unchanged']} unchanged, "
    )
    if min_duration_minutes:
        message += f"{skipped_short} shorter than {min_duration_minutes} min, "
    print(message + f"{skipped_invalid} invalid.")

def generate_activity_calendar(
    workouts: List[Dict],
    existing_calendar: Calendar,
    min_duration_minutes: float = 0,
    custom_activity_names: dict = None,
    sessions: Optional[List[Dict]] = None,
    daily_activity: Optional[List[Dict]] = None,
) -> Tuple[Calendar, Set[str]]:
    """
    Merge fetched Oura workouts, and optionally sessions and daily activity,
    into the calendar. Pass None for a collection that was not fetched.
    MIN_DURATION_MINUTES only applies to workouts.

    Returns (calendar, live_uids). live_uids holds the UID of every fetched
    object that still belongs in the calendar (including ones whose update
    failed to parse, so their existing event is kept), for use by
    prune_deleted_events.
    """
    cal = existing_calendar
    existing_by_uid = _index_events(cal)
    live_uids: Set[str] = set()

    _merge_objects(
        cal, existing_by_uid, live_uids, workouts, "workout",
        lambda w: _build_workout_event(w, custom_activity_names), workout_uid,
        min_duration_minutes=min_duration_minutes,
    )
    if sessions is not None:
        _merge_objects(
            cal, existing_by_uid, live_uids, sessions, "session",
            lambda s: _build_session_event(s, custom_activity_names), session_uid,
        )
    if daily_activity is not None:
        _merge_objects(
            cal, existing_by_uid, live_uids, daily_activity, "daily activity",
            _build_daily_activity_event, daily_activity_uid,
        )
    return cal, live_uids

def _is_monthly_summary(component) -> bool:
    """True if a calendar component is an auto-generated monthly summary event."""
    if component.name != "VEVENT":
        return False
    if component.get('x-oura-monthly-summary') is not None:
        return True
    uid = component.get('uid')
    return uid is not None and str(uid).startswith(MONTHLY_SUMMARY_UID_PREFIX)

def _event_kind(component) -> Optional[str]:
    """The X-OURA-KIND of one of our activity events, or None for anything else."""
    if component.name != "VEVENT" or _is_monthly_summary(component):
        return None
    kind = component.get('x-oura-kind')
    return str(kind) if kind is not None else None

def _event_day(component) -> Optional[date]:
    """
    The day an event belongs to: Oura's own `day` (stored in X-OURA-DAY) when
    available, otherwise the date the event starts on. Returns None if the
    event has no usable date.
    """
    stored = component.get('x-oura-day')
    if stored is not None:
        try:
            return date.fromisoformat(str(stored))
        except ValueError:
            pass
    dtstart = component.get('dtstart')
    value = getattr(dtstart, 'dt', None)
    # datetime is a subclass of date, so check it first to get the day portion.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None

def _int_prop(component, key) -> Optional[int]:
    value = component.get(key)
    if value is None:
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None

def _build_monthly_summary_event(year: int, month: int, totals: Dict) -> Event:
    """Create an all-day summary event on the last day of (year, month)."""
    last_day = date(year, month, monthrange(year, month)[1])
    workouts: Counter = totals["workouts"]
    sessions: Counter = totals["sessions"]
    steps: List[int] = totals["steps"]

    def by_count(counter: Counter) -> List[str]:
        # Most frequent first; ties broken alphabetically for stable output.
        return [
            f"{count}x {label}"
            for label, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    lines = [f"Workouts: {sum(workouts.values())}"]
    lines.extend(by_count(workouts))
    if workouts:
        lines.append(f"Total Workout Time: {convert_to_hh_mm(totals['workout_seconds'])}")
    if totals["distance"]:
        lines.append(f"Total Distance: {totals['distance'] / 1000:.1f} km")
    if totals["calories"]:
        lines.append(f"Total Calories: {_format_int(totals['calories'])} kcal")
    if steps:
        lines.append(
            f"Avg Daily Steps: {_format_int(sum(steps) / len(steps))} "
            f"({len(steps)} day{'s' if len(steps) != 1 else ''})"
        )
    if sessions:
        lines.append(f"Sessions: {sum(sessions.values())}")
        lines.extend(by_count(sessions))

    event = Event()
    event.add('uid', f"{MONTHLY_SUMMARY_UID_PREFIX}{year:04d}-{month:02d}")
    event.add('dtstart', last_day)  # date value -> all-day event
    event.add('dtend', last_day + timedelta(days=1))
    now_utc = datetime.now(timezone.utc)
    event.add('dtstamp', now_utc)
    event.add('created', now_utc)
    event.add('last-modified', now_utc)
    event.add('transp', 'TRANSPARENT')  # informational; don't mark as busy
    event.add('x-oura-monthly-summary', '1')
    event.add('summary', f"📊 Activity Summary, {last_day.strftime('%B %Y')}")
    event.add('description', "\n".join(lines))
    return event

def add_monthly_summaries(calendar: Calendar, custom_activity_names: dict = None, enabled: bool = True) -> Calendar:
    """
    Insert/refresh an all-day summary event on the last day of each month that
    contains activity events, with workout counts per activity type, total
    workout time, distance and calories, average daily steps and sessions.

    The summaries are computed from the X-OURA-* metrics of all activity events
    in the calendar, so months outside the fetch window keep accurate totals.
    Previously generated summaries are always dropped (so none linger after the
    feature is disabled) and re-added when enabled. A summary whose content is
    unchanged is preserved so calendar clients don't see spurious updates.
    """
    months: Dict[Tuple[int, int], Dict] = {}
    for component in calendar.walk('VEVENT'):
        kind = _event_kind(component)
        if kind is None:
            continue
        day = _event_day(component)
        if day is None:
            continue
        totals = months.setdefault((day.year, day.month), {
            "workouts": Counter(), "workout_seconds": 0, "distance": 0,
            "calories": 0, "steps": [], "sessions": Counter(),
        })
        if kind == KIND_WORKOUT:
            # Label from the raw activity type with the current config, so
            # renaming an activity also renames it in past summaries.
            activity = component.get('x-oura-activity')
            totals["workouts"][format_activity_label(activity, custom_activity_names)] += 1
            totals["workout_seconds"] += _int_prop(component, 'x-oura-duration') or 0
            totals["distance"] += _int_prop(component, 'x-oura-distance') or 0
            totals["calories"] += _int_prop(component, 'x-oura-calories') or 0
        elif kind == KIND_SESSION:
            session_type = component.get('x-oura-type')
            totals["sessions"][format_session_label(session_type, custom_activity_names)] += 1
        elif kind == KIND_DAILY_ACTIVITY:
            steps = _int_prop(component, 'x-oura-steps')
            if steps is not None:
                totals["steps"].append(steps)

    existing_summaries = {
        str(c.get('uid')): c for c in calendar.walk('VEVENT') if _is_monthly_summary(c)
    }
    calendar.subcomponents = [c for c in calendar.subcomponents if not _is_monthly_summary(c)]
    if not enabled:
        if existing_summaries:
            print(f"Monthly summaries disabled; removed {len(existing_summaries)} existing summary event(s).")
        return calendar

    created = 0
    preserved = 0
    for (year, month), totals in sorted(months.items()):
        event = _build_monthly_summary_event(year, month, totals)
        prev = existing_summaries.get(str(event.get('uid')))
        if prev is not None and _same_content(prev, event):
            calendar.add_component(prev)
            preserved += 1
            continue
        # Preserve the original CREATED time when refreshing a month's summary.
        if prev is not None and prev.get('created') is not None:
            event.pop('created', None)
            event.add('created', prev.get('created').dt)
        calendar.add_component(event)
        created += 1

    print(
        f"Monthly summaries: {len(months)} month(s) "
        f"({created} created/updated, {preserved} unchanged)."
    )
    return calendar

def save_calendar(calendar: Calendar, path: str) -> bool:
    """Write the calendar to disk. Returns True on success, False on I/O error."""
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(calendar.to_ical())
        return True
    except OSError as e:
        print(f"❌ Failed to save calendar to '{path}': {e}")
        return False
