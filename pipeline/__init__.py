"""
Enrichment pipeline for the Nigeria 2027 Election Intelligence Platform.

Everything in this package runs *offline* (on the collection host, after the
daily YouTube pull) and writes its results into election_sentiment.db. The
Streamlit app never runs a model: it only reads the tables this package
produces, which is what keeps the dashboard fast on a free hosting tier.

Modules
-------
schema            additive DDL for the enrichment tables and indexes
settings          constants shared by the pipeline and the dashboard (no API key)
features          per-comment features: language hint, hashes, author activity
sentiment_models  transformer sentiment scoring (CardiffNLP RoBERTa, NaijaSenti)
topics            seeded-lexicon topic classification
locations         state / geopolitical-zone mention detection
authenticity      duplicate, burst and manipulation-risk signals
aggregates        daily fact tables, keyword log-odds, model agreement
forecast          sentiment / volume projections (statsmodels)
video_stats       YouTube video statistics (views, likes) for reach estimates
enrich            orchestrator: runs the steps above in order
"""
