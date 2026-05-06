"""Phase 7 wallet clustering for Polymarket weather-wallet research."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from polymarket_research_common import DATA_DIR, ET, REPORT_DIR, md_table


FEATURES = [
    "trade_count",
    "active_days",
    "trades_per_active_day",
    "market_count",
    "event_count",
    "burstiness_score",
    "median_trade_size",
    "median_notional_usd_proxy",
    "buy_trade_pct",
    "no_outcome_trade_pct",
    "extreme_price_trade_pct",
    "mid_price_trade_pct",
    "city_entropy_norm",
    "event_entropy_norm",
    "repeat_market_rate_pct",
    "same_day_exit_proxy_pct",
    "estimated_aggressiveness_score",
]


def describe_cluster(df: pd.DataFrame) -> str:
    ext = df["extreme_price_trade_pct"].mean()
    repeat = df["repeat_market_rate_pct"].mean()
    events = df["event_count"].mean()
    no = df["no_outcome_trade_pct"].mean()
    if ext > 90 and no > 60:
        return "extreme-price NO / expiry specialists"
    if ext > 70 and repeat > 65:
        return "temperature ladder optimizers"
    if events > 250 and repeat < 65:
        return "broad ladder explorers"
    if df["trade_count"].mean() < 300:
        return "thin recent-slice / unclear"
    return "mixed active weather traders"


def main() -> None:
    profiles = pd.read_parquet(DATA_DIR / "polymarket_wallet_profiles.parquet")
    xdf = profiles[FEATURES].fillna(0)
    x = StandardScaler().fit_transform(xdf)

    best_k = 3
    best_score = -1
    scores = {}
    max_k = min(6, len(profiles) - 1)
    for k in range(2, max_k + 1):
        labels = KMeans(n_clusters=k, n_init=50, random_state=7).fit_predict(x)
        score = silhouette_score(x, labels)
        scores[k] = float(score)
        if score > best_score:
            best_score = score
            best_k = k

    kmeans = KMeans(n_clusters=best_k, n_init=100, random_state=7).fit(x)
    agg = AgglomerativeClustering(n_clusters=best_k).fit_predict(x)
    out = profiles.copy()
    out["cluster_kmeans"] = kmeans.labels_
    out["cluster_hierarchical"] = agg
    out["cluster_agreement"] = out["cluster_kmeans"].astype(str) == out["cluster_hierarchical"].astype(str)

    labels = []
    for cluster, g in out.groupby("cluster_kmeans"):
        labels.append({"cluster_kmeans": cluster, "cluster_label": describe_cluster(g)})
    labels_df = pd.DataFrame(labels)
    out = out.merge(labels_df, on="cluster_kmeans", how="left")
    out["cluster_confidence"] = out["cluster_agreement"].map({True: "medium", False: "low"})
    out.to_parquet(DATA_DIR / "polymarket_wallet_clusters.parquet", index=False)

    cluster_summary = (
        out.groupby(["cluster_kmeans", "cluster_label"])
        .agg(
            wallets=("wallet", "count"),
            median_extreme_pct=("extreme_price_trade_pct", "median"),
            median_repeat_pct=("repeat_market_rate_pct", "median"),
            median_events=("event_count", "median"),
            examples=("user_name", lambda s: ", ".join(s.head(4))),
        )
        .reset_index()
    )

    report = [
        "# Polymarket Wallet Clusters",
        "",
        f"Generated: {datetime.now(tz=ET).isoformat()}",
        "",
        "## Scope",
        "",
        "Research-only. Clusters are provisional and based on 17 wallets in the recent API-accessible slice. They are not stable 24-month strategy families until backfilled.",
        "",
        f"Selected cluster count: {best_k}",
        f"Silhouette scores: {scores}",
        "",
        "## Cluster Summary",
        "",
        md_table(cluster_summary),
        "",
        "## Wallet Assignments",
        "",
        md_table(out[["user_name", "provisional_archetype", "cluster_kmeans", "cluster_label", "cluster_confidence", "trade_count", "extreme_price_trade_pct", "repeat_market_rate_pct"]].sort_values(["cluster_kmeans", "user_name"]), 30),
    ]
    (REPORT_DIR / "polymarket_wallet_clusters.md").write_text("\n".join(report) + "\n")

    print("=== PHASE 7 WALLET CLUSTERING ===")
    print(f"Selected k={best_k}, silhouette={best_score:.3f}")
    print(cluster_summary.to_string(index=False))
    print("\nAssignments:")
    print(out[["user_name", "cluster_kmeans", "cluster_label", "cluster_confidence"]].sort_values(["cluster_kmeans", "user_name"]).to_string(index=False))
    print("\nSaved:")
    print(f"  {DATA_DIR / 'polymarket_wallet_clusters.parquet'}")
    print(f"  {REPORT_DIR / 'polymarket_wallet_clusters.md'}")


if __name__ == "__main__":
    main()

