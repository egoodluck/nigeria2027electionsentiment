"""
YouTube video statistics (views, likes, comment counts, duration) for the
media-intelligence reach estimates.

Quota: videos.list costs 1 unit per call and accepts 50 ids per call, so the
whole 2,200-video corpus refreshes for ~45 units -- negligible next to the
search.list calls in discovery.

Videos are refreshed when they have never been fetched or when their last
fetch is older than STATS_REFRESH_DAYS (views keep growing for weeks). Needs
YOUTUBE_API_KEY; skipped cleanly when it is absent so the offline enrichment
steps still run.
"""

import datetime as dt
import os
import re

from pipeline.schema import connect, ensure_schema, log_run
from pipeline.settings import DB_PATH

STATS_REFRESH_DAYS = 7
ISO_DUR = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _duration_seconds(iso):
    m = ISO_DUR.match(iso or "")
    if not m:
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def run(db_path=DB_PATH, verbose=True):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        if verbose:
            print("[video_stats] YOUTUBE_API_KEY not set - skipping (reach estimates stay unavailable)")
        return 0
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        if verbose:
            print("[video_stats] google-api-python-client not installed - skipping")
        return 0

    ensure_schema(db_path)
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    conn = connect(db_path)
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=STATS_REFRESH_DAYS)).isoformat(timespec="seconds")
    ids = [r[0] for r in conn.execute(
        """SELECT v.video_id FROM videos v
           LEFT JOIN video_stats s ON s.video_id = v.video_id
           WHERE s.video_id IS NULL OR s.fetched_at < ?
           ORDER BY v.published_at DESC""", (cutoff,)).fetchall()]
    if not ids:
        conn.close()
        return 0

    youtube = build("youtube", "v3", developerKey=key)
    written, quota = 0, 0
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            resp = youtube.videos().list(part="statistics,contentDetails", id=",".join(chunk), maxResults=50).execute()
            quota += 1
        except HttpError as e:
            print(f"[video_stats] API error, stopping: {e}")
            break
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        rows = []
        for item in resp.get("items", []):
            st = item.get("statistics", {})
            rows.append((item["id"], int(st.get("viewCount", 0) or 0), int(st.get("likeCount", 0) or 0),
                         int(st.get("commentCount", 0) or 0), _duration_seconds(item.get("contentDetails", {}).get("duration")), now))
        conn.executemany(
            "INSERT OR REPLACE INTO video_stats (video_id, view_count, like_count, comment_count, duration_s, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            rows)
        conn.commit()
        written += len(rows)
    log_run(conn, "video_stats", started, written, f"quota={quota}")
    conn.commit()
    conn.close()
    if verbose:
        print(f"[video_stats] refreshed {written} videos using {quota} quota units")
    return written


if __name__ == "__main__":
    run()
