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
# - id values are uniqueTournament ids from SofaScore
# - slug aliases are kept as fallback
# =====================================================

LEAGUES = {
    "Süper Lig": {"ids": [52], "slugs": ["super-lig"]},
    "Premier League": {"ids": [17], "slugs": ["premier-league"]},
    "LaLiga": {"ids": [8], "slugs": ["laliga", "laliga-ea-sports"]},
    "Serie A": {"ids": [23], "slugs": ["serie-a"]},
    "Bundesliga": {"ids": [35], "slugs": ["bundesliga"]},
    "Ligue 1": {"ids": [34], "slugs": ["ligue-1"]},
}


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
def get_http_session():
    session = requests.Session()
    # Environment proxy'lerini devre dışı bırakır (bazı ortamlarda 403 proxy hatasını önler)
    session.trust_env = False

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


def fetch_json(session, url, timeout=20):
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, str(exc)

    try:
        return response.json(), None
    except ValueError:
        return None, "API JSON döndürmedi"


def is_target_league(ev, selected_league):
    tournament = ev.get("tournament", {})
    unique = tournament.get("uniqueTournament", {})

    t_id = unique.get("id")
    t_slug = str(unique.get("slug", "")).lower()

    id_match = t_id in selected_league["ids"]
    slug_match = t_slug in selected_league["slugs"]

    return id_match or slug_match


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

    dates = list(daterange(start_date, end_date))
    if not dates:
        return pd.DataFrame([]), 0, 0, ["Geçersiz tarih aralığı"]

    session = get_http_session()
    progress = st.progress(0)
    status = st.empty()

    for i, date in enumerate(dates):
        progress.progress((i + 1) / len(dates))
        status.text(f"Taranıyor: {date}")

        scheduled_url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date}"
        schedule_data, err = fetch_json(session, scheduled_url)

        if err:
            errors.append(f"{date} programı alınamadı: {err}")
            continue

        events = schedule_data.get("events", [])
        for ev in events:
            scanned_events += 1

            if not is_target_league(ev, selected_league):
                continue

            match_id = ev.get("id")
            if not match_id:
                continue

            total_matches += 1

            lineup_data, lineup_err = fetch_json(
                session,
                f"https://api.sofascore.com/api/v1/event/{match_id}/lineups",
            )
            if lineup_err:
                errors.append(f"{match_id} lineups alınamadı: {lineup_err}")
                continue

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

    return pd.DataFrame(final), total_matches, scanned_events, errors


# =====================================================
# UI
# =====================================================

st.set_page_config(layout="wide")
st.title("⚽ Futbol Oyuncu Analiz Aracı")

with st.sidebar:
    league_name = st.selectbox("Lig", list(LEAGUES.keys()))
    selected_league = LEAGUES[league_name]

    today = datetime.today().date()
    start = st.date_input("Başlangıç", today - timedelta(days=30))
    end = st.date_input("Bitiş", today)

    st.subheader("Minimum Dakika")

    min_minutes = {
        "GK": st.number_input("GK", min_value=0, value=300, step=30),
        "DEF": st.number_input("DEF", min_value=0, value=300, step=30),
        "MID": st.number_input("MID", min_value=0, value=300, step=30),
        "FWD": st.number_input("FWD", min_value=0, value=240, step=30),
    }

    run = st.button("🚀 Analizi Başlat", use_container_width=True)

if run:
    if start > end:
        st.error("Başlangıç tarihi, bitiş tarihinden büyük olamaz.")
        st.stop()

    df, matches, scanned_events, errors = fetch_data(
        selected_league,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        min_minutes,
    )

    st.caption(f"Toplam {scanned_events} maç olayı tarandı.")

    if errors:
        with st.expander("Bağlantı / API hataları", expanded=False):
            for item in errors[:20]:
                st.warning(item)
            if len(errors) > 20:
                st.info(f"{len(errors) - 20} hata daha var.")

    if df.empty:
        st.error("Veri bulunamadı. Tarih aralığını genişletin veya minimum dakika filtrelerini düşürün.")
    else:
        st.success(f"{matches} maç incelendi")

        tabs = st.tabs(["GK", "DEF", "MID", "FWD"])
        for grp, tab in zip(["GK", "DEF", "MID", "FWD"], tabs):
            with tab:
                st.dataframe(
                    df[df["Grup"] == grp].drop(columns=["Grup"]),
                    use_container_width=True,
                )
