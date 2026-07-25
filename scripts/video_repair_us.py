#!/usr/bin/env python3
"""One-shot cleanup for the US channel (audit 2026-07-25).

Fault found: DUPLICATE TOPICS — the pre-fix engine re-uploaded the same
topic with the same title 2-3x (audit flags 11 videos -> 5 dup groups,
incl. one "Dark Psychology" TRIPLE upload).

Monetization-safe rule = one video per topic on the channel. For each dup
group we DELETE the weaker copies and KEEP the best performer:

  "Why Your Body Does This: Deja Vu"
      keep  o9RMmgJTx5c (125v)   delete NkBlQuLHwY8 (45v)
  "The Bone That Breaks Most in Fights"
      keep  enQtkaIgByI (111v)   delete NOhr7wFWwXs (6v)
  "Why Your Body Does This: Dreams"
      keep  Jhqjx48cDSg (238v)   delete 19SRKbKe78w (121v)
  "Why Your Body Does This: Forgetting Names"
      keep  eKD0RKCMUFM (98v)    delete x7rGuJfJnAg (44v)
  "Why Your Body Does This: Dark Psychology"  (TRIPLE!)
      keep  I9d3K0ng0MQ (140v)   delete r-I6zkxMCZ4 (117v), 7Wsw351aWYQ (21v)

Total lost views = 354 (negligible); spam-signal cleaned = big.
Re-uploads of these topics are already blocked by the near-duplicate ban
in src/trend_fetcher.py.

Run DRY by default; pass --apply to delete for real.
Needs GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / REFRESH_TOKEN env.
"""
import argparse
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("video-repair-us")

DELETE_IDS = {
    "NkBlQuLHwY8": "weaker copy of 'Deja Vu' (45v; keeper o9RMmgJTx5c 125v)",
    "NOhr7wFWwXs": "weaker copy of 'Bone That Breaks Most' (6v; keeper enQtkaIgByI 111v)",
    "19SRKbKe78w": "weaker copy of 'Dreams' (121v; keeper Jhqjx48cDSg 238v)",
    "x7rGuJfJnAg": "weaker copy of 'Forgetting Names' (44v; keeper eKD0RKCMUFM 98v)",
    "r-I6zkxMCZ4": "copy 2/3 of 'Dark Psychology' (117v; keeper I9d3K0ng0MQ 140v)",
    "7Wsw351aWYQ": "copy 3/3 of 'Dark Psychology' (21v; keeper I9d3K0ng0MQ 140v)",
}


def _token() -> str:
    data = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(
            urllib.request.Request("https://oauth2.googleapis.com/token", data=data),
            timeout=30) as r:
        return json.load(r)["access_token"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    token = _token()
    for vid, why in DELETE_IDS.items():
        if not args.apply:
            log.info("[dry] would DELETE %s (%s)", vid, why)
            continue
        req = urllib.request.Request(
            f"https://www.googleapis.com/youtube/v3/videos?id={vid}", method="DELETE")
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=40) as r:
            r.read()
        log.info("DELETED %s", vid)
        time.sleep(1)
    log.info("done (apply=%s)", args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
