from __future__ import annotations

import pandas as pd

from scripts.backtest import add_regime_flags


def test_regime_hgefs_flag():
    df = pd.DataFrame({"date": ["2024-12-16", "2024-12-17", "2025-01-01"]})
    out = add_regime_flags(df)
    assert out.loc[0, "regime_hgefs"] == 0
    assert out.loc[1, "regime_hgefs"] == 1
    assert out.loc[2, "regime_hgefs"] == 1


def test_regime_nbm_v43_flag():
    df = pd.DataFrame({"date": ["2025-05-26", "2025-05-27", "2025-06-01"]})
    out = add_regime_flags(df)
    assert out.loc[0, "regime_nbm_v43"] == 0
    assert out.loc[1, "regime_nbm_v43"] == 1
