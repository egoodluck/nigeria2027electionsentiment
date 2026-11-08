"""Unit tests for the pure analytics layer and the pipeline text utilities.

    pytest -q
"""
import math

import pandas as pd
import pytest

from app import analytics as an
from attribute_and_score import clean_text, match_candidates, match_parties
from pipeline.features import language_hint, normalise_for_hash, text_hash
from pipeline.locations import states_in
from pipeline.topics import lexicon_topics


def _facts():
    days = pd.date_range("2026-10-01", periods=14, freq="D")
    rows = []
    for i, d in enumerate(days):
        for cand, pos, neg in (("tinubu", 10 + i, 10), ("obi", 12, 6), ("atiku", 3, 3)):
            n = pos + neg + 5
            rows.append(dict(day=d, candidate=cand, channel_id="c1", category="broadcast_network", channel="Arise News",
                             n=n, n_pos=pos, n_neu=5, n_neg=neg, sum_conf=0.8 * n, sum_likes=n, n_authors=n, n_flagged=0, n_videos=1))
    return pd.DataFrame(rows)


def test_net_sentiment_and_ci():
    assert an.net_sentiment(30, 10, 50) == pytest.approx(0.4)
    lo, hi = an.net_ci(30, 10, 50)
    assert lo < 0.4 < hi and -1 <= lo and hi <= 1
    assert math.isnan(an.net_sentiment(0, 0, 0))


def test_summarize_and_compare():
    fd = _facts()
    s = an.summarize(fd[fd["candidate"] == "obi"])
    assert s["n"] == 23 * 14 and s["net"] == pytest.approx(6 / 23)
    pc = an.compare_periods(fd, pd.Timestamp("2026-10-14"), 7)
    assert pc.current["tinubu"]["n"] > pc.previous["tinubu"]["n"]  # growing series


def test_momentum_and_influence_bounds():
    fd = _facts()
    mom = an.momentum_index(fd, pd.Timestamp("2026-10-14"), 7)
    assert mom["momentum"].between(0, 100).all()
    # tinubu's positive count grows every day -> momentum above the neutral 50
    assert mom.loc[mom["candidate"] == "tinubu", "momentum"].iloc[0] > 50
    inf = an.influence_index(fd, pd.Timestamp("2026-10-14"), 7, mom)
    assert set(inf["rank"]) == {1, 2, 3}
    assert inf["influence"].between(0, 100).all()


def test_daily_series_rolling():
    d = an.daily_series(_facts(), window=7)
    sub = d[d["candidate"] == "obi"]
    assert len(sub) == 14 and sub["rolling_net"].iloc[-1] == pytest.approx(6 / 23)


def test_attribution_whole_words():
    assert match_candidates("Abati is biased, the debate was a combat") == []          # 'bat' substring must not match
    assert match_candidates("BAT will win") == ["tinubu"]
    assert match_candidates("Obi is coming") == ["obi"]
    assert "obi" not in match_candidates("Obiano and Obinna are names")
    assert match_candidates("Atiku's camp and PO") == ["atiku", "obi"]


def test_party_disambiguation():
    assert match_parties("the adc of the governor", []) == []                              # aide-de-camp
    assert match_parties("adc in nigeria", []) == ["adc"]
    assert match_parties("apc government", []) == ["apc"]


def test_clean_text_unescapes():
    assert clean_text("Tinubu &amp; Atiku<br>meet &#39;today&#39; http://x.y") == "Tinubu & Atiku meet 'today'"


def test_language_hint():
    assert language_hint("Wetin dey happen, una no dey see am?")[0] == "pcm"
    assert language_hint("Allah ya kara wa shugaba Tinubu lafiya da nasara")[0] == "ha"
    assert language_hint("The economy is in a terrible state and prices are rising.")[0] == "en"


def test_hash_normalisation():
    a = text_hash("Nigeria is the only country!!! 🌎 where the poor clap")
    b = text_hash("nigeria is the only country where the poor clap")
    assert a == b and text_hash("short") is None
    assert normalise_for_hash("Héllo, World") == "hello world"


def test_topics_and_states():
    t = lexicon_topics("Hunger and banditry everywhere, subsidy removal killed us")
    assert "economy" in t and "security" in t
    assert states_in("No roads in Benue, and the Niger Republic coup worries the Niger Delta") == ["Benue"]
    assert "Niger" in states_in("Minna is in Niger state")
