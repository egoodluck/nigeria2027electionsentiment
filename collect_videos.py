"""
Video discovery: searches each configured channel for each discovery query,
restricted to the collection window, and stores matching videos.

Quota cost: 100 units per search.list call.
50 channels x 4 queries = 200 calls = 20,000 units for one full pass over
every channel x query pair -- double the free daily quota (10,000 units).
So unlike a small roster, this can't complete in a single run.

Rationed passes: a "pass" is one full sweep of every (channel, query) pair.
Each run searches at most MAX_SEARCH_CALLS_PER_RUN pairs and persists its
cursor in the discovery_state table, so a pass spreads across as many daily
runs as it takes (~3 runs at the default rationing).

publishedBefore is always config.COLLECTION_END (a fixed, far-future date)
-- never "now" -- so it's guaranteed to be after publishedAfter regardless
of when a run happens to execute (e.g. before config.COLLECTION_START, or
partway through a pass). publishedAfter only advances between passes, once
a pass fully completes: the moment the completed pass started (recorded as
pass_started_at) becomes the next pass's publishedAfter, so no window is
skipped or double-counted -- it just takes a few days to sweep the roster
instead of one run.

YouTube's search.list rejects any publishedAfter timestamp that's still in
the future relative to its own clock (confirmed empirically -- it's a hard
400, not a soft "zero results"). If you run this before COLLECTION_START
arrives (e.g. testing a few days early), publishedAfter for a new pass would
be a future date and every call would fail. Since no video can have a
publish date in the future anyway, the correct behaviour is to skip
discovery entirely until COLLECTION_START has passed -- there's nothing to
find yet, so no call, no quota spent, no error.
"""

import datetime
from googleapiclient.discovery import build
import re

from googleapiclient.errors import HttpError
from config import (
    require_api_key,
    DISCOVERY_QUERIES,
    DISCOVERY_MODE,
    DISCOVERY_TITLE_TERMS,
    COLLECTION_START,
    COLLECTION_END,
    MAX_RESULTS_PER_SEARCH,
    MAX_SEARCH_CALLS_PER_RUN,
    UPLOADS_MAX_PAGES_PER_CHANNEL,
)
from db import get_conn, upsert_video, get_discovery_state, save_discovery_state

TITLE_RX = re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in DISCOVERY_TITLE_TERMS) + r")(?![\w])", re.IGNORECASE)


def _utcnow_rfc3339():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_videos_search():
    youtube = build("youtube", "v3", developerKey=require_api_key())
    quota_used = 0
    videos_found = 0

    with get_conn() as conn:
        channel_rows = conn.execute(
            "SELECT channel_id, handle, label FROM channels ORDER BY channel_id"
        ).fetchall()

        if not channel_rows:
            raise RuntimeError(
                "No channels in the database. Run resolve_channels.py first."
            )

        pairs = [(ch, query) for ch in channel_rows for query in DISCOVERY_QUERIES]

        now = _utcnow_rfc3339()
        state = get_discovery_state(conn)
        if state is None or state["published_after"] is None:
            # No pass currently in flight -- start a new one, anchored from
            # where the last completed pass left off (or COLLECTION_START
            # for the very first pass ever). publishedBefore is always the
            # fixed COLLECTION_END, never "now".
            last_pass_end = state["last_pass_end"] if state else COLLECTION_START
            published_after = last_pass_end
            published_before = COLLECTION_END
            pass_started_at = now
            cursor = 0

            if published_after > now:
                print(f"Collection window hasn't started yet (publishedAfter={published_after} "
                      f"is still in the future). Skipping video discovery this run -- no videos "
                      f"can exist yet, so no API calls or quota spent. Will resume automatically "
                      f"once that date arrives.")
                return 0, 0
        else:
            last_pass_end = state["last_pass_end"]
            published_after = state["published_after"]
            published_before = state["published_before"]
            pass_started_at = state["pass_started_at"]
            cursor = state["cursor"]

        calls_made = 0
        while cursor < len(pairs) and calls_made < MAX_SEARCH_CALLS_PER_RUN:
            ch, query = pairs[cursor]
            request = youtube.search().list(
                part="id,snippet",
                channelId=ch["channel_id"],
                q=query,
                type="video",
                order="date",
                publishedAfter=published_after,
                publishedBefore=published_before,
                maxResults=MAX_RESULTS_PER_SEARCH,
            )
            response = request.execute()
            quota_used += 100
            calls_made += 1

            items = response.get("items", [])
            for item in items:
                video_id = item["id"]["videoId"]
                title = item["snippet"]["title"]
                video_published_at = item["snippet"]["publishedAt"]
                upsert_video(conn, video_id, ch["channel_id"], title, video_published_at, query)
                videos_found += 1

            print(f"[{ch['label']}] '{query}': {len(items)} videos "
                  f"(pair {cursor + 1}/{len(pairs)}, quota used so far: {quota_used})")
            cursor += 1

        if cursor >= len(pairs):
            save_discovery_state(
                conn, cursor=0, published_after=None, published_before=None,
                pass_started_at=None, last_pass_end=pass_started_at,
            )
            print(f"\nDiscovery pass complete (covered {published_after} onward, "
                  f"next pass starts from {pass_started_at}).")
        else:
            save_discovery_state(
                conn, cursor=cursor, published_after=published_after,
                published_before=published_before, pass_started_at=pass_started_at,
                last_pass_end=last_pass_end,
            )
            print(f"\nDiscovery pass in progress: {cursor}/{len(pairs)} channel x query pairs "
                  f"done so far. Continues automatically on the next run.")

    print(f"\nVideo discovery done this run. {videos_found} new videos stored. Quota used: {quota_used} units.")
    return videos_found, quota_used


def collect_videos_uploads():
    """Cheap discovery: scan each channel's uploads playlist (1 unit / 50 videos)
    and keep videos inside the collection window whose title matches
    DISCOVERY_TITLE_TERMS. Stops paging a channel once it reaches videos older
    than the window start or older than the newest video already stored for it."""
    youtube = build("youtube", "v3", developerKey=require_api_key())
    quota_used = 0
    videos_found = 0
    with get_conn() as conn:
        channel_rows = conn.execute("SELECT channel_id, handle, label FROM channels ORDER BY label").fetchall()
        if not channel_rows:
            raise RuntimeError("No channels in the database. Run resolve_channels.py first.")
        for ch in channel_rows:
            uploads_id = "UU" + ch["channel_id"][2:] if ch["channel_id"].startswith("UC") else None
            if not uploads_id:
                print(f"[{ch['label']}] channel id does not look like UC...; skipping uploads scan")
                continue
            newest_known = conn.execute(
                "SELECT MAX(published_at) FROM videos WHERE channel_id = ?", (ch["channel_id"],)).fetchone()[0]
            floor = max(COLLECTION_START, newest_known or COLLECTION_START)
            page_token, pages, kept = None, 0, 0
            while pages < UPLOADS_MAX_PAGES_PER_CHANNEL:
                try:
                    resp = youtube.playlistItems().list(
                        part="snippet", playlistId=uploads_id, maxResults=50, pageToken=page_token).execute()
                    quota_used += 1
                    pages += 1
                except HttpError as e:
                    print(f"[{ch['label']}] playlist error: {e}")
                    break
                reached_floor = False
                for item in resp.get("items", []):
                    sn = item["snippet"]
                    published = sn.get("publishedAt", "")
                    if published < floor:
                        reached_floor = True
                        break
                    if published >= COLLECTION_END:
                        continue
                    title = sn.get("title", "")
                    if TITLE_RX.search(title):
                        vid = sn.get("resourceId", {}).get("videoId")
                        if vid:
                            upsert_video(conn, vid, ch["channel_id"], title, published, "uploads")
                            videos_found += 1
                            kept += 1
                page_token = resp.get("nextPageToken")
                if reached_floor or not page_token:
                    break
            print(f"[{ch['label']}] uploads scan: {pages} page(s), {kept} matching videos (quota so far {quota_used})")
    print(f"\nVideo discovery (uploads mode) done. {videos_found} videos stored/refreshed. Quota used: {quota_used} units.")
    return videos_found, quota_used


def collect_videos():
    if DISCOVERY_MODE == "uploads":
        return collect_videos_uploads()
    return collect_videos_search()


if __name__ == "__main__":
    collect_videos()
