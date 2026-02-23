import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Cache-Control": "no-cache",
}

LIGLER = {
    "Süper Lig": 52,
    "Premier League": 17,
    "LaLiga": 8,
    "Serie A": 23,
    "Bundesliga": 35,
    "Ligue 1": 34,
}

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

def fetch_data(tournament_id, start_date, end_date, min_minutes, progress_bar, status_text):
    players = {}
    def ensure_player(name):
        if name not in players:
            players[name] = {"team": "", "pos": "", "ratings": [], "minutes": 0, "match_ids": set()}
        return players[name]
    dates = list(daterange(start_date, end_date))
    total_matches = 0
    for i, date in enumerate(dates):
        progress_bar.progress((i + 1) / len(dates))
        status_text.text(f"Tarih taranıyor: {date}")
        try:
            r = requests.get(
                f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date}",
                headers=HEADERS, timeout=20
            )
        except:
            continue
        if r.status_code != 200:
            continue
        for ev in r.json().get("events", []):
            if ev.get("tournament", {}).get("uniqueTournament", {}).get("id") != tournament_id:
                continue
            match_id = ev.get("id")
            if not match_id:
                continue
            total_matches += 1
            try:
                lr = requests.get(
                    f"https://api.sofascore.com/api/v1/event/{match_id}/lineups",
                    headers=HEADERS, timeout=20
                )
            except:
                continue
            if lr.status_code != 200:
                continue
            lineup = lr.json()
            for side in ("home", "away"):
                team_name = ev["homeTeam"]["name"] if side == "home" else ev["awayTeam"]["name"]
                for pl in lineup.get(side, {}).get("players", []):
                    name = pl.get("player", {}).get("name")
                    if not name:
                        continue
                    stats = pl.get("statistics", {})
                    rating = stats.get("rating")
                    if rating is None:
                        continue
                    try:
                        minutes = max(0, min(int(stats.get("minutesPlayed", 0)), 130))
                    except:
                        minutes = 0
                    rec = ensure_player(name)
                    if match_id in rec["match_ids"]:
                        continue
                    rec["match_ids"].add(match_id)
                    rec["team"] = team_name
                    rec["ratings"].append(float(rating))
                    rec["minutes"] += minutes
                    pos = pl.get("position")
                    if pos:
                        rec["pos"] = pos
    final = []
    for name, rec in players.items():
        grp = group_pos(rec["pos"])
        if rec["minutes"] < min_minutes.get(grp, 0):
            continue
        avg = sum(rec["ratings"]) / len(rec["ratings"])
        final.append({
            "Oyuncu": name,
            "Takım": rec["team"],
            "Mevki": rec["pos"],
            "Grup": grp,
            "Ort. Rating": round(avg, 2),
            "Dakika": rec["minutes"],
            "Maç": len(rec["match_ids"])
        })
    final.sort(key=lambda x: x["Ort. Rating"], reverse=True)
    return final, total_matches

st.set_page_config(page_title="Futbol Scouting", page_icon="⚽", layout="wide")
st.title("⚽ Futbol Oyuncu Analiz Aracı")

with st.sidebar:
    st.header("⚙️ Ayarlar")
    league_name = st.selectbox("Lig", list(LIGLER.keys()))
    tournament_id = LIGLER[league_name]
    st.subheader("📅 Tarih Aralığı")
    start_date = st.date_input("Başlangıç", value=datetime(2025, 9, 1))
    end_date = st.date_input("Bitiş", value=datetime(2026, 1, 1))
    st.subheader("👥 Gösterilecek Oyuncu Sayısı")
    limit_gk = st.slider("Kaleci", 1, 10, 5)
    limit_def = st.slider("Defans", 1, 30, 20)
    limit_mid = st.slider("Orta Saha", 1, 30, 20)
    limit_fwd = st.slider("Forvet", 1, 20, 15)
    st.subheader("⏱️ Minimum Dakika")
    min_gk = st.number_input("Kaleci min. dakika", value=900, step=100)
    min_def = st.number_input("Defans min. dakika", value=900, step=100)
    min_mid = st.number_input("Orta Saha min. dakika", value=900, step=100)
    min_fwd = st.number_input("Forvet min. dakika", value=600, step=100)
    run = st.button("🚀 Analizi Başlat", use_container_width=True)

if run:
    st.info(f"{league_name} için veri çekiliyor...")
    progress_bar = st.progress(0)
    status_text = st.empty()
    min_minutes = {"GK": min_gk, "DEF": min_def, "MID": min_mid, "FWD": min_fwd}
    data, total_matches = fetch_data(
        tournament_id,
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
        min_minutes,
        progress_bar,
        status_text
    )
    progress_bar.empty()
    status_text.empty()
    if not data:
        st.error("Veri bulunamadı. Tarih aralığını veya lig seçimini kontrol et.")
    else:
        st.success(f"✅ {total_matches} maç incelendi, {len(data)} oyuncu listelendi.")
        df = pd.DataFrame(data)
        tabs = st.tabs(["🥅 Kaleciler", "🛡️ Defans", "⚙️ Orta Saha", "⚡ Forvet"])
        for (grp, limit, tab) in [
            ("GK", limit_gk, tabs[0]),
            ("DEF", limit_def, tabs[1]),
            ("MID", limit_mid, tabs[2]),
            ("FWD", limit_fwd, tabs[3])
        ]:
            with tab:
                filtered = df[df["Grup"] == grp].head(limit).reset_index(drop=True)
                filtered.index += 1
                st.dataframe(filtered.drop(columns=["Grup"]), use_container_width=True)
                st.download_button(
                    f"📥 CSV İndir ({grp})",
                    filtered.to_csv(index=False).encode("utf-8"),
                    f"{league_name}_{grp}.csv",
                    "text/csv"
                )
else:
    st.markdown("👈 **Sol panelden ayarları yap ve 'Analizi Başlat' butonuna bas.**")
