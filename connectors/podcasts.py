"""Apple Podcasts: the shows you follow and the episodes you played (when last, how far, how often).

The library keeps one row per episode, so only the latest play of each is known; daily runs keep earlier
plays of episodes played again (accumulate)."""

from common import LIB, Writer, columns, connect, from_apple, select, snapshot_sqlite, tables

DB = LIB / "Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite"
AVENUE = ("Local SQLite: ~/Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite "
          "(the Podcasts app; the iPhone's copy has the same schema). ZMTPODCAST = shows (ZSUBSCRIBED, ZADDEDDATE), "
          "ZMTEPISODE = episodes (ZLASTDATEPLAYED, ZPLAYHEAD seconds in, ZPLAYCOUNT, ZDURATION).")


def main():
    with Writer("podcasts", AVENUE) as w:
        if not DB.exists():
            return
        con = connect(snapshot_sqlite(DB, "podcasts/MTLibrary.sqlite"))
        if not {"ZMTPODCAST", "ZMTEPISODE"} <= tables(con):  # made, never written to
            w.notes["empty"] = 1
            return
        # Each column only if this version of Podcasts has it: one missing mustn't lose every show and play.
        shows = {}
        for r in con.execute(select(con, "ZMTPODCAST", ("Z_PK", "ZUUID", "ZTITLE", "ZAUTHOR", "ZSUBSCRIBED", "ZADDEDDATE",
                                                        "ZWEBPAGEURL", "ZFEEDURL"))):
            shows[r["Z_PK"]] = r
            if r["ZSUBSCRIBED"]:
                w.add(id=f"show:{r['ZUUID'] or r['Z_PK']}", kind="subscription", ts=from_apple(r["ZADDEDDATE"]),
                      author="me", is_me=True, title=r["ZTITLE"], text=f"Follows {r['ZTITLE']}" + (f" by {r['ZAUTHOR']}" if r["ZAUTHOR"] else ""),
                      url=r["ZWEBPAGEURL"], meta={"author": r["ZAUTHOR"], "feed": r["ZFEEDURL"]})
        cols = columns(con, "ZMTEPISODE")
        played = " or ".join(test for test, c in (("ZLASTDATEPLAYED is not null", "ZLASTDATEPLAYED"), ("ZPLAYCOUNT > 0", "ZPLAYCOUNT"),
                                                  ("ZHASBEENPLAYED = 1", "ZHASBEENPLAYED")) if c in cols) or "0"
        want = ("Z_PK", "ZUUID", "ZTITLE", "ZPODCAST", "ZLASTDATEPLAYED", "ZPLAYCOUNT", "ZPLAYHEAD", "ZDURATION", "ZPUBDATE", "ZWEBPAGEURL")
        for r in con.execute(select(con, "ZMTEPISODE", want) + f" where {played}"):
            show = shows.get(r["ZPODCAST"])
            when = from_apple(r["ZLASTDATEPLAYED"])
            # One record per play we've seen: an episode played again later is a new record.
            rid = f"play:{r['ZUUID'] or r['Z_PK']}:{when or 'unknown'}"
            w.add(id=rid, kind="listen", ts=when, author="me", is_me=True, title=r["ZTITLE"],
                  thread=show["ZUUID"] if show else None, thread_name=show["ZTITLE"] if show else None,
                  text=f"Listened to {r['ZTITLE']}" + (f" ({show['ZTITLE']})" if show else ""),
                  url=r["ZWEBPAGEURL"],
                  meta={"show": show["ZTITLE"] if show else None, "seconds_in": r["ZPLAYHEAD"], "duration": r["ZDURATION"],
                        "play_count": r["ZPLAYCOUNT"], "published": from_apple(r["ZPUBDATE"])})


if __name__ == "__main__":
    main()
