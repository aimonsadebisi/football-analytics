import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# =====================================================
# HEADERS (VERY IMPORTANT FOR STREAMLIT CLOUD)
# =====================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com"
}

# =====================================================
# LEAGUES (SLUG BASED - STABLE)
# =====================================================

LEAGUES = {
    "Süper Lig": "super-lig",
    "Premier League": "premier-league",
    "LaLiga": "laliga",
    "Serie A": "serie-a",
    "Bundesliga": "bundesliga",
    "Ligue 1": "ligue-1",
}

# =====================================================
# HELPERS
# =====================================================

def daterange(start, end):
    d1 = datetime.strptime(start, "%Y-%m-%d")
    d2 = datetime.strptime(end, "%Y-%m-%d")
    while d1 <= d2:
        yield d1.strftime("%Y-%m-%d")
        d1 += timedelta(days=1)


def group_pos(pos):
    p = (pos or "").upper()
    if p.startswith("G"): return "GK"
    if p.startswith("D"): return "DEF"
    if p.startswith("M"): return "MID"
    return "FWD"


# =====================================================
# ✅ STABLE LEAGUE FILTER
# =====================================================

def is_target_league(ev, slug):

    tournament = ev.get("tournament", {})
    unique = tournament.get("uniqueTournament", {})

    league_slug = str(unique.get("slug", "")).lower()

    return league_slug == slug


# =====================================================
# DATA FETCH
# =====================================================

def fetch_data(league_slug, start_date, end_date, min_minutes):

    players = {}

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

    dates = list(daterange(start_date, end_date))

    progress = st.progress(0)
    status = st.empty()

    for i, date in enumerate(dates):

        progress.progress((i + 1) / len(dates))
        status.text(f"Taranıyor: {date}")

        try:
            r = requests.get(
                f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date}",
                headers=HEADERS,
                timeout=20,
            )
        except:
            continue

        if r.status_code != 200:
            continue

        for ev in r.json().get("events", []):

            if not is_target_league(ev, league_slug):
                continue

            match_id = ev.get("id")
            if not match_id:
                continue

            total_matches += 1

            lr = requests.get(
                f"https://api.sofascore.com/api/v1/event/{match_id}/lineups",
                headers=HEADERS,
                timeout=20,
            )

            if lr.status_code != 200:
                continue

            lineup = lr.json()

            for side in ("home", "away"):

                team = ev["homeTeam"]["name"] if side=="home" else ev["awayTeam"]["name"]

                for pl in lineup.get(side, {}).get("players", []):

                    name = pl.get("player", {}).get("name")
                    if not name:
                        continue

                    stats = pl.get("statistics", {})
                    rating = stats.get("rating")

                    if rating is None:
                        continue

                    minutes = int(stats.get("minutesPlayed", 0))
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

    # BUILD FINAL
    final = []

    for name, rec in players.items():

        grp = group_pos(rec["pos"])

        if rec["minutes"] < min_minutes.get(grp, 0):
            continue

        avg = sum(rec["ratings"]) / len(rec["ratings"])

        final.append({
            "Oyuncu": name,
            "Takım": rec["team"],
            "Pozisyon": rec["pos"],
            "Grup": grp,
            "Rating": round(avg,2),
            "Dakika": rec["minutes"],
            "Maç": len(rec["match_ids"])
        })

    final.sort(key=lambda x: x["Rating"], reverse=True)

    return pd.DataFrame(final), total_matches


# =====================================================
# UI
# =====================================================

st.set_page_config(layout="wide")
st.title("⚽ Futbol Oyuncu Analiz Aracı")

with st.sidebar:

    league = st.selectbox("Lig", list(LEAGUES.keys()))
    league_slug = LEAGUES[league]

    start = st.date_input("Başlangıç", datetime(2025,9,1))
    end = st.date_input("Bitiş", datetime(2026,1,1))

    st.subheader("Minimum Dakika")

    min_minutes = {
        "GK": st.number_input("GK",900),
        "DEF": st.number_input("DEF",900),
        "MID": st.number_input("MID",900),
        "FWD": st.number_input("FWD",600),
    }

    run = st.button("🚀 Analizi Başlat", use_container_width=True)

if run:

    df, matches = fetch_data(
        league_slug,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        min_minutes,
    )

    if df.empty:
        st.error("Veri bulunamadı.")
    else:
        st.success(f"{matches} maç incelendi")

        tabs = st.tabs(["GK","DEF","MID","FWD"])

        for grp, tab in zip(["GK","DEF","MID","FWD"], tabs):
            with tab:
                st.dataframe(
                    df[df["Grup"]==grp].drop(columns=["Grup"]),
                    use_container_width=True
                )
