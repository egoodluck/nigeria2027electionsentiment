"""
Comment collection: pulls top-level comments for stored videos.

Quota cost: 1 unit per commentThreads.list call (up to 100 comments). The
search calls in collect_videos.py are the quota bottleneck, not this step --
but only if this step is quota-aware, which the original version was not.

What changed in the 2026-11 release and why
-------------------------------------------
The original loop visited EVERY stored video in insertion order (oldest
first) and paged through up to 300 comments per video on every run. With
2,200 videos that is >2,200 units per run -- more than the headroom left
after discovery -- so the run hit quotaExceeded roughly two thirds of the way
through the list, and the videos it never reached were precisely the newest
ones. Recent comments were systematically under-collected.

Now:
  * videos are visited newest-first;
  * a video is skipped when it is older than ACTIVE_VIDEO_DAYS and its last
    visit yielded no new comments (comment activity on news clips dies within
    days), unless it has never been visited;
  * paging stops as soon as a page contains only comments we already hold
    (order=time is newest-first, so everything after that is old too);
  * a quotaExceeded error ends the run cleanly instead of failing 2,000 more
    times; the next run resumes with the videos that were not reached;
  * `comments_found` now counts rows actually inserted, not rows fetched.

Per-video visit state lives in `video_fetch_state` (created here if absent).
"""

import argparse
import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import COMMENT_COLLECTION_START, MAX_COMMENTS_PER_VIDEO, require_api_key
from db import get_conn

ACTIVE_VIDEO_DAYS = 14          # always revisit videos younger than this
REVISIT_IDLE_DAYS = 7           # revisit older videos at most this often
MAX_PAGES_PER_VIDEO = max(1, MAX_COMMENTS_PER_VIDEO // 100)

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS video_fetch_state (
    video_id          TEXT PRIMARY KEY,
    last_fetched_at   TEXT,
    last_new_comments INTEGER,
    total_fetches     INTEGER DEFAULT 0
);
"""


def _parse_rfc3339(timestamp):
    if not timestamp:
        return None
    normalized = timestamp.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(normalized)


def _is_quota_error(err):
    try:
        return err.resp.status == 403 and b"quota" in (err.content or b"").lower()
    except Exception:
        return False


def _select_videos(conn, now):
    """Newest first; skip stale videos that produced nothing last time."""
    rows = conn.execute(
        """SELECT v.video_id, v.title, v.published_at, s.last_fetched_at, s.last_new_comments
           FROM videos v LEFT JOIN video_fetch_state s ON s.video_id = v.video_id
           ORDER BY v.published_at DESC"""
    ).fetchall()
    active_cutoff = now - datetime.timedelta(days=ACTIVE_VIDEO_DAYS)
    revisit_cutoff = now - datetime.timedelta(days=REVISIT_IDLE_DAYS)
    selected = []
    for r in rows:
        published = _parse_rfc3339(r["published_at"]) if r["published_at"] else None
        last = _parse_rfc3339(r["last_fetched_at"]) if r["last_fetched_at"] else None
        if last is None or (published and published >= active_cutoff):
            selected.append(r)
        elif (r["last_new_comments"] or 0) > 0 or last <= revisit_cutoff:
            selected.append(r)
    return selected


def collect_comments(since=COMMENT_COLLECTION_START, quota_budget=None):
    since_dt = _parse_rfc3339(since)
    if since_dt is None:
        raise ValueError("COMMENT_COLLECTION_START must be a valid RFC 3339 timestamp")

    youtube = build("youtube", "v3", developerKey=require_api_key())
    quota_used = 0
    comments_new = 0
    now = datetime.datetime.now(datetime.timezone.utc)

    with get_conn() as conn:
        conn.executescript(STATE_SCHEMA)
        videos = _select_videos(conn, now)
        print(f"Visiting {len(videos)} videos (newest first).")
        stopped = False

        for video in videos:
            if quota_budget is not None and quota_used >= quota_budget:
                print(f"Quota budget of {quota_budget} units reached; stopping. Remaining videos resume next run.")
                break
            video_id = video["video_id"]
            known = {r[0] for r in conn.execute("SELECT comment_id FROM comments WHERE video_id = ?", (video_id,))}
            page_token = None
            new_for_video = 0
            pages = 0

            while pages < MAX_PAGES_PER_VIDEO:
                try:
                    response = youtube.commentThreads().list(
                        part="snippet", videoId=video_id, maxResults=100, pageToken=page_token,
                        textFormat="plainText", order="time",
                    ).execute()
                    quota_used += 1
                    pages += 1
                except HttpError as e:
                    if _is_quota_error(e):
                        print("YouTube quota exhausted for today; stopping comment collection cleanly.")
                        stopped = True
                    else:
                        title_preview = (video["title"] or "")[:50]
                        print(f"  Skipping {video_id} ({title_preview}...): {e}")
                    break

                items = response.get("items", [])
                saw_old = False
                for item in items:
                    top = item["snippet"]["topLevelComment"]["snippet"]
                    published_at = top.get("publishedAt")
                    published_dt = _parse_rfc3339(published_at)
                    if published_dt is None or published_dt < since_dt:
                        saw_old = True
                        break
                    comment_id = item["snippet"]["topLevelComment"]["id"]
                    if comment_id in known:
                        saw_old = True
                        continue
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO comments
                           (comment_id, video_id, author, text_raw, published_at, like_count)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (comment_id, video_id, top.get("authorDisplayName"), top.get("textDisplay"),
                         published_at, top.get("likeCount", 0)),
                    )
                    if cur.rowcount:
                        new_for_video += 1
                        known.add(comment_id)
                if saw_old:
                    break
                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            if stopped:
                break
            comments_new += new_for_video
            conn.execute(
                """INSERT INTO video_fetch_state (video_id, last_fetched_at, last_new_comments, total_fetches)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(video_id) DO UPDATE SET
                       last_fetched_at = excluded.last_fetched_at,
                       last_new_comments = excluded.last_new_comments,
                       total_fetches = video_fetch_state.total_fetches + 1""",
                (video_id, now.isoformat(timespec="seconds"), new_for_video),
            )
            conn.commit()

    print(f"\nComment collection done. {comments_new} new comments stored since {since}. Quota used: {quota_used} units.")
    return comments_new, quota_used


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect YouTube comments published since a given RFC 3339 timestamp.")
    parser.add_argument("--since", default=COMMENT_COLLECTION_START,
                        help=f"Collect comments published on or after this RFC 3339 timestamp. Default: {COMMENT_COLLECTION_START}")
    parser.add_argument("--quota-budget", type=int, default=None, help="Stop after spending this many quota units.")
    args = parser.parse_args()
    collect_comments(since=args.since, quota_budget=args.quota_budget)
