#!/usr/bin/env python3
"""
Visualisation script for MousePortal simulation (or real session) data.

Reads a per-frame CSV produced by DataLogger and generates a multi-panel
figure showing experiment structure, locomotion dynamics, and the effect
of each velocity transform.

Usage
-----
    python visualize.py data/sub-001-SIM/ses-01/beh/*.csv
    python visualize.py path/to/portal.csv -o figures/
    python visualize.py path/to/portal.csv --no-show    # save only

Outputs
-------
A single PNG figure (and optionally an interactive matplotlib window)
with 6 panels:

1. **Position trace** — camera position over time, shaded by condition.
2. **Velocity comparison** — raw input vs effective (post-transform) velocity.
3. **Gain ratio** — effective / raw velocity, highlighting transform effects.
4. **Trial timeline** — Gantt-style chart of experiment states.
5. **Per-trial summary** — bar chart of distance and duration per trial.
6. **Velocity distributions** — box plots of raw and effective velocity
   grouped by condition.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.axes as mpl_axes
import matplotlib.figure as mpl_figure
import matplotlib.patches as mpatches
import matplotlib.ticker as ticker
import numpy as np

try:
    import pandas as pd
except ImportError:
    print(
        "[visualize] pandas is required.  Install with:\n"
        "    pip install pandas matplotlib",
        file=sys.stderr,
    )
    sys.exit(1)


# ── Colour palette ────────────────────────────────────────────────────────

# Map condition labels → colours.  Falls back to a cycle for unknowns.
_CONDITION_COLORS: Dict[str, str] = {
    "normal":   "#4CAF50",
    "identity": "#4CAF50",
    "freeze":   "#2196F3",
    "gain_2x":  "#FF9800",
    "gain_0.5": "#FFC107",
    "gain_half":"#FFC107",
    "invert":   "#F44336",
    "noisy":    "#9C27B0",
    "offset":   "#00BCD4",
    "delay":    "#795548",
    "clamp":    "#607D8B",
}

_FALLBACK_CYCLE = [
    "#E91E63", "#3F51B5", "#009688", "#CDDC39",
    "#FF5722", "#673AB7", "#8BC34A", "#03A9F4",
]


def _color_for(label: str, idx: int = 0) -> str:
    return _CONDITION_COLORS.get(label, _FALLBACK_CYCLE[idx % len(_FALLBACK_CYCLE)])


_STATE_COLORS: Dict[str, str] = {
    "IDLE":                    "#BDBDBD",
    "BLOCK_START":             "#90CAF9",
    "TRIAL_RUNNING":           "#66BB6A",
    "INTER_TRIAL_INTERVAL":    "#FFEE58",
    "BLOCK_END":               "#CE93D8",
    "SESSION_COMPLETE":        "#EF5350",
}


# ── Data loading & preprocessing ──────────────────────────────────────────


def load_data(csv_path: str) -> pd.DataFrame:
    """Load a MousePortal CSV and add derived columns."""
    df = pd.read_csv(csv_path)

    # Keep only per-frame rows (have a numeric position).
    df = df[df["position"].apply(lambda x: _is_number(x))].copy()
    df["position"] = df["position"].astype(float)
    df["velocity"] = df["velocity"].astype(float)
    df["effective_velocity"] = df["effective_velocity"].astype(float)
    df["timestamp"] = df["timestamp"].astype(float)
    df["frame"] = df["frame"].astype(int)
    df["block"] = df["block"].astype(int)
    df["trial"] = df["trial"].astype(int)

    # Elapsed time from session start.
    t0 = df["timestamp"].iloc[0]
    df["time"] = df["timestamp"] - t0

    # Gain ratio (safe division).
    df["gain_ratio"] = np.where(
        np.abs(df["velocity"]) > 0.01,
        df["effective_velocity"] / df["velocity"],
        np.nan,
    )

    # Unique trial id for grouping.
    df["trial_id"] = df["block"].astype(str) + "-" + df["trial"].astype(str)

    return df


def _is_number(x: Any) -> bool:
    try:
        float(x)
        return True
    except (ValueError, TypeError):
        return False


# ── Per-trial summary ─────────────────────────────────────────────────────


def trial_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-trial statistics."""
    trials = (
        df[df["state"] == "TRIAL_RUNNING"]
        .groupby(["block", "trial", "condition"], sort=False)
        .agg(
            start_time=("time", "first"),
            end_time=("time", "last"),
            start_pos=("position", "first"),
            end_pos=("position", "last"),
            mean_raw_vel=("velocity", "mean"),
            std_raw_vel=("velocity", "std"),
            mean_eff_vel=("effective_velocity", "mean"),
            std_eff_vel=("effective_velocity", "std"),
            n_frames=("frame", "count"),
        )
        .reset_index()
    )
    trials["duration"] = trials["end_time"] - trials["start_time"]
    trials["distance"] = (trials["end_pos"] - trials["start_pos"]).abs()
    trials["trial_id"] = (
        trials["block"].astype(str) + "-" + trials["trial"].astype(str)
    )
    return trials


# ── Plotting ──────────────────────────────────────────────────────────────


def plot_session(df: pd.DataFrame, ts: pd.DataFrame, title: str = "") -> mpl_figure.Figure:
    """Create the 6-panel session overview figure.

    Panels adapt automatically for sessions with many blocks/trials.
    """
    n_blocks = ts["block"].nunique() if not ts.empty else 1
    n_trials = len(ts)
    is_large = n_trials > 16  # switch to dense-friendly layouts

    fig = plt.figure(figsize=(18, 14), facecolor="white")
    fig.suptitle(
        title or "MousePortal — Glitch Experiment Simulation",
        fontsize=15,
        fontweight="bold",
        y=0.98,
    )

    gs = fig.add_gridspec(3, 2, hspace=0.40, wspace=0.30,
                          left=0.07, right=0.96, top=0.93, bottom=0.06)

    ax_pos   = fig.add_subplot(gs[0, 0])
    ax_vel   = fig.add_subplot(gs[0, 1])
    ax_gain  = fig.add_subplot(gs[1, 0])
    ax_tl    = fig.add_subplot(gs[1, 1])
    ax_bars  = fig.add_subplot(gs[2, 0])
    ax_box   = fig.add_subplot(gs[2, 1])

    # -- Assign condition colours ----------------------------------------
    cond_labels = df["condition"].unique()
    cmap = {c: _color_for(c, i) for i, c in enumerate(cond_labels)}

    # ---- Panel 1: per-trial displacement (zeroed per trial) ------------
    _plot_position_trace(ax_pos, df, cmap, is_large)

    # ---- Panel 2: raw vs effective velocity ----------------------------
    _plot_velocity_comparison(ax_vel, df, cmap, is_large)

    # ---- Panel 3: gain ratio strip/box by condition --------------------
    _plot_gain_ratio(ax_gain, df, ts, cmap)

    # ---- Panel 4: experiment state timeline ----------------------------
    _plot_state_timeline(ax_tl, df, ts, cmap, is_large)

    # ---- Panel 5: condition-level summary bars -------------------------
    _plot_trial_bars(ax_bars, ts, cmap, is_large)

    # ---- Panel 6: box plots by condition -------------------------------
    _plot_condition_boxes(ax_box, df, cmap)

    return fig


# ── Individual panel renderers ────────────────────────────────────────────


def _plot_position_trace(ax: mpl_axes.Axes, df: pd.DataFrame, cmap: dict,
                         is_large: bool = False) -> None:
    """Panel 1: per-trial displacement (zeroed at trial start).

    For large sessions, plotting cumulative position squashes most data.
    Instead we show each trial's displacement from its starting position,
    overlaid like a raster — much easier to compare across conditions.
    """
    trial_df = df[df["state"] == "TRIAL_RUNNING"].copy()
    lw = 0.5 if is_large else 0.9
    alpha = 0.55 if is_large else 0.85

    for cond, grp in trial_df.groupby("condition", sort=False):
        for tid, seg in grp.groupby("trial_id", sort=False):
            t0 = seg["time"].iloc[0]
            p0 = seg["position"].iloc[0]
            ax.plot(
                seg["time"].values - t0,
                seg["position"].values - p0,
                color=cmap[cond], linewidth=lw, alpha=alpha,
            )

    ax.set_xlabel("Trial-relative time (s)")
    ax.set_ylabel("Displacement (units)")
    ax.set_title("Per-Trial Displacement", fontweight="bold")
    ax.axhline(0, color="black", linewidth=0.3, linestyle="--")
    _add_condition_legend(ax, cmap)


def _plot_velocity_comparison(ax: mpl_axes.Axes, df: pd.DataFrame, cmap: dict,
                              is_large: bool = False) -> None:
    """Panel 2: raw and effective velocity over session time."""
    trial_df = df[df["state"] == "TRIAL_RUNNING"]
    lw_raw = 0.3 if is_large else 0.5
    lw_eff = 0.4 if is_large else 0.7
    alpha_raw = 0.35 if is_large else 0.6
    alpha_eff = 0.55 if is_large else 0.8

    ax.plot(trial_df["time"], trial_df["velocity"],
            color="#999999", linewidth=lw_raw, alpha=alpha_raw, label="Raw input")
    for cond, grp in trial_df.groupby("condition", sort=False):
        for tid, seg in grp.groupby("trial_id", sort=False):
            ax.plot(seg["time"], seg["effective_velocity"],
                    color=cmap[cond], linewidth=lw_eff, alpha=alpha_eff)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Velocity (units/s)")
    ax.set_title("Raw vs Effective Velocity", fontweight="bold")
    ax.axhline(0, color="black", linewidth=0.4, linestyle="--")

    # Build legend with raw + conditions.
    handles = [mpatches.Patch(color="#999999", label="Raw input")]
    for c, col in cmap.items():
        handles.append(mpatches.Patch(color=col, label=f"{c} (eff)"))
    ax.legend(handles=handles, fontsize=7, loc="upper right", ncol=2)


def _plot_gain_ratio(ax: mpl_axes.Axes, df: pd.DataFrame,
                     ts: pd.DataFrame, cmap: dict) -> None:
    """Panel 3: per-trial mean gain as a strip + box plot by condition.

    Much cleaner than a noisy time-series for large sessions.
    """
    trial_df = df[df["state"] == "TRIAL_RUNNING"].copy()

    # Compute median gain per trial (avoids NaN-heavy raw mean).
    trial_gains = (
        trial_df.groupby(["trial_id", "condition"], sort=False)["gain_ratio"]
        .median()
        .reset_index()
        .rename(columns={"gain_ratio": "med_gain"})
    )

    conditions = list(cmap.keys())
    cond_to_x = {c: i for i, c in enumerate(conditions)}
    n = len(conditions)

    # Box plot of median gains per condition.
    data_per_cond = [
        trial_gains[trial_gains["condition"] == c]["med_gain"].dropna().values
        for c in conditions
    ]
    bp = ax.boxplot(
        data_per_cond,
        positions=np.arange(n),
        widths=0.5,
        patch_artist=True,
        showfliers=False,
        medianprops=dict(color="black", linewidth=1.5),
    )
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(cmap[conditions[i]])
        patch.set_alpha(0.35)

    # Jittered strip of individual trial points.
    rng = np.random.default_rng(0)
    for _, row in trial_gains.iterrows():
        c = row["condition"]
        if c not in cond_to_x or np.isnan(row["med_gain"]):
            continue
        jitter = rng.uniform(-0.15, 0.15)
        ax.plot(
            cond_to_x[c] + jitter, row["med_gain"],
            "o", color=cmap[c], markersize=4, alpha=0.7,
            markeredgecolor="white", markeredgewidth=0.3,
        )

    ax.axhline(1.0, color="black", linewidth=0.6, linestyle="--")
    ax.axhline(0.0, color="#BDBDBD", linewidth=0.5, linestyle=":")
    ax.set_xticks(np.arange(n))
    ax.set_xticklabels(conditions, fontsize=8)
    ax.set_ylabel("Median gain per trial (eff / raw)")
    ax.set_title("Transform Gain by Condition", fontweight="bold")
    # Auto y-limits with a small margin.
    all_vals = trial_gains["med_gain"].dropna()
    if not all_vals.empty:
        lo, hi = all_vals.min(), all_vals.max()
        margin = max(0.5, (hi - lo) * 0.15)
        ax.set_ylim(lo - margin, hi + margin)


def _plot_state_timeline(
    ax: mpl_axes.Axes, df: pd.DataFrame, ts: pd.DataFrame, cmap: dict,
    is_large: bool = False,
) -> None:
    """Panel 4: Gantt-style state timeline.

    For large sessions, uses one row per block and omits per-trial labels
    to prevent overlap.  Block numbers are shown on the y-axis.
    """
    n_blocks = ts["block"].nunique() if not ts.empty else 1
    use_rows = is_large or n_blocks > 4

    runs = _state_runs(df)

    if use_rows:
        # Assign a block number to each run by matching time to trial summary.
        block_starts = ts.groupby("block")["start_time"].min().to_dict()
        block_ends = ts.groupby("block")["end_time"].max().to_dict()
        blocks_sorted = sorted(int(b) for b in block_starts.keys())

        bar_h = 0.7
        for _, run in runs.iterrows():
            # Determine which block this run belongs to.
            blk = blocks_sorted[0]  # fallback
            for b in blocks_sorted:
                bs = block_starts.get(b, 0)
                be = block_ends.get(b, 0)
                if run["start"] >= bs - 0.1 and run["start"] <= be + 5:
                    blk = b
                    break
            y = blk
            colour = _STATE_COLORS.get(run["state"], "#EEEEEE")
            ax.barh(y, run["duration"], left=run["start"],
                    height=bar_h, color=colour, edgecolor="white",
                    linewidth=0.2)

        ax.set_yticks(blocks_sorted)
        ax.set_yticklabels([f"B{b}" for b in blocks_sorted], fontsize=7)
        ax.set_ylabel("Block")
        ax.invert_yaxis()
    else:
        # Original single-row layout for small sessions.
        for _, run in runs.iterrows():
            colour = _STATE_COLORS.get(run["state"], "#EEEEEE")
            ax.barh(0.5, run["duration"], left=run["start"],
                    height=0.4, color=colour, edgecolor="white",
                    linewidth=0.3)
        # Annotate trial labels only when there's room.
        for _, row in ts.iterrows():
            mid = row["start_time"] + row["duration"] / 2
            label = f"B{row['block']}T{row['trial']}\n{row['condition']}"
            ax.text(mid, 0.5, label, ha="center", va="center",
                    fontsize=6, fontweight="bold")
        ax.set_yticks([])
        ax.set_ylim(0, 1)

    ax.set_xlabel("Time (s)")
    ax.set_title("Experiment State Timeline", fontweight="bold")

    handles = [
        mpatches.Patch(color=col, label=st)
        for st, col in _STATE_COLORS.items()
    ]
    ax.legend(handles=handles, fontsize=6, loc="upper right", ncol=3)


def _plot_trial_bars(ax: mpl_axes.Axes, ts: pd.DataFrame, cmap: dict,
                     is_large: bool = False) -> None:
    """Panel 5: condition-level summary (mean ± std) with individual trial dots.

    For small sessions (≤16 trials) falls back to per-trial bars.
    For large sessions aggregates by condition so the chart stays readable.
    """
    if not is_large:
        # --- small-session: per-trial bars (original) ---
        n = len(ts)
        x = np.arange(n)
        width = 0.35
        colors = [cmap.get(c, "#999999") for c in ts["condition"]]
        ax.bar(x - width / 2, ts["distance"], width,
               color=colors, alpha=0.85)
        ax2 = ax.twinx()
        ax2.bar(x + width / 2, ts["duration"], width,
                color=colors, alpha=0.4, edgecolor="black", linewidth=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(
            [f"B{r.block}T{r.trial}\n{r.condition}" for r in ts.itertuples()],
            fontsize=7, rotation=0, ha="center",
        )
        ax.set_ylabel("Distance (units)", color="#333333")
        ax2.set_ylabel("Duration (s)", color="#888888")
        ax.set_title("Per-Trial Distance & Duration", fontweight="bold")
        h1 = mpatches.Patch(facecolor="#666666", alpha=0.85, label="Distance")
        h2 = mpatches.Patch(facecolor="#666666", alpha=0.4, edgecolor="black",
                            linewidth=0.6, label="Duration")
        ax.legend(handles=[h1, h2], fontsize=7, loc="upper left")
        return

    # --- large-session: condition-level summary ---
    conditions = list(cmap.keys())
    cond_agg = (
        ts.groupby("condition")
        .agg(
            mean_dist=("distance", "mean"),
            std_dist=("distance", "std"),
            mean_dur=("duration", "mean"),
            std_dur=("duration", "std"),
        )
        .reindex(conditions)
    )
    cond_agg = cond_agg.fillna(0)
    n = len(conditions)
    x = np.arange(n)
    width = 0.32
    colors = [cmap[c] for c in conditions]

    ax.bar(
        x - width / 2, cond_agg["mean_dist"], width,
        yerr=cond_agg["std_dist"], capsize=3,
        color=colors, alpha=0.85, edgecolor="white", linewidth=0.5,
    )
    ax2 = ax.twinx()
    ax2.bar(
        x + width / 2, cond_agg["mean_dur"], width,
        yerr=cond_agg["std_dur"], capsize=3,
        color=colors, alpha=0.35, edgecolor="black", linewidth=0.5,
    )

    # Overlay individual trial dots.
    rng = np.random.default_rng(1)
    for _, row in ts.iterrows():
        c = row["condition"]
        if c not in cmap:
            continue
        ci = conditions.index(c)
        jitter = rng.uniform(-0.08, 0.08)
        ax.plot(ci - width / 2 + jitter, row["distance"],
                "o", color="black", markersize=3, alpha=0.5)
        ax2.plot(ci + width / 2 + jitter, row["duration"],
                 "o", color="black", markersize=3, alpha=0.35)

    ax.set_xticks(x)
    ax.set_xticklabels(conditions, fontsize=9)
    ax.set_ylabel("Distance (units)", color="#333333")
    ax2.set_ylabel("Duration (s)", color="#888888")
    ax.set_title("Condition Summary (mean ± std)", fontweight="bold")

    h1 = mpatches.Patch(facecolor="#666666", alpha=0.85, label="Distance")
    h2 = mpatches.Patch(facecolor="#666666", alpha=0.35, edgecolor="black",
                        linewidth=0.6, label="Duration")
    ax.legend(handles=[h1, h2], fontsize=7, loc="upper left")


def _plot_condition_boxes(ax: mpl_axes.Axes, df: pd.DataFrame, cmap: dict) -> None:
    """Panel 6: velocity distributions by condition."""
    trial_df = df[df["state"] == "TRIAL_RUNNING"]
    conditions = trial_df["condition"].unique()
    n = len(conditions)

    data_raw = [trial_df[trial_df["condition"] == c]["velocity"].values for c in conditions]
    data_eff = [trial_df[trial_df["condition"] == c]["effective_velocity"].values for c in conditions]

    positions_raw = np.arange(n) * 2
    positions_eff = positions_raw + 0.7

    bp_raw = ax.boxplot(
        data_raw, positions=positions_raw, widths=0.55,
        patch_artist=True, showfliers=False,
        medianprops=dict(color="black"),
    )
    for i, patch in enumerate(bp_raw["boxes"]):
        patch.set_facecolor("#DDDDDD")
        patch.set_alpha(0.7)

    bp_eff = ax.boxplot(
        data_eff, positions=positions_eff, widths=0.55,
        patch_artist=True, showfliers=False,
        medianprops=dict(color="black"),
    )
    for i, patch in enumerate(bp_eff["boxes"]):
        patch.set_facecolor(cmap.get(conditions[i], "#999999"))
        patch.set_alpha(0.75)

    ax.set_xticks(positions_raw + 0.35)
    ax.set_xticklabels(conditions, fontsize=8)
    ax.set_ylabel("Velocity (units/s)")
    ax.set_title("Velocity Distributions by Condition", fontweight="bold")
    ax.axhline(0, color="black", linewidth=0.3, linestyle="--")

    h_raw = mpatches.Patch(facecolor="#DDDDDD", edgecolor="black", label="Raw input")
    h_eff = mpatches.Patch(facecolor="#66BB6A", edgecolor="black", label="Effective")
    ax.legend(handles=[h_raw, h_eff], fontsize=7, loc="upper right")


# ── Helpers ───────────────────────────────────────────────────────────────


def _state_runs(df: pd.DataFrame) -> pd.DataFrame:
    """Find contiguous runs of the same experiment state."""
    change = df["state"] != df["state"].shift()
    group = change.cumsum()
    runs = (
        df.groupby(group)
        .agg(
            state=("state", "first"),
            start=("time", "first"),
            end=("time", "last"),
        )
        .reset_index(drop=True)
    )
    runs["duration"] = runs["end"] - runs["start"]
    return runs


def _add_condition_legend(ax: mpl_axes.Axes, cmap: dict) -> None:
    handles = [mpatches.Patch(color=col, label=cond) for cond, col in cmap.items()]
    ax.legend(handles=handles, fontsize=7, loc="upper left", ncol=2)


# ── Print summary table ──────────────────────────────────────────────────


def print_summary(ts: pd.DataFrame) -> None:
    """Print a text summary of per-trial metrics."""
    hdr = (
        f"{'Trial':<8} {'Cond':<12} {'Dist':>8} {'Dur (s)':>8} "
        f"{'MeanRawV':>10} {'MeanEffV':>10} {'StdRawV':>10}"
    )
    print("\n" + "=" * len(hdr))
    print("  Per-Trial Summary")
    print("=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))
    for row in ts.itertuples():
        tid = f"B{row.block}T{row.trial}"
        print(
            f"{tid:<8} {row.condition:<12} {row.distance:>8.1f} {row.duration:>8.1f} "
            f"{row.mean_raw_vel:>10.2f} {row.mean_eff_vel:>10.2f} {row.std_raw_vel:>10.2f}"
        )
    print("-" * len(hdr))

    # Condition-level aggregates.
    cond_agg = ts.groupby("condition").agg(
        n_trials=("duration", "count"),
        mean_dist=("distance", "mean"),
        mean_dur=("duration", "mean"),
        mean_raw=("mean_raw_vel", "mean"),
        mean_eff=("mean_eff_vel", "mean"),
    )
    print("\n  Condition Averages")
    print("-" * len(hdr))
    for cond, row in cond_agg.iterrows():
        print(
            f"  {cond:<12}  trials={int(row.n_trials)}  "
            f"dist={row.mean_dist:.1f}  dur={row.mean_dur:.1f}s  "
            f"raw_v={row.mean_raw:.2f}  eff_v={row.mean_eff:.2f}"
        )
    print("=" * len(hdr) + "\n")


# ── CLI entry point ───────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visualise MousePortal simulation / session data",
    )
    parser.add_argument(
        "csv",
        help="Path to the per-frame CSV file",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="Directory to save the figure (default: same dir as CSV)",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save figure without showing the interactive window",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Figure DPI for saved PNG (default: 200)",
    )
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.isfile(csv_path):
        print(f"[visualize] File not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[visualize] Loading: {csv_path}")
    df = load_data(csv_path)
    print(f"[visualize] Loaded {len(df)} frames")

    ts = trial_summary(df)
    print_summary(ts)

    fig = plot_session(df, ts, title=f"MousePortal — {Path(csv_path).stem}")

    # Save figure.
    out_dir = args.output_dir or os.path.dirname(csv_path) or "."
    os.makedirs(out_dir, exist_ok=True)
    stem = Path(csv_path).stem
    fig_path = os.path.join(out_dir, f"{stem}_analysis.png")
    fig.savefig(fig_path, dpi=args.dpi, bbox_inches="tight")
    print(f"[visualize] Figure saved: {fig_path}")

    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
