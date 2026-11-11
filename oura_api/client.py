import requests
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

OURA_API_ROOT = "https://api.ouraring.com/v2/usercollection"
OURA_WORKOUT_URL = f"{OURA_API_ROOT}/workout"
OURA_SESSION_URL = f"{OURA_API_ROOT}/session"
OURA_DAILY_ACTIVITY_URL = f"{OURA_API_ROOT}/daily_activity"

# The Oura API asks every client to identify itself with a User-Agent header
# and may reject requests without one.
USER_AGENT = "oura-activity-ical/1.0"

def fetch_window(days_back: int = 7) -> Tuple[date, date]:
    """
    Return the (start_date, end_date) window of a sync: the last `days_back`
    days up to and including today. All collections are fetched for the same
    window so pruning of deleted events can be scoped to exactly what was
    fetched.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    return start_date, end_date

def fetch_workouts(token: str, start_date: date, end_date: date) -> Optional[List[Dict]]:
    """Fetch workout documents (requires the 'workout' scope)."""
    return _fetch_collection(OURA_WORKOUT_URL, token, start_date, end_date)

def fetch_sessions(token: str, start_date: date, end_date: date) -> Optional[List[Dict]]:
    """Fetch session documents such as meditation or breathing (requires the 'session' scope)."""
    return _fetch_collection(OURA_SESSION_URL, token, start_date, end_date)

def fetch_daily_activity(token: str, start_date: date, end_date: date) -> Optional[List[Dict]]:
    """Fetch daily activity documents (requires the 'daily' scope)."""
    return _fetch_collection(OURA_DAILY_ACTIVITY_URL, token, start_date, end_date)

def _fetch_collection(url: str, token: str, start_date: date, end_date: date) -> Optional[List[Dict]]:
    """
    Fetch every document of an Oura collection in [start_date, end_date],
    following `next_token` pagination.

    Returns None (and prints a friendly message) on network errors, auth
    failures, or malformed responses. Callers must treat None as "unknown"
    rather than "empty", so a failed fetch never prunes existing events.
    """
    name = url.rsplit("/", 1)[-1]
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
    # Query one day past the window so today is always covered, whether the
    # API treats end_date as inclusive or exclusive.
    params = {
        "start_date": start_date.isoformat(),
        "end_date": (end_date + timedelta(days=1)).isoformat(),
    }

    all_data = []
    next_token = None

    while True:
        if next_token:
            params["next_token"] = next_token

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"❌ Could not reach the Oura API ({name}): {e}")
            return None

        if response.status_code == 401:
            print("❌ Oura API rejected the access token (HTTP 401). "
                  "Check OURA_TOKEN in config.py.")
            return None
        if response.status_code == 403:
            print(f"❌ Oura API denied access to '{name}' (HTTP 403). "
                  "Check that the token has the required scope and that your "
                  "Oura membership is active.")
            return None
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            hint = f" Retry after {retry_after} seconds." if retry_after else " Try again later."
            print(f"❌ Oura API rate limit hit (HTTP 429).{hint}")
            return None
        if not response.ok:
            print(f"❌ Oura API returned HTTP {response.status_code} for '{name}': {response.text[:200]}")
            return None

        try:
            data = response.json()
        except ValueError:
            print(f"❌ Oura API returned a non-JSON response for '{name}'.")
            return None
        if not isinstance(data, dict):
            print(f"❌ Oura API returned an unexpected response for '{name}'.")
            return None

        all_data.extend(data.get("data") or [])

        next_token = data.get("next_token")
        if not next_token:
            break

    return all_data
