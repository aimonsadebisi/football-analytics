import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =====================================================
# HEADERS
# =====================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}

# =====================================================
# LEAGUES
# id values are uniqueTournament ids from SofaScore
# =====================================================

LEAGUES = {
    "Süper Lig": {"ids": [52], "slugs": ["super-lig"]},
    "Premier League": {"ids": [17], "slugs": ["premier-league"]},
    "LaLiga": {"ids": [8], "slugs": ["laliga", "laliga-ea-sports"]},
    "Serie A": {"ids": [23], "slugs": ["serie-a"]},
    "Bundesliga": {"ids": [35], "slugs": ["bundesliga"]},
    "Ligue 1": {"ids": [34], "slugs": ["ligue-1"]},
}

# API endpoint fallback order
SCHEDULE_ENDPOINTS = [
    "https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date}",
    "https://www.sofascore.com/api/v1/sport/football/scheduled-events/{date}",
    "https://api.sofascore.com/api/v1/sport/football/events/{date}",
    "https://www.sofascore.com/api/v1/sport/football/events/{date}",
]


def daterange(start, end):
    d1 = datetime.strptime(start, "%Y-%m-%d")
    d2 = datetime.strptime(end, "%Y-%m-%d")
    while d1 <= d2:
        yield d1.strftime("%Y-%m-%d")
        d1 += timedelta(days=1)


def group_pos(pos):
    p = (pos or "").upper()
    if p.startswith("G"):
        return "GK"
    if p.startswith("D"):
        return "DEF"
    if p.startswith("M"):
        return "MID"
    return "FWD"


@st.cache_resource
def get_http_session(use_env_proxy):
    session = requests.Session()
    session.trust_env = use_env_proxy

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)
    return session


def fetch_json(url, timeout=20):
    """Try direct first, then env-proxy session as fallback."""
    sessions = [
        (get_http_session(False), "direct"),
        (get_http_session(True), "proxy"),
    ]

    last_err = None
    for session, mode in sessions:
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json(), None
        except ValueError:
            last_err = f"{mode}: API JSON döndürmedi"
        except requests.RequestException as exc:
            last_err = f"{mode}: {exc}"

    return None, last_err


def is_target_league(ev, selected_league):
    tournament = ev.get("tournament", {})
    unique = tournament.get("uniqueTournament", {})

    t_id = unique.get("id")
    t_slug = str(unique.get("slug", "")).lower()

    return (t_id in selected_league["ids"]) or (t_slug in selected_league["slugs"])


def is_played_match(ev):
    # SofaScore status examples: finished, inprogress, notstarted, postponed
    status = str(ev.get("status", {}).get("type", "")).lower()
    return status in {"finished", "inprogress"}


def fetch_schedule_for_date(date):
    errors = []
    for endpoint in SCHEDULE_ENDPOINTS:
        url = endpoint.format(date=date)
        data, err = fetch_json(url)
        if err:
            errors.append(f"{url} -> {err}")
            continue

        events = data.get("events", []) if isinstance(data, dict) else []
        if events:
            return events, None

        # endpoint worked but returned empty; keep as potential info
        errors.append(f"{url} -> 0 event")

    return [], " | ".join(errors)


def fetch_data(selected_league, start_date, end_date, min_minutes):
    players = {}
    errors = []

    def ensure(name):
        if name not in players:
            players[name] = {
                "team": "",
                "pos": "",
                "ratings": [],
                "minutes": 0,
                "match_ids": set(),
            }
        return players[name]

    total_matches = 0
    scanned_events = 0
    league_events = 0
    lineup_success = 0

    dates = list(daterange(start_date, end_date))
    if not dates:
        return pd.DataFrame([]), 0, 0, ["Geçersiz tarih aralığı"], 0, 0

    progress = st.progress(0)
    status = st.empty()

    for i, date in enumerate(dates):
        progress.progress((i + 1) / len(dates))
        status.text(f"Taranıyor: {date}")

        events, schedule_err = fetch_schedule_for_date(date)
        if schedule_err and not events:
            errors.append(f"{date} programı alınamadı: {schedule_err}")
            continue

        for ev in events:
            scanned_events += 1

            if not is_target_league(ev, selected_league):
                continue

            league_events += 1

            if not is_played_match(ev):
                # Not-started matches have no ratings/lineups yet.
                continue

            match_id = ev.get("id")
            if not match_id:
                continue

            total_matches += 1

            lineup_data, lineup_err = fetch_json(
                f"https://api.sofascore.com/api/v1/event/{match_id}/lineups"
            )
            if lineup_err:
                # lineups endpoint on www as fallback
                lineup_data, lineup_err = fetch_json(
                    f"https://www.sofascore.com/api/v1/event/{match_id}/lineups"
                )

            if lineup_err or not isinstance(lineup_data, dict):
                errors.append(f"{match_id} lineups alınamadı: {lineup_err}")
                continue

            lineup_success += 1

            for side in ("home", "away"):
                team = ev.get("homeTeam", {}).get("name", "") if side == "home" else ev.get("awayTeam", {}).get("name", "")

                for pl in lineup_data.get(side, {}).get("players", []):
                    name = pl.get("player", {}).get("name")
                    if not name:
                        continue

                    stats = pl.get("statistics", {})
                    rating = stats.get("rating")
                    if rating is None:
                        continue

                    try:
                        minutes = int(stats.get("minutesPlayed", 0) or 0)
                    except (TypeError, ValueError):
                        minutes = 0
                    minutes = max(0, min(minutes, 130))

                    rec = ensure(name)
                    if match_id in rec["match_ids"]:
                        continue

                    rec["match_ids"].add(match_id)
                    rec["team"] = team
                    rec["ratings"].append(float(rating))
                    rec["minutes"] += minutes

                    pos = pl.get("position")
                    if pos:
                        rec["pos"] = pos

    progress.empty()
    status.empty()

    final = []
    for name, rec in players.items():
        grp = group_pos(rec["pos"])

        if rec["minutes"] < min_minutes.get(grp, 0):
            continue
        if not rec["ratings"]:
            continue

        avg = sum(rec["ratings"]) / len(rec["ratings"])

        final.append(
            {
                "Oyuncu": name,
                "Takım": rec["team"],
                "Pozisyon": rec["pos"],
                "Grup": grp,
                "Rating": round(avg, 2),
                "Dakika": rec["minutes"],
                "Maç": len(rec["match_ids"]),
            }
        )

    final.sort(key=lambda x: x["Rating"], reverse=True)

    return pd.DataFrame(final), total_matches, scanned_events, errors, league_events, lineup_success


# =====================================================
# UI
# =====================================================

st.set_page_config(layout="wide")
st.title("⚽ Futbol Oyuncu Analiz Aracı")

with st.sidebar:
    league_name = st.selectbox("Lig", list(LEAGUES.keys()))
    selected_league = LEAGUES[league_name]

    today = datetime.today().date()
    start = st.date_input("Başlangıç", today - timedelta(days=14))
    end = st.date_input("Bitiş", today)

    st.subheader("Minimum Dakika")

    min_minutes = {
        "GK": st.number_input("GK", min_value=0, value=180, step=30),
        "DEF": st.number_input("DEF", min_value=0, value=180, step=30),
        "MID": st.number_input("MID", min_value=0, value=180, step=30),
        "FWD": st.number_input("FWD", min_value=0, value=150, step=30),
    }

    run = st.button("🚀 Analizi Başlat", use_container_width=True)

if run:
    if start > end:
        st.error("Başlangıç tarihi, bitiş tarihinden büyük olamaz.")
        st.stop()

    df, matches, scanned_events, errors, league_events, lineup_success = fetch_data(
        selected_league,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        min_minutes,
    )

    st.caption(
        f"Taranan event: {scanned_events} | Lig eşleşen: {league_events} | Lineup alınan: {lineup_success}"
    )

    if errors:
        with st.expander("Bağlantı / API hataları", expanded=False):
            for item in errors[:30]:
                st.warning(item)
            if len(errors) > 30:
                st.info(f"{len(errors) - 30} hata daha var.")

    if df.empty:
        st.error(
            "Veri bulunamadı. Olası sebepler: (1) tarih aralığında oynanmış maç yok, "
            "(2) API erişimi engelli, (3) dakika filtresi yüksek."
        )
    else:
        st.success(f"{matches} maç incelendi")

        tabs = st.tabs(["GK", "DEF", "MID", "FWD"])
        for grp, tab in zip(["GK", "DEF", "MID", "FWD"], tabs):
            with tab:
                st.dataframe(
                    df[df["Grup"] == grp].drop(columns=["Grup"]),
                    use_container_width=True,
                )
