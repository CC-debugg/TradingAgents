"""Qlib integration with pandas/sklearn fallback when qlib is not installed."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

QLIB_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "qlib_crypto"

# Human-readable labels for macro factor attribution charts / CSV
MACRO_FACTOR_META: dict[str, dict[str, str]] = {
    "ALPHA": {
        "title": "Alpha (intercept)",
        "proxy": "—",
        "desc": "Return not explained by factors below",
    },
    "MKT": {
        "title": "US equity market",
        "proxy": "SPY",
        "desc": "Broad stock market beta",
    },
    "RATES": {
        "title": "Long rates / bonds",
        "proxy": "TLT",
        "desc": "Duration / rate sensitivity",
    },
    "COMMOD": {
        "title": "Commodities / gold",
        "proxy": "GLD",
        "desc": "Inflation / safe-haven proxy",
    },
    "USD": {
        "title": "US dollar strength",
        "proxy": "UUP",
        "desc": "DXY-style USD factor",
    },
    "CRYPTO": {
        "title": "Crypto / meme beta",
        "proxy": "DOGE-USD",
        "desc": "Meme coin market exposure",
    },
}


def factor_display_name(code: str) -> str:
    """e.g. 'MKT · US equity market (SPY)'."""
    meta = MACRO_FACTOR_META.get(code, {"title": code, "proxy": "?", "desc": ""})
    proxy = meta.get("proxy", "?")
    title = meta.get("title", code)
    if proxy and proxy != "—":
        return f"{code} · {title} ({proxy})"
    return f"{code} · {title}"


def qlib_available() -> bool:
    try:
        import qlib  # noqa: F401

        return True
    except ImportError:
        return False


def build_factor_panel(prices: dict[str, pd.Series], horizon: int = 5) -> pd.DataFrame:
    """Alpha-style factors + forward label for supervised learning."""
    frames = []
    for symbol, close in prices.items():
        if symbol.startswith("POLY_"):
            continue
        px = close.dropna()
        ret = px.pct_change()
        df = pd.DataFrame(
            {
                "symbol": symbol,
                "close": px,
                "RET1": ret,
                "RET5": px.pct_change(5),
                "VOL20": ret.rolling(20).std(),
                "MOM20": px / px.shift(20) - 1,
                "RSI14": _rsi(px, 14),
            },
            index=px.index,
        )
        df["LABEL"] = px.shift(-horizon) / px - 1
        frames.append(df.dropna())
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).reset_index().rename(columns={"index": "datetime"})


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = (-delta.clip(upper=0)).rolling(period).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def export_qlib_csv(panel: pd.DataFrame, out_dir: Path | None = None) -> Path:
    """Write Qlib-friendly long-format CSV per symbol."""
    out_dir = out_dir or QLIB_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for symbol, grp in panel.groupby("symbol"):
        path = out_dir / f"{symbol}.csv"
        export = grp[["datetime", "close", "RET1", "VOL20", "MOM20", "RSI14", "LABEL"]].copy()
        export.to_csv(path, index=False)
    meta = out_dir / "manifest.json"
    meta.write_text(
        json.dumps(
            {
                "symbols": sorted(panel["symbol"].unique().tolist()),
                "rows": len(panel),
                "qlib_init_hint": "pip install pyqlib && qlib.init(provider_uri='data/qlib_crypto', region='cn')",
            },
            indent=2,
        )
    )
    return out_dir


def train_signal_model(panel: pd.DataFrame) -> tuple[object, list[str], str]:
    """
    Train classifier: positive forward return or not.
    Uses Qlib LGBModel if available, else sklearn HistGradientBoosting.
    """
    features = ["RET1", "RET5", "VOL20", "MOM20", "RSI14"]
    df = panel.dropna(subset=features + ["LABEL"]).copy()
    df["y"] = (df["LABEL"] > 0).astype(int)
    X = df[features].values
    y = df["y"].values

    if qlib_available() and len(df) > 200:
        try:
            from qlib.contrib.model.gbdt import LGBModel

            model = LGBModel()
            model.fit(pd.DataFrame(X, columns=features), pd.Series(y))
            return model, features, "qlib.LGBModel"
        except Exception:
            pass

    try:
        from sklearn.ensemble import HistGradientBoostingClassifier

        model = HistGradientBoostingClassifier(max_depth=4, max_iter=80, random_state=42)
        model.fit(X, y)
        return model, features, "sklearn.HistGradientBoostingClassifier"
    except ImportError:
        class MomentumClassifier:
            def predict(self, Xdf):
                col = list(Xdf.columns).index("MOM20")
                return (Xdf.values[:, col] > 0).astype(int)

        model = MomentumClassifier()
        return model, features, "numpy.MOM20_fallback"


def predict_scores(panel: pd.DataFrame, model, features: list[str]) -> pd.Series:
    df = panel.dropna(subset=features).copy()
    if hasattr(model, "predict"):
        try:
            proba = model.predict(df[features])
            if proba.ndim == 1 and set(np.unique(proba)).issubset({0, 1}):
                scores = proba.astype(float)
            else:
                scores = proba
        except Exception:
            scores = model.predict(df[features])
    else:
        scores = model.predict(df[features])
    return pd.Series(scores, index=df["datetime"] if "datetime" in df.columns else df.index)


def factor_attribution(strat_r: pd.Series, macro_returns: pd.DataFrame) -> pd.DataFrame:
    """OLS-style factor attribution (MKT, rates proxy, etc.)."""
    y = strat_r.dropna()
    X = macro_returns.reindex(y.index).dropna(how="all").fillna(0)
    common = y.index.intersection(X.index)
    if len(common) < 30:
        return pd.DataFrame()
    yv = y.loc[common].values
    Xv = X.loc[common].values
    Xd = np.column_stack([np.ones(len(common)), Xv])
    beta, _, _, _ = np.linalg.lstsq(Xd, yv, rcond=None)
    names = ["ALPHA"] + list(X.columns)
    contrib = {}
    for i, name in enumerate(names):
        if name == "ALPHA":
            contrib[name] = beta[i] * 252
        else:
            contrib[name] = beta[i] * X[name].mean() * 252
    out = pd.DataFrame({"factor": names, "beta": beta, "contrib_ann": [contrib[n] for n in names]})
    ss_res = ((yv - Xd @ beta) ** 2).sum()
    ss_tot = ((yv - yv.mean()) ** 2).sum()
    out.attrs["r_squared"] = float(1 - ss_res / ss_tot) if ss_tot else 0.0
    out.attrs["n_obs"] = len(common)
    return out


def render_factor_attribution_chart(
    attr: pd.DataFrame,
    path: str | Path,
    *,
    returns_label: str = "strategy daily returns",
) -> None:
    """Save labeled factor attribution PNG (betas + annualized contrib %)."""
    import matplotlib.pyplot as plt

    if attr.empty:
        return

    path = Path(path)
    r2 = float(attr.attrs.get("r_squared", 0))
    n_obs = int(attr.attrs.get("n_obs", 0))
    plot_df = attr[attr["factor"] != "ALPHA"].copy()
    if plot_df.empty:
        plot_df = attr.copy()

    labels = [factor_display_name(str(f)) for f in plot_df["factor"]]
    betas = plot_df["beta"].astype(float).values
    contribs = (plot_df["contrib_ann"].astype(float).values * 100.0)

    alpha_row = attr[attr["factor"] == "ALPHA"]
    alpha_ann = (
        float(alpha_row["contrib_ann"].iloc[0]) * 100.0 if len(alpha_row) else float("nan")
    )

    plt.style.use("dark_background")
    fig, (ax_b, ax_c) = plt.subplots(1, 2, figsize=(16, 6), facecolor="#0D1117")
    fig.suptitle(
        "Performance Attribution — Macro Factors (not Fama-French)",
        color="white",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )
    fig.text(
        0.5,
        0.93,
        f"Dependent: {returns_label}  ·  n={n_obs} days  ·  "
        f"ALPHA contrib ≈ {alpha_ann:+.2f}%/yr  ·  R² applies to all factors incl. ALPHA",
        ha="center",
        color="#7A8899",
        fontsize=9,
    )

    y_pos = np.arange(len(labels))
    colors_b = ["#00D4FF" if b >= 0 else "#FF4466" for b in betas]
    ax_b.barh(y_pos, betas, color=colors_b, alpha=0.9, height=0.55)
    ax_b.set_yticks(y_pos)
    ax_b.set_yticklabels(labels, fontsize=9, color="white")
    ax_b.axvline(0, color="#7A8899", lw=0.6)
    ax_b.set_xlabel("Beta (exposure)", color="#7A8899", fontsize=9)
    ax_b.set_title(f"Factor Exposures (β)  ·  R²={r2:.2f}", color="white", fontweight="bold")
    ax_b.grid(True, alpha=0.35, axis="x")
    for i, (b, lab) in enumerate(zip(betas, labels)):
        ax_b.text(
            b + (0.002 if b >= 0 else -0.002),
            i,
            f"{b:+.3f}",
            va="center",
            ha="left" if b >= 0 else "right",
            fontsize=8,
            color="white",
        )

    colors_c = ["#00FF88" if c >= 0 else "#FF4466" for c in contribs]
    ax_c.barh(y_pos, contribs, color=colors_c, alpha=0.9, height=0.55)
    ax_c.set_yticks(y_pos)
    ax_c.set_yticklabels(labels, fontsize=9, color="white")
    ax_c.axvline(0, color="#7A8899", lw=0.6)
    ax_c.set_xlabel("Attributed annual return (%)", color="#7A8899", fontsize=9)
    ax_c.set_title("Attributed Annual Return (%)", color="white", fontweight="bold")
    ax_c.grid(True, alpha=0.35, axis="x")
    for i, (c, lab) in enumerate(zip(contribs, labels)):
        ax_c.text(
            c + (0.15 if c >= 0 else -0.15),
            i,
            f"{c:+.2f}%",
            va="center",
            ha="left" if c >= 0 else "right",
            fontsize=8,
            color="white",
        )

    legend_lines = [
        f"{code}: {MACRO_FACTOR_META.get(code, {}).get('desc', '')}"
        for code in plot_df["factor"]
    ]
    fig.text(0.5, 0.02, "  |  ".join(legend_lines), ha="center", color="#7A8899", fontsize=7.5)

    plt.tight_layout(rect=[0, 0.04, 1, 0.90])
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#0D1117")
    plt.close(fig)
