from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
from icalendar import Calendar, Event
import os
import re

# Kinds of Oura objects turned into events, stored in X-OURA-KIND so later runs
# can recognise (and summarise or prune) their own events straight from the
# calendar file, which is the only persistence layer.
KIND_WORKOUT = "workout"

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

def generate_activity_calendar(
    workouts: List[Dict],
    existing_calendar: Calendar,
    min_duration_minutes: float = 0,
    custom_activity_names: dict = None,
) -> Tuple[Calendar, Set[str]]:
    """
    Merge fetched Oura workouts into the calendar.

    Returns (calendar, live_uids). live_uids holds the UID of every fetched
    object that still belongs in the calendar (including ones whose update
    failed to parse, so their existing event is kept), for use by
    prune_deleted_events.
    """
    cal = existing_calendar
    existing_by_uid = _index_events(cal)
    live_uids: Set[str] = set()

    stats = {"added": 0, "updated": 0, "unchanged": 0}
    skipped_short = 0
    skipped_invalid = 0
    for workout in workouts:
        try:
            event = _build_workout_event(workout, custom_activity_names)
        except Exception as e:
            print(f"Skipping workout {workout.get('id')} due to invalid data: {e}")
            skipped_invalid += 1
            if workout.get("id"):
                live_uids.add(workout_uid(workout))
            continue
        duration_minutes = int(str(event.get('x-oura-duration'))) / 60
        if duration_minutes < min_duration_minutes:
            skipped_short += 1
            continue
        live_uids.add(str(event.get('uid')))
        stats[_upsert_event(cal, existing_by_uid, event)] += 1

    print(
        f"Workouts: added {stats['added']}, updated {stats['updated']}, "
        f"skipped {stats['unchanged']} unchanged, {skipped_short} shorter than "
        f"{min_duration_minutes} min, {skipped_invalid} invalid."
    )
    return cal, live_uids

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
