"""Offline RL sleeve trainer (TensorTrade research track).

Run inside the py3.12 conda env (TensorFlow does NOT support py3.13):

    conda activate tensortrade
    python integrations/rl_tensortrade/train_rl_sleeve.py

Outputs data/rl_sleeve/rl_tensortrade_returns.csv consumed by the live
dashboard as the `rl_tensortrade` research tab. Never wired into PROD or
the $1M Equal-Weight Index.

Part 1 smoke-tests the TensorTrade env API (boss request: "test them").
Part 2 trains a tabular Q-learning agent on DOGE daily features and
exports walk-forward OOS daily returns net of 5 bps/leg TC.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DOGE_CSV = REPO / "data" / "qlib_crypto" / "DOGE.csv"
OUT_CSV = REPO / "data" / "rl_sleeve" / "rl_tensortrade_returns.csv"
FEE_PER_LEG = 5 / 10_000


def smoke_test_tensortrade(close: pd.Series) -> bool:
    """Build a minimal TensorTrade env and step it with random actions."""
    try:
        import tensortrade.env.default as default
        from tensortrade.feed.core import DataFeed, Stream
        from tensortrade.oms.exchanges import Exchange
        from tensortrade.oms.instruments import USD, Instrument
        from tensortrade.oms.services.execution.simulated import execute_order
        from tensortrade.oms.wallets import Portfolio, Wallet
    except Exception as exc:
        print(f"[smoke] tensortrade import failed: {exc}")
        return False

    try:
        DOGE = Instrument("DOGE", 8, "Dogecoin")
        # USD has 2-decimal precision; sub-cent meme prices quantize to 0 → scale up.
        scaled = (close * 10_000).tolist()
        price_stream = Stream.source(scaled, dtype="float").rename("USD-DOGE")
        exchange = Exchange("sim", service=execute_order)(price_stream)
        portfolio = Portfolio(
            USD,
            [Wallet(exchange, 10_000 * USD), Wallet(exchange, 0 * DOGE)],
        )
        feed = DataFeed(
            [Stream.source(close.pct_change().fillna(0).tolist(), dtype="float").rename("ret")]
        )
        env = default.create(
            portfolio=portfolio,
            action_scheme="simple",
            reward_scheme="simple",
            feed=feed,
            window_size=5,
        )
        obs, _ = env.reset() if isinstance(env.reset(), tuple) else (env.reset(), None)
        steps = 0
        for _ in range(20):
            action = env.action_space.sample()
            result = env.step(action)
            steps += 1
            done = result[2] if len(result) >= 3 else False
            if done:
                break
        print(f"[smoke] TensorTrade env OK — {steps} steps, action_space={env.action_space}")
        return True
    except Exception as exc:
        print(f"[smoke] tensortrade env failed: {exc}")
        return False


def _discretize(mom: float, vol: float, rsi: float) -> tuple[int, int, int]:
    m = 0 if mom < -0.05 else (2 if mom > 0.05 else 1)
    v = 0 if vol < 0.05 else (2 if vol > 0.09 else 1)
    r = 0 if rsi < 40 else (2 if rsi > 60 else 1)
    return m, v, r


def train_q_learning(df: pd.DataFrame, train_frac: float = 0.7, seed: int = 7) -> pd.Series:
    """Tabular Q-learning on (MOM20, VOL20, RSI14) grid; actions {-1, 0, +1}.

    OOS returns only (post-train split), net of TC on position changes.
    """
    rng = np.random.default_rng(seed)
    states = df.apply(lambda row: _discretize(row["MOM20"], row["VOL20"], row["RSI14"]), axis=1)
    rets = df["RET1"].shift(-1).fillna(0).to_numpy()  # next-day return as reward base

    n_train = int(len(df) * train_frac)
    actions = np.array([-1.0, 0.0, 1.0])
    q: dict[tuple, np.ndarray] = {}
    alpha, gamma, eps = 0.1, 0.9, 0.2

    for epoch in range(30):
        pos = 0.0
        for i in range(n_train - 1):
            s = states.iloc[i]
            q.setdefault(s, np.zeros(3))
            a_idx = rng.integers(3) if rng.random() < eps else int(np.argmax(q[s]))
            a = actions[a_idx]
            tc = FEE_PER_LEG if a != pos else 0.0
            reward = a * rets[i] - tc
            s_next = states.iloc[i + 1]
            q.setdefault(s_next, np.zeros(3))
            q[s][a_idx] += alpha * (reward + gamma * q[s_next].max() - q[s][a_idx])
            pos = a
        eps = max(0.02, eps * 0.9)

    # OOS rollout with greedy policy
    oos_idx = df.index[n_train:]
    pos = 0.0
    out = []
    for i in range(n_train, len(df)):
        s = states.iloc[i]
        a = actions[int(np.argmax(q.get(s, np.zeros(3))))]
        tc = FEE_PER_LEG if a != pos else 0.0
        out.append(a * rets[i] - tc)
        pos = a
    return pd.Series(out, index=oos_idx, name="rl_tensortrade")


def main() -> int:
    if not DOGE_CSV.exists():
        print(f"missing {DOGE_CSV}")
        return 1
    df = pd.read_csv(DOGE_CSV, parse_dates=["datetime"]).set_index("datetime").dropna()
    print(f"[data] DOGE {len(df)} rows {df.index.min().date()} → {df.index.max().date()}")

    ok = smoke_test_tensortrade(df["close"])
    print(f"[smoke] result: {'PASS' if ok else 'FAIL (see above)'}")

    oos = train_q_learning(df)
    sh = oos.mean() / oos.std() * np.sqrt(252) if oos.std() > 0 else 0.0
    cum = float((1 + oos).prod() - 1)
    print(f"[train] OOS days={len(oos)} sharpe={sh:.2f} cum={cum:.2%}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    oos.to_frame().assign(date=oos.index.strftime("%Y-%m-%d")).reset_index(drop=True)[
        ["date", "rl_tensortrade"]
    ].to_csv(OUT_CSV, index=False)
    print(f"[out] wrote {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
