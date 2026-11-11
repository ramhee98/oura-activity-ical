# Oura Activity iCal

Generate an activity calendar from your Oura Ring workouts, sessions and daily activity as an `.ics` file you can import into calendar apps like Google Calendar, Apple Calendar, or Outlook.

## Features

- Fetches workouts, sessions and daily activity from the Oura API v2
- Converts them into iCalendar format (`.ics`)
- Preserves existing data: Automatically merges new data with existing calendar entries, preventing data loss
- Keeps events fresh: an event that already exists (matched by its stable UID derived from the Oura object id) is refreshed in place when its data changes, including metrics not shown in the event text
- Duplicate prevention: Skips events that already exist and haven't changed
- Supports pagination for large datasets
- Workouts as timed events, titled with icon, activity and duration (e.g. `🏃 Running 0:52`), with activity, duration, distance, calories, intensity, source and label in the description
- Emoji-labeled activity types for quick recognition:
  - 🏃 Running, 🚶 Walking, 🥾 Hiking, 🚴 Cycling, 🚵 Mountain Biking
  - 🏋️ Strength Training, 🔥 HIIT, 🏊 Swimming, 🧘 Yoga, 🤸 Pilates
  - ⛷️ Skiing, 🏂 Snowboarding, ⛸️ Ice Skating, 🧗 Climbing, 🚣 Rowing
  - 🎾 Tennis, 🏸 Badminton, ⚽ Soccer, 🏀 Basketball, 💃 Dancing, and more
  - 🏅 as fallback for unknown activity types
- Configurable activity names with custom icons via `CUSTOM_ACTIVITY_NAMES`
- `--discover` mode to list all activity types found and print a ready-to-paste `CUSTOM_ACTIVITY_NAMES` config block
- Optional sessions (🧘 Meditation, 🌬️ Breathing, 🛀 Relaxation, ...) as timed events with mood and average heart rate / HRV, toggleable via `INCLUDE_SESSIONS`
- Optional daily activity as an all-day event per day with activity score, steps, active calories, total calories and walking-equivalent distance, toggleable via `INCLUDE_DAILY_ACTIVITY`
- Monthly summaries: adds an all-day "Activity Summary" event on the last day of each month with workout counts per activity type, total workout time, distance, calories and average daily steps. Recomputed on every run and toggleable via `MONTHLY_SUMMARY`
- Skips workouts shorter than a configurable duration (`MIN_DURATION_MINUTES`)
- Keeps the calendar in sync with the app: workouts, sessions and days deleted in Oura are removed from the calendar within the fetched `DAYS_BACK` window (disable with `--no-prune`)
- `--dry-run` mode to preview the resulting events without writing the file
- Compatible with major calendar clients

## Requirements

- Python 3.8+
- Oura API access token with `workout` scope, plus `session` for `INCLUDE_SESSIONS` and `daily` for `INCLUDE_DAILY_ACTIVITY`
- Dependencies:
  - `icalendar`
  - `requests`

**Note**: Oura deprecated personal access tokens in December 2025. Create an [API Application](https://cloud.ouraring.com/oauth/applications) and use an OAuth2 access token with the scopes above as `OURA_TOKEN`.

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/ramhee98/oura-activity-ical.git
   cd oura-activity-ical
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create `config.py` or copy `config.py.template` and modify it with:
   ```bash
   cp config.py.template config.py
   ```

## Configuration

Edit `config.py` with your settings:

```python
# Your Oura API access token (requires the 'workout' scope, plus 'session'
# for INCLUDE_SESSIONS and 'daily' for INCLUDE_DAILY_ACTIVITY)
OURA_TOKEN = "your-token-here"

# Path where the generated iCalendar (.ics) file will be saved
ICAL_OUTPUT_PATH = "./activity.ics"

# Number of past days to fetch activity data for
DAYS_BACK = 7

# Minimum duration (in minutes) for a workout to be included in the calendar
MIN_DURATION_MINUTES = 10

# Add Oura sessions (meditation, breathing, relaxation, ...) as timed events
INCLUDE_SESSIONS = False

# Add an all-day event per day with score, steps, calories and distance
INCLUDE_DAILY_ACTIVITY = True

# Add an all-day "Activity Summary" event on the last day of each month
MONTHLY_SUMMARY = True

# Override the name and icon of activity types (workouts and sessions)
# Find your activity types by running: python3 main.py --discover
CUSTOM_ACTIVITY_NAMES = {
    "strength_training": "💪 Gym",
    "meditation": "🕯️ Evening Meditation",
}
```

`MIN_DURATION_MINUTES` only applies to workouts; sessions and daily activity are always included when enabled.

## Usage

### Sync activity to calendar

```bash
python3 main.py
```

This will:
1. Fetch workouts (and, if enabled, sessions and daily activity) from the Oura API for the specified number of days
2. Load any existing calendar data from your `activity.ics` file
3. Add new events and refresh any events whose data changed (matched by unique ID)
4. Remove events deleted in Oura within the fetched window
5. Refresh the monthly summary events
6. Save the updated calendar to `activity.ics`

**Note**: The script automatically preserves your existing activity data, so you can run it regularly to update your calendar with new entries without losing historical data. To re-process older entries, run once with a larger `DAYS_BACK`. If any Oura API request fails, the run is aborted and the calendar file is left untouched.

### Monthly summaries

On every sync, the script adds (and keeps up to date) an **all-day summary event on the last day of each month** that contains activity. The event lists your workouts per activity type and the month's totals, so you get an at-a-glance overview directly in your calendar app:

**Title:**
```
📊 Activity Summary, June 2026
```

**Description:**
```
Workouts: 14
6x 🏃 Running
4x 🏋️ Strength Training
3x 🚴 Cycling
1x 🥾 Hiking
Total Workout Time: 15:42
Total Distance: 187.3 km
Total Calories: 8,912 kcal
Avg Daily Steps: 9,874 (30 days)
Sessions: 5
4x 🧘 Meditation
1x 🌬️ Breathing
```

Summaries are derived from your real activity events, so they are recomputed on every run and never counted as activity themselves. Average daily steps are taken from the daily activity events, so they require `INCLUDE_DAILY_ACTIVITY = True`. Activity names follow your current `CUSTOM_ACTIVITY_NAMES`, also for past months. Unchanged summaries are left untouched to avoid spurious updates in calendar clients. Set `MONTHLY_SUMMARY = False` to remove them.

### Discover activity types

```bash
python3 main.py --discover
```

Lists all activity types found in the last `DAYS_BACK` days (workouts, plus session types when `INCLUDE_SESSIONS` is enabled) and prints a ready-to-paste `CUSTOM_ACTIVITY_NAMES` dict. Types already mapped in `config.py` are shown with their current label. Other types show the default label, how often they occurred and when they were last seen:

```
Found 4 activity type(s) in the last 30 days. Add this to your config.py and adjust names/icons as you like:

CUSTOM_ACTIVITY_NAMES = {
    "running": "🏃 Running",  # 9 workouts, last seen: 2026-06-29T07:12:00+02:00
    "strength_training": "💪 Gym",  # already in config
    "bouldering": "🧗 Bouldering",  # 3 workouts, last seen: 2026-06-26T18:30:00+02:00
    "meditation": "🧘 Meditation",  # 2 sessions, last seen: 2026-06-28T21:00:00+02:00
}
```

Keep only the entries you want to change. Increase `DAYS_BACK` in `config.py` if you expect older activity types to appear.

### Pruning deleted events

By default, each run removes calendar events whose workout, session or daily activity no longer exists in Oura, for example a workout you deleted in the app. Workouts that no longer meet `MIN_DURATION_MINUTES` are removed the same way. Pruning is scoped to the fetched window: only events whose day falls within the last `DAYS_BACK` days are eligible, so older events are never touched (the fetch carries no information about them). Only data types that were actually fetched are pruned, so disabling `INCLUDE_SESSIONS` or `INCLUDE_DAILY_ACTIVITY` keeps the events already in the calendar. Monthly summary events are regenerated separately and are never pruned.

To keep stale events instead, run with `--no-prune`:

```bash
python3 main.py --no-prune
```

### Dry run

```bash
python3 main.py --dry-run
```

Fetches and processes everything like a normal sync, then prints the resulting events of the fetched window instead of writing the calendar file:

```
Dry run: not writing ./activity.ics. Events from 2026-06-23 to 2026-06-30:

  2026-06-28 07:12    🏃 Running 0:52
  2026-06-28 all-day  👟 Activity 86, 12,345 steps
  2026-06-28 21:00    🧘 Meditation 0:12
  2026-06-30 all-day  📊 Activity Summary, June 2026
```

## Example Calendar Output

**Title (workout):**
```
🏃 Running 0:52
```

**Description:**
```
Activity: 🏃 Running
Duration: 0:52
Distance: 8.42 km
Calories: 612 kcal
Intensity: Moderate
Source: Autodetected
Label: Morning run
```

**Title (session):**
```
🧘 Meditation 0:12
```

**Description:**
```
Type: 🧘 Meditation
Duration: 0:12
Mood: Good
Avg Heart Rate: 58 bpm
Avg HRV: 64 ms
```

**Title (daily activity, all-day event):**
```
👟 Activity 86, 12,345 steps
```

**Description:**
```
Activity Score: 86
Steps: 12,345
Active Calories: 512 kcal
Total Calories: 2,634 kcal
Walking Equivalent: 9.8 km
```

## Related

- [oura-sleep-ical](https://github.com/ramhee98/oura-sleep-ical): Generate a sleep calendar from Oura Ring data
- [oura-tags-ical](https://github.com/ramhee98/oura-tags-ical): Generate a tag calendar from Oura Ring Enhanced Tags
