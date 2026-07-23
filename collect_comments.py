"""
Comment collection: pulls top-level comments for every stored video.

Quota cost: 1 unit per commentThreads.list call -- cheap. The search calls
in collect_videos.py are the quota bottleneck, not this step. De-duplication
is automatic (INSERT OR IGNORE on comment_id primary key), so it's safe to
re-run this against videos already processed.
"""

import argparse
import datetime

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from config import YOUTUBE_API_KEY, MAX_COMMENTS_PER_VIDEO, COMMENT_COLLECTION_START
from db import get_conn, upsert_comment


def _parse_rfc3339(timestamp):
    if not timestamp:
        return None
    normalized = timestamp.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(normalized)


def collect_comments(since=COMMENT_COLLECTION_START):
    since_dt = _parse_rfc3339(since)
    if since_dt is None:
        raise ValueError("COMMENT_COLLECTION_START must be a valid RFC 3339 timestamp")

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    quota_used = 0
    comments_found = 0

    with get_conn() as conn:
        videos = conn.execute("SELECT video_id, title FROM videos").fetchall()

        for video in videos:
            video_id = video["video_id"]
            fetched = 0
            page_token = None
            stop_video = False

            while fetched < MAX_COMMENTS_PER_VIDEO and not stop_video:
                try:
                    request = youtube.commentThreads().list(
                        part="snippet",
                        videoId=video_id,
                        maxResults=100,
                        pageToken=page_token,
                        textFormat="plainText",
                        order="time",
                    )
                    response = request.execute()
                    quota_used += 1
                except HttpError as e:
                    title_preview = (video["title"] or "")[:50]
                    print(f"  Skipping {video_id} ({title_preview}...): {e}")
                    break

                items = response.get("items", [])
                for item in items:
                    top = item["snippet"]["topLevelComment"]["snippet"]
                    published_at = top.get("publishedAt")
                    published_dt = _parse_rfc3339(published_at)
                    if published_dt is None or published_dt < since_dt:
                        stop_video = True
                        break

                    comment_id = item["snippet"]["topLevelComment"]["id"]
                    upsert_comment(
                        conn,
                        comment_id=comment_id,
                        video_id=video_id,
                        author=top.get("authorDisplayName"),
                        text_raw=top.get("textDisplay"),
                        published_at=published_at,
                        like_count=top.get("likeCount", 0),
                    )
                    comments_found += 1
                    fetched += 1

                if stop_video:
                    break

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

    print(
        f"\nComment collection done. {comments_found} comments stored since {since}. "
        f"Quota used: {quota_used} units."
    )
    return comments_found, quota_used


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Collect YouTube comments published since a given RFC 3339 timestamp."
    )
    parser.add_argument(
        "--since",
        default=COMMENT_COLLECTION_START,
        help=(
            "Collect comments published on or after this RFC 3339 timestamp. "
            f"Default: {COMMENT_COLLECTION_START}"
        ),
    )
    args = parser.parse_args()
    collect_comments(since=args.since)
