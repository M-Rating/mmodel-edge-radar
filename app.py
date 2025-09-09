import os
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

# ===== CONFIG =====
st.set_page_config(page_title="M Model — Live Edge Radar", layout="wide")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

# ===== UTILITIES =====
def american_to_prob(odds: int) -> float:
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)

def implied_from_book(bookmakers, home_name, away_name):
    for book in bookmakers or []:
        for market in book.get("markets", []):
            if market.get("key") == "h2h":
                home_odds, away_odds = None, None
                for outcome in market.get("outcomes", []):
                    if outcome.get("name") == home_name:
                        home_odds = outcome.get("price")
                    elif outcome.get("name") == away_name:
                        away_odds = outcome.get("price")
                if home_odds is not None and away_odds is not None:
                    return american_to_prob(home_odds), american_to_prob(away_odds)
    return None, None

def get_market_odds_ncaab():
    if not ODDS_API_KEY:
        return {}
    url = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "us", "markets": "h2h", "oddsFormat": "american"}
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        st.warning(f"Odds fetch failed: {e}")
        return {}
    odds_map = {}
    for game in data:
        home = game.get("home_team")
        away = game.get("away_team")
        if not home or not away:
            continue
        home_prob, away_prob = implied_from_book(game.get("bookmakers"), home, away)
        if home_prob is None or away_prob is None:
            continue
        matchup = f"{away} @ {home}"
        odds_map[matchup] = {
            "home_implied_prob": home_prob,
            "away_implied_prob": away_prob,
            "home_team": home,
            "away_team": away
        }
    return odds_map

# ===== YOUR DATA HOOKS (works now; swap later for your real data) =====
def load_ratings():
    return pd.DataFrame([
        {"team": "Dayton", "elo": 1600},
        {"team": "Gonzaga", "elo": 1720},
        {"team": "Duke", "elo": 1700},
        {"team": "Kansas", "elo": 1710},
        {"team": "Arizona", "elo": 1695},
        {"team": "Baylor", "elo": 1680}
    ])

def get_todays_games():
    # Format: list of (away_team, home_team)
    return [("Dayton", "Kansas"), ("Duke", "Arizona"), ("Baylor", "Gonzaga")]

def predict_win_prob(team_a, team_b, ratings_df, neutral=False):
    def elo(t):
        s = ratings_df.loc[ratings_df["team"] == t, "elo"]
        return float(s.values[0]) if not s.empty else 1500.0
    ra, rb = elo(team_a), elo(team_b)
    if not neutral:
        rb += 50  # home edge
    return 1 / (1 + 10 ** ((rb - ra) / 400))

# ===== FAN BIAS =====
def apply_fan_bias(ratings_df, team_name="Dayton", boost_points=0):
    r = ratings_df.copy()
    if boost_points != 0:
        r.loc[r["team"] == team_name, "elo"] += boost_points
    return r

# ===== EDGE FINDERS =====
def build_predictions_df(adjusted_ratings, odds_map, games):
    rows = []
    for away, home in games:
        matchup = f"{away} @ {home}"
        model_home_prob = 1 - predict_win_prob(away, home, adjusted_ratings, neutral=False)
        market_home_prob = odds_map.get(matchup, {}).get("home_implied_prob", None)
        if market_home_prob is None:
            continue
        edge = (model_home_prob - market_home_prob) * 100
        rows.append({
            "matchup": matchup,
            "home_team": home,
            "away_team": away,
            "model_home_win%": round(model_home_prob * 100, 1),
            "market_home_win%": round(market_home_prob * 100, 1),
            "edge%": round(edge, 1)
        })
    return pd.DataFrame(rows)

def filter_high_value_underdogs(preds_df, threshold_pct):
    if preds_df.empty:
        return preds_df
    df = preds_df.copy()
    dogs = df[df["market_home_win%"] < 50]
    dogs = dogs[(dogs["model_home_win%"] - dogs["market_home_win%"]) >= threshold_pct]
    return dogs.sort_values("edge%", ascending=False)

# ===== UI =====
st.title("M Model — Live Edge Radar")
with st.sidebar:
    st.header("Controls")
    flyers_boost = st.slider("Flyers Boost (Elo points)", 0, 10, 0, 1)
    threshold = st.slider("Minimum edge to highlight (%)", 0, 20, 5, 1)
    if ODDS_API_KEY:
        st.success("Odds API key detected.")
    else:
        st.warning("No Odds API key found. Set ODDS_API_KEY in Secrets to enable live edges.")

# Load data
base_ratings = load_ratings()
ratings = apply_fan_bias(base_ratings, "Dayton", flyers_boost)
odds_map = get_market_odds_ncaab() if ODDS_API_KEY else {}
games = get_todays_games()
preds_df = build_predictions_df(ratings, odds_map, games)

# Tabs
tab1, tab2 = st.tabs(["Upset Radar", "High-Value Underdogs"])
with tab1:
    st.subheader("📊 Model vs. Market — Full Slate")
    if preds_df.empty:
        st.info("No predictions available.")
    else:
        df = preds_df.sort_values("edge%", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
        if not df.empty:
            fig = px.bar(df, x="matchup", y="edge%", color="edge%", title="Edge % by Matchup")
            fig.update_layout(xaxis_title="", yaxis_title="Edge % (Model - Market)")
            st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("🐾 High-Value Underdogs")
    if preds_df.empty:
        st.info("No predictions available.")
    else:
        dogs = filter_high_value_underdogs(preds_df, threshold)
        if dogs.empty:
            st.info("No underdogs above threshold.")
        else:
            st.dataframe(dogs, use_container_width=True, hide_index=True)
