import streamlit as st
import pandas as pd
import json
import glob
from datetime import datetime

# -------------------
# CONFIG
# -------------------
SNAPSHOT_DIR = "snapshots"
SNAPSHOT_DEFAULT_SEASON = 2025
NCAA_SEASON_START_MM_DD = "11-01"
NCAA_SEASON_END_MM_DD = "04-15"
ROUND_POINTS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16, 6: 32}

# -------------------
# HELPERS
# -------------------
def is_ncaa_in_season(today=None):
    today = today or datetime.today()
    y = today.year
    start = datetime.strptime(f"{y}-{NCAA_SEASON_START_MM_DD}", "%Y-%m-%d")
    if today.month >= 11:
        end = datetime.strptime(f"{y+1}-{NCAA_SEASON_END_MM_DD}", "%Y-%m-%d")
    else:
        end = datetime.strptime(f"{y}-{NCAA_SEASON_END_MM_DD}", "%Y-%m-%d")
    return start <= today <= end

def get_latest_snapshot_path():
    files = sorted(glob.glob(f"{SNAPSHOT_DIR}/*_selection_sunday.json"))
    if files:
        return files[-1]
    return f"{SNAPSHOT_DIR}/{SNAPSHOT_DEFAULT_SEASON}_selection_sunday.json"

def load_snapshot(path: str):
    with open(path, "r") as f:
        data = json.load(f)
    teams_df = pd.DataFrame(data.get("teams", []))
    bracket_df = pd.DataFrame(data.get("bracket", []))
    odds_df = pd.DataFrame(data.get("odds", []))
    results_df = pd.DataFrame(data.get("results", []))
    return data.get("meta", {}), teams_df, bracket_df, odds_df, results_df

def snapshot_picks_to_brackets(bracket_df: pd.DataFrame):
    pick_cols = ["kenpom_winner", "torvik_winner", "espn_consensus_winner", "cbs_consensus_winner"]
    out = {"m_rating": {}}
    for _, row in bracket_df.iterrows():
        mid = row["matchup_id"]
        out["m_rating"][mid] = row.get("predicted_winner")
        for col in pick_cols:
            if col in bracket_df.columns:
                out.setdefault(col.replace("_winner", ""), {})[mid] = row.get(col)
    return out

def score_brackets(picks: dict, results_df: pd.DataFrame):
    results = {r["matchup_id"]: r["winner_id"] for _, r in results_df.iterrows()} if not results_df.empty else {}
    rounds = {r["matchup_id"]: int(r["round"]) for _, r in results_df.iterrows()} if not results_df.empty else {}
    rows = []
    for name, bracket in picks.items():
        score = 0
        max_possible = 0
        for mid, picked in bracket.items():
            rnd = rounds.get(mid)
            if rnd is None:
                continue
            pts = ROUND_POINTS.get(rnd, 0)
            max_possible += pts
            actual = results.get(mid)
            if actual is not None and picked == actual:
                score += pts
        rows.append({"bracket": name, "score": score, "max_possible": max_possible})
    return pd.DataFrame(rows).sort_values(["score", "max_possible"], ascending=[False, False])

def current_results(results_df: pd.DataFrame):
    base = results_df.copy()
    overrides = st.session_state.whatif_results.copy()
    if overrides.empty:
        return base
    if not base.empty:
        base = base[~base["matchup_id"].isin(overrides["matchup_id"])]
    merged = pd.concat([base, overrides], ignore_index=True)
    return merged

# -------------------
# STREAMLIT APP
# -------------------
st.set_page_config(page_title="M-Rating Bracket Tracker", layout="wide")
st.title("🏀 M-Rating Bracket Tracker & What‑If Simulator")

if "whatif_results" not in st.session_state:
    st.session_state.whatif_results = pd.DataFrame(columns=["matchup_id", "winner_id", "round"])

# Sidebar mode toggle
in_season = is_ncaa_in_season()
default_mode = "Live" if in_season else "Snapshot"
mode = st.sidebar.radio("Mode", options=["Live", "Snapshot"], index=0 if default_mode=="Live" else 1)

# Load data
if mode == "Snapshot":
    snap_path = get_latest_snapshot_path()
    meta, teams_df, bracket_df, odds_df, results_df = load_snapshot(snap_path)
    st.caption(f"📦 Off‑season mode: Selection Sunday snapshot {meta.get('snapshot_date', '')} (season {meta.get('season', '')})")
else:
    # Placeholder for live Odds API logic
    meta, teams_df, bracket_df, odds_df, results_df = {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    st.warning("Live mode placeholder — add Odds API fetch here.")

# -------------------
# SNAPSHOT MODE UI
# -------------------
if mode == "Snapshot":
    # What‑If Simulator FIRST
    st.subheader("🔄 What‑If Simulator")
    if not bracket_df.empty:
        round_choices = sorted(bracket_df["round"].unique())
        sel_round = st.selectbox("Round", round_choices)
        subset = bracket_df[bracket_df["round"] == sel_round]

        id_to_name = {r.team_id: r.team_name for _, r in teams_df.rename(columns=str).iterrows()}
        def label(row):
            t1 = id_to_name.get(row["team1_id"], row["team1_id"])
            t2 = id_to_name.get(row["team2_id"], row["team2_id"])
            return f'{row["matchup_id"]}: {t1} vs {t2}'

        match = st.selectbox("Matchup", list(subset["matchup_id"]),
                             format_func=lambda mid: label(subset[subset["matchup_id"]==mid].iloc[0]))
        row = subset[subset["matchup_id"] == match].iloc[0]
        t1, t2 = row["team1_id"], row["team2_id"]
        winner = st.radio("Set winner", options=[t1, t2],
                          format_func=lambda tid: id_to_name.get(tid, tid), horizontal=True)

        if st.button("Apply What‑If"):
            new_row = pd.DataFrame([{"matchup_id": match, "winner_id": winner, "round": int(row["round"])}])
            if not st.session_state.whatif_results.empty and match in st.session_state.whatif_results["matchup_id"].values:
                st.session_state.whatif_results.loc[
                    st.session_state.whatif_results["matchup_id"] == match,
                    ["winner_id", "round"]
                ] = [winner, int(row["round"])]
            else:
                st.session_state.whatif_results = pd.concat(
                    [st.session_state.whatif_results, new_row], ignore_index=True
                )
            st.success("What‑If applied.")

    # Bracket Showdown SECOND
    picks = snapshot_picks_to_brackets(bracket_df)
    res = current_results(results_df)
    leaderboard = score_brackets(picks, res)
    st.subheader("🏆 Bracket Showdown")
    st.dataframe(leaderboard, hide_index=True)

    # Teams table LAST
    with st.expander("📋 Teams list"):
        st.dataframe(teams_df, use_container_width=True)
