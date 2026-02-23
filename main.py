import requests
from datetime import datetime, timedelta

HEADERS = {"User-Agent": "Mozilla/5.0"}

# =====================================================
# ✅ AYARLAR - SADECE BURAYI DEĞİŞTİR
# =====================================================

LIG = "Süper Lig"       # Sadece isim olarak yaz, aşağıdan eşleşiyor

BASLANGIC_TARIHI = "2025-09-01"
BITIS_TARIHI     = "2026-01-01"

KALECI_SAYISI    = 5
DEFANS_SAYISI    = 20
ORTA_SAHA_SAYISI = 20
FORVET_SAYISI    = 15

KALECI_MIN_DAK    = 900
DEFANS_MIN_DAK    = 900
ORTA_SAHA_MIN_DAK = 900
FORVET_MIN_DAK    = 600

# =====================================================
# LİG LİSTESİ
# =====================================================

LIGLER = {
    "Süper Lig":      52,
    "Premier League": 17,
    "LaLiga":          8,
    "Serie A":        23,
    "Bundesliga":     35,
    "Ligue 1":        34,
}

TOURNAMENT_ID = LIGLER.get(LIG)
if not TOURNAMENT_ID:
    print(f"HATA: '{LIG}' adında bir lig bulunamadı. Şu liglerden birini yaz:")
    for l in LIGLER:
        print(f"  - {l}")
    exit()

# =====================================================
# YARDIMCI FONKSİYONLAR
# =====================================================

def daterange(start, end):
    d1 = datetime.strptime(start, "%Y-%m-%d")
    d2 = datetime.strptime(end, "%Y-%m-%d")
    while d1 <= d2:
        yield d1.strftime("%Y-%m-%d")
        d1 += timedelta(days=1)

def is_target_league(ev):
    tournament = ev.get("tournament", {})
    unique = tournament.get("uniqueTournament", {})
    return unique.get("id") == TOURNAMENT_ID

def group_pos(pos):
    p = (pos or "").upper()
    if p.startswith("G"): return "GK"
    if p.startswith("D"): return "DEF"
    if p.startswith("M"): return "MID"
    return "FWD"

# =====================================================
# VERİ ÇEKME
# =====================================================

print(f"\n{'='*60}")
print(f"  {LIG} - Oyuncu Analizi")
print(f"  {BASLANGIC_TARIHI}  ->  {BITIS_TARIHI}")
print(f"{'='*60}\n")

players = {}

def ensure_player(name):
    if name not in players:
        players[name] = {"team": "", "pos": "", "ratings": [], "minutes": 0, "match_ids": set()}
    return players[name]

total_matches = 0

for date in daterange(BASLANGIC_TARIHI, BITIS_TARIHI):
    print(f"Tarih taranıyor: {date}")

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
        if not is_target_league(ev):
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
        home_team = ev["homeTeam"]["name"]
        away_team = ev["awayTeam"]["name"]

        for side in ("home", "away"):
            team_name = home_team if side == "home" else away_team
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

# =====================================================
# SIRALAMA
# =====================================================

MIN_DAK = {"GK": KALECI_MIN_DAK, "DEF": DEFANS_MIN_DAK, "MID": ORTA_SAHA_MIN_DAK, "FWD": FORVET_MIN_DAK}

final = []
for name, rec in players.items():
    grp = group_pos(rec["pos"])
    if rec["minutes"] < MIN_DAK[grp]:
        continue
    avg = sum(rec["ratings"]) / len(rec["ratings"])
    final.append([name, rec["team"], rec["pos"], grp, avg, rec["minutes"], len(rec["match_ids"])])

final.sort(key=lambda x: x[4], reverse=True)

gk = [r for r in final if r[3] == "GK"][:KALECI_SAYISI]
df = [r for r in final if r[3] == "DEF"][:DEFANS_SAYISI]
md = [r for r in final if r[3] == "MID"][:ORTA_SAHA_SAYISI]
fw = [r for r in final if r[3] == "FWD"][:FORVET_SAYISI]

# =====================================================
# YAZDIRMA
# =====================================================

def table(title, data):
    print("\n" + "="*100)
    print(title.center(100))
    print("="*100)
    print(f"{'OYUNCU':<28}{'TAKIM':<24}{'MEVKI':<8}{'RATING':>10}{'DAKIKA':>10}{'MAC':>8}")
    print("-"*100)
    for i, r in enumerate(data, 1):
        print(f"{i:<3}{r[0][:27]:<28}{r[1][:23]:<24}{r[2]:<8}{r[4]:>10.2f}{r[5]:>10}{r[6]:>8}")

print(f"\nToplam mac analiz edildi: {total_matches}")
print(f"Listeye giren oyuncu: {len(final)}")

table("EN IYI KALECILER", gk)
table("EN IYI DEFANS OYUNCULARI", df)
table("EN IYI ORTA SAHA OYUNCULARI", md)
table("EN IYI FORVETLER", fw)
