"""
Surveille les places du Nintendo Museum (Uji, Kyoto) et envoie une notif
push sur ton téléphone via ntfy dès qu'une date de ton voyage se libère.

Utilise le calendrier public de la billetterie (aucune connexion au compte
Nintendo, donc aucun risque pour ton compte). Il ne réserve rien : il te
prévient, tu réserves à la main.
"""
import os
import sys
import time
from datetime import date, datetime, timedelta

import requests
from curl_cffi import requests as cffi_requests

# --- Réglages -------------------------------------------------------------
# Tes jours à Kyoto (le musée est fermé le mardi, le script les ignore).
TARGET_DATES = os.environ.get(
    "TARGET_DATES", "2026-10-14,2026-10-15,2026-10-16,2026-10-17,2026-10-18"
).split(",")
CHECK_EVERY_SECONDS = int(os.environ.get("CHECK_EVERY_SECONDS", "90"))
RUN_FOR_MINUTES = int(os.environ.get("RUN_FOR_MINUTES", "55"))
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
TEST_NOTIFICATION = os.environ.get("TEST_NOTIFICATION", "false").lower() == "true"
# --------------------------------------------------------------------------

API_URL = "https://museum-tickets.nintendo.com/en/api/calendar"
BOOKING_URL = "https://museum-tickets.nintendo.com/en/calendar"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def notify(title, message, priority="urgent", tags="video_game"):
    if not NTFY_TOPIC:
        log(f"(pas de NTFY_TOPIC) {title} - {message}")
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,  # ASCII only dans les en-têtes HTTP
                "Priority": priority,
                "Tags": tags,
                "Click": BOOKING_URL,
            },
            timeout=15,
        )
    except requests.RequestException as e:
        log(f"Echec envoi notif : {e}")


def months_to_check(dates):
    return sorted({(int(d[:4]), int(d[5:7])) for d in dates})


SESSION = cffi_requests.Session(impersonate="chrome")
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BOOKING_URL,
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
}
_warmed_up = False


def fetch_month(year, month):
    global _warmed_up
    if not _warmed_up:
        # Ouvre d'abord la page calendrier comme un navigateur (cookies).
        SESSION.get(BOOKING_URL, timeout=30)
        _warmed_up = True
    r = SESSION.get(
        API_URL,
        params={"target_year": year, "target_month": month},
        headers=HEADERS,
        timeout=30,
    )
    if r.status_code != 200:
        _reset()
        raise RuntimeError(f"HTTP {r.status_code} : {r.text[:200]!r}")
    try:
        return r.json()["data"]["calendar"]
    except Exception:
        _reset()
        raise RuntimeError(f"Reponse pas en JSON : {r.text[:200]!r}")


def _reset():
    global _warmed_up
    _warmed_up = False


def available_dates(calendars, dates):
    """Dates cibles ouvertes (open_status 1) et en vente (sale_status 1)."""
    found = []
    for d in dates:
        day = calendars.get(d)
        if day and day.get("open_status") == 1 and day.get("sale_status") == 1:
            found.append(d)
    return found


def label(d):
    dt = date.fromisoformat(d)
    return f"{JOURS[dt.weekday()]} {dt.day}/{dt.month}"


def main():
    dates = [d.strip() for d in TARGET_DATES if d.strip()]
    if not dates:
        sys.exit("Aucune date configurée.")

    if TEST_NOTIFICATION:
        notify("Test Nintendo Museum", "Les notifs marchent ! Le bot surveille : "
               + ", ".join(label(d) for d in dates), priority="default", tags="white_check_mark")
        log("Notif de test envoyée.")
        return

    if date.fromisoformat(max(dates)) < date.today():
        log("Toutes les dates sont passées, rien à surveiller.")
        return

    deadline = time.time() + RUN_FOR_MINUTES * 60
    already_notified = set()
    errors = 0
    error_alert_sent = False

    while time.time() < deadline:
        try:
            calendars = {}
            for y, m in months_to_check(dates):
                calendars.update(fetch_month(y, m))
            errors, error_alert_sent = 0, False

            etats = " ".join(
                f"{d[5:]}={calendars.get(d, {}).get('sale_status', '?')}" for d in dates)
            found = available_dates(calendars, dates)
            new = [d for d in found if d not in already_notified]
            if new:
                jours = ", ".join(label(d) for d in new)
                notify("Nintendo Museum : place dispo !",
                       f"Place(s) libre(s) : {jours}. Fonce, ca part en quelques minutes !")
                log(f"DISPO : {jours}")
            else:
                log(("Rien de libre." if not found else "Toujours dispo (deja notifie).")
                    + f"  [{etats}]  (1=dispo, 2=complet)")
            # Si une date repart en complet, on pourra re-notifier si elle revient.
            already_notified = set(found)

        except Exception as e:
            errors += 1
            log(f"Erreur ({errors}) : {e}")
            if errors >= 5 and not error_alert_sent:
                notify("Bot Nintendo Museum en panne",
                       f"Impossible de lire le site depuis plusieurs essais : {e}",
                       priority="default", tags="warning")
                error_alert_sent = True

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
