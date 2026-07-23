"""
Resolve @handles in config.CHANNELS to actual YouTube channelIds, and store
them in the database.

Run this ONCE before your first collection run, and again any time you
add or change a channel in config.py.

    python resolve_channels.py
"""

from googleapiclient.discovery import build
from config import YOUTUBE_API_KEY, CHANNELS
from db import init_db, get_conn, upsert_channel


def resolve_all():
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    init_db()

    with get_conn() as conn:
        for ch in CHANNELS:
            # Pre-verified IDs (found during research) skip the API call
            # entirely -- no quota cost, no risk of a bad handle lookup.
            if ch.get("channel_id"):
                upsert_channel(conn, ch["channel_id"], ch["handle"], ch["label"], ch["category"])
                print(f"[verified]  {ch['label']:<22} -> {ch['channel_id']}")
                continue

            handle = ch["handle"]
            resp = youtube.channels().list(
                part="id,snippet",
                forHandle=handle.lstrip("@"),
            ).execute()
            items = resp.get("items", [])

            if not items:
                raise ValueError(
                    f"Could not resolve handle {handle!r} ({ch['label']}) to a channel ID.\n"
                    f"  -> Visit youtube.com/{handle} in a browser to confirm the correct handle,\n"
                    f"     then fix it in config.CHANNELS and re-run this script.\n"
                    f"  This stops here on purpose rather than silently dropping the channel --\n"
                    f"  a missing channel changes your 50-channel roster composition without you noticing."
                )

            channel_id = items[0]["id"]
            title = items[0]["snippet"]["title"]
            upsert_channel(conn, channel_id, handle, ch["label"], ch["category"])
            print(f"[resolved]  {ch['label']:<22} -> {channel_id}  ({title})")

    print("\nAll channels resolved and stored.")


if __name__ == "__main__":
    resolve_all()
