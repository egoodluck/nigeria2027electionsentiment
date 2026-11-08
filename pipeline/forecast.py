"""
Projections -- explicitly *not* predictions -- of daily net sentiment and
discussion volume per candidate, 30 days ahead, with 80% and 95% intervals.

Method (statsmodels, free):
  * net sentiment  : ETS, additive error, additive damped trend, no season,
                     fitted on the daily net-sentiment series (days with fewer
                     than FORECAST_MIN_DAILY_N mentions are treated as missing
                     and linearly interpolated, max gap 3 days).
  * volume         : ETS on log1p(daily mentions) with a 7-day additive season
                     when >= 3 weeks of history exist; intervals back-transformed.
  * fallbacks      : ARIMA(1,0,0) if ETS fails to converge; a naive
                     mean +/- 1.96*sd band if the series is too short/flat.

Every stored row carries `method` and `history_days` so the dashboard can show
how the number was produced. The intervals describe the statistical range of
the fitted model under "nothing changes"; they say nothing about events,
campaigns or the election outcome.
"""

import datetime as dt
import warnings

import numpy as np
import pandas as pd

from pipeline.schema import connect, ensure_schema, log_run
from pipeline.settings import (
    ALL_KEY,
    CANDIDATE_ORDER,
    DB_PATH,
    FORECAST_HORIZON_DAYS,
    FORECAST_MIN_DAILY_N,
    FORECAST_MIN_HISTORY_DAYS,
    MATURITY_DAYS,
)

warnings.filterwarnings("ignore")


def mature_cutoff(conn):
    """Last day whose comment counts can be considered complete."""
    row = conn.execute("SELECT MAX(fetched_at) FROM comments").fetchone()
    if not row or not row[0]:
        return None
    last_fetch = pd.to_datetime(row[0], utc=True, errors="coerce")
    if pd.isna(last_fetch):
        return None
    return (last_fetch - pd.Timedelta(days=MATURITY_DAYS)).strftime("%Y-%m-%d")


def _daily_series(conn, candidate, model):
    cutoff = mature_cutoff(conn)
    df = pd.read_sql_query(
        """SELECT day, SUM(n) n, SUM(n_pos) n_pos, SUM(n_neg) n_neg
           FROM fact_daily WHERE candidate = ? AND model = ? AND (? IS NULL OR day <= ?)
           GROUP BY day ORDER BY day""",
        conn, params=(candidate, model, cutoff, cutoff),
    )
    if df.empty:
        return None
    df["day"] = pd.to_datetime(df["day"])
    idx = pd.date_range(df["day"].min(), df["day"].max(), freq="D")
    df = df.set_index("day").reindex(idx)
    df["n"] = df["n"].fillna(0)
    net = (df["n_pos"] - df["n_neg"]) / df["n"].replace(0, np.nan)
    net[df["n"] < FORECAST_MIN_DAILY_N] = np.nan
    return pd.DataFrame({"n": df["n"], "net": net})


def _ets_forecast(y, steps, seasonal=None):
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    kwargs = dict(error="add", trend="add", damped_trend=True)
    if seasonal:
        kwargs.update(seasonal="add", seasonal_periods=seasonal)
    model = ETSModel(y.astype(float), **kwargs).fit(disp=False, maxiter=200)
    pred = model.get_prediction(start=len(y), end=len(y) + steps - 1)
    f80 = pred.summary_frame(alpha=0.20)
    f95 = pred.summary_frame(alpha=0.05)
    return pd.DataFrame({
        "yhat": f80["mean"].to_numpy(), "lo80": f80["pi_lower"].to_numpy(), "hi80": f80["pi_upper"].to_numpy(),
        "lo95": f95["pi_lower"].to_numpy(), "hi95": f95["pi_upper"].to_numpy(),
    }), f"ETS(A,Ad,{'A7' if seasonal else 'N'})"


def _arima_forecast(y, steps):
    from statsmodels.tsa.arima.model import ARIMA

    model = ARIMA(y.astype(float), order=(1, 0, 0)).fit()
    fc = model.get_forecast(steps)
    ci80 = fc.conf_int(alpha=0.20)
    ci95 = fc.conf_int(alpha=0.05)
    return pd.DataFrame({
        "yhat": fc.predicted_mean.to_numpy(), "lo80": ci80.iloc[:, 0].to_numpy(), "hi80": ci80.iloc[:, 1].to_numpy(),
        "lo95": ci95.iloc[:, 0].to_numpy(), "hi95": ci95.iloc[:, 1].to_numpy(),
    }), "ARIMA(1,0,0)"


def _naive_forecast(y, steps):
    mu, sd = float(np.nanmean(y)), float(np.nanstd(y) or 0.05)
    return pd.DataFrame({
        "yhat": np.repeat(mu, steps), "lo80": np.repeat(mu - 1.28 * sd, steps), "hi80": np.repeat(mu + 1.28 * sd, steps),
        "lo95": np.repeat(mu - 1.96 * sd, steps), "hi95": np.repeat(mu + 1.96 * sd, steps),
    }), "naive mean"


def _forecast(y, steps, seasonal=None):
    y = pd.Series(y).astype(float)
    if y.notna().sum() < FORECAST_MIN_HISTORY_DAYS:
        return None, None
    y = y.interpolate(limit=3, limit_direction="both")
    if y.isna().any():
        y = y.fillna(y.mean())
    for fn, kw in ((_ets_forecast, {"seasonal": seasonal}), (_ets_forecast, {}), (_arima_forecast, {}), (_naive_forecast, {})):
        try:
            out, method = fn(y, steps, **kw) if kw else fn(y, steps)
            if np.isfinite(out.to_numpy()).all():
                return out, method
        except Exception:
            continue
    return None, None


def run(db_path=DB_PATH, models=None, verbose=True):
    ensure_schema(db_path)
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    conn = connect(db_path)
    present = [r[0] for r in conn.execute("SELECT DISTINCT model FROM comment_sentiment").fetchall()]
    models = [m for m in (models or present) if m in present]
    rows = []
    for model in models:
        for cand in CANDIDATE_ORDER + [ALL_KEY]:
            series = _daily_series(conn, cand, model)
            if series is None or len(series) < FORECAST_MIN_HISTORY_DAYS:
                continue
            last_day = series.index.max()
            future = pd.date_range(last_day + pd.Timedelta(days=1), periods=FORECAST_HORIZON_DAYS, freq="D")
            hist_days = int(series["net"].notna().sum())

            fc, method = _forecast(series["net"], FORECAST_HORIZON_DAYS)
            if fc is not None:
                fc = fc.clip(-1, 1)
                for d, r in zip(future, fc.itertuples(index=False)):
                    rows.append((cand, model, "net_sentiment", d.strftime("%Y-%m-%d"), *[round(float(v), 4) for v in r],
                                 method, hist_days, started))

            vol = np.log1p(series["n"])
            seasonal = 7 if len(vol) >= 21 else None
            fc, method = _forecast(vol, FORECAST_HORIZON_DAYS, seasonal=seasonal)
            if fc is not None:
                fc = np.expm1(fc).clip(lower=0)
                for d, r in zip(future, fc.itertuples(index=False)):
                    rows.append((cand, model, "volume", d.strftime("%Y-%m-%d"), *[round(float(v), 2) for v in r],
                                 method, int(len(series)), started))

    conn.execute("DELETE FROM forecasts")
    conn.executemany(
        """INSERT OR REPLACE INTO forecasts
           (candidate, model, metric, day, yhat, lo80, hi80, lo95, hi95, method, history_days, generated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    log_run(conn, "forecast", started, len(rows), f"models={models}")
    conn.commit()
    conn.close()
    if verbose:
        print(f"[forecast] {len(rows)} projection rows for models {models}")
    return len(rows)


if __name__ == "__main__":
    run()
