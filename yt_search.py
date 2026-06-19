#!/usr/bin/env python3
"""
YouTube search tool built on yt-dlp.

Searches YouTube and reports each result's title, channel, and view count.
Optionally downloads and extracts captions (subtitles / auto-generated) as
plain text.

Examples
--------
    # Search and print the top 5 results
    python yt_search.py "lo-fi hip hop" -n 5

    # Search and also extract English captions for each hit
    python yt_search.py "python tutorial" -n 3 --captions

    # Extract captions for a single known video / URL
    python yt_search.py --video https://www.youtube.com/watch?v=dQw4w9WgXcQ --captions

    # Emit machine-readable JSON instead of a table
    python yt_search.py "climate report" -n 10 --json
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from typing import Any, Iterable

try:
    from yt_dlp import YoutubeDL
except ImportError:  # pragma: no cover - import guard
    sys.exit(
        "yt-dlp is not installed. Install it with:\n"
        "    pip install -U yt-dlp"
    )


# --------------------------------------------------------------------------- #
# Searching / metadata
# --------------------------------------------------------------------------- #
def search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return metadata for the top `limit` YouTube results for `query`."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,  # need full entries for accurate view counts
        "skip_download": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    return [_summarize(entry) for entry in info.get("entries", []) if entry]


def fetch_video(url: str) -> dict[str, Any]:
    """Return metadata for a single video URL or ID."""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return _summarize(info)


def _summarize(entry: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields we care about out of a yt-dlp info dict."""
    return {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "channel": entry.get("channel") or entry.get("uploader"),
        "view_count": entry.get("view_count"),
        "duration": entry.get("duration"),
        "url": entry.get("webpage_url")
        or (f"https://www.youtube.com/watch?v={entry.get('id')}" if entry.get("id") else None),
        # keep the raw entry around so captions can be extracted without a
        # second network round-trip
        "_raw": entry,
    }


# --------------------------------------------------------------------------- #
# Captions
# --------------------------------------------------------------------------- #
def extract_captions(
    entry: dict[str, Any],
    languages: Iterable[str] = ("en",),
    include_auto: bool = True,
) -> str | None:
    """
    Return caption text for a video as a plain string, or None if unavailable.

    `entry` may be a summary dict (with a `_raw` key) or a raw yt-dlp info dict.
    Prefers manually-uploaded subtitles, falling back to auto-generated ones.
    """
    raw = entry.get("_raw", entry)
    subs = raw.get("subtitles") or {}
    auto = raw.get("automatic_captions") or {} if include_auto else {}

    track = _pick_track(subs, languages) or _pick_track(auto, languages)
    if not track:
        return None

    data = _download_track(track)
    if data is None:
        return None
    return _captions_to_text(data)


def _pick_track(
    tracks: dict[str, list[dict[str, Any]]], languages: Iterable[str]
) -> dict[str, Any] | None:
    """Choose the best caption format for the first matching language."""
    if not tracks:
        return None

    # exact match first, then any language that starts with a requested code
    # (e.g. "en-US" satisfies a request for "en")
    candidates: list[str] = []
    for lang in languages:
        if lang in tracks:
            candidates.append(lang)
    for lang in languages:
        for available in tracks:
            if available.startswith(lang) and available not in candidates:
                candidates.append(available)

    if not candidates:
        return None

    formats = tracks[candidates[0]]
    # Prefer text-friendly formats over the binary/positional ones.
    preference = ["json3", "srv3", "srv2", "srv1", "vtt", "ttml"]
    formats_by_ext = {f.get("ext"): f for f in formats}
    for ext in preference:
        if ext in formats_by_ext:
            return formats_by_ext[ext]
    return formats[0] if formats else None


def _download_track(track: dict[str, Any]) -> tuple[str, str] | None:
    """Download a caption track. Returns (ext, raw_text) or None."""
    url = track.get("url")
    if not url:
        return None
    try:
        # yt-dlp ships urllib helpers, but a direct request keeps deps minimal.
        from urllib.request import Request, urlopen

        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as resp:  # noqa: S310 - YouTube URL
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    return track.get("ext", ""), raw


def _captions_to_text(data: tuple[str, str]) -> str:
    """Convert a downloaded caption track into clean, deduplicated text."""
    ext, raw = data
    if ext == "json3":
        return _from_json3(raw)
    if ext in ("vtt",):
        return _from_vtt(raw)
    # srv*/ttml are XML-ish; strip tags as a reasonable fallback.
    return _from_xmlish(raw)


def _from_json3(raw: str) -> str:
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return _from_xmlish(raw)
    lines: list[str] = []
    for event in doc.get("events", []):
        segs = event.get("segs") or []
        text = "".join(seg.get("utf8", "") for seg in segs).strip()
        if text:
            lines.append(text)
    return _dedupe_lines(lines)


def _from_vtt(raw: str) -> str:
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if (
            not line
            or line == "WEBVTT"
            or "-->" in line
            or line.startswith(("NOTE", "Kind:", "Language:"))
            or line.isdigit()
        ):
            continue
        # strip inline timing/style tags like <00:00:01.000> and <c>
        line = re.sub(r"<[^>]+>", "", line)
        if line:
            lines.append(line)
    return _dedupe_lines(lines)


def _from_xmlish(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "\n", raw)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return _dedupe_lines(lines)


def _dedupe_lines(lines: list[str]) -> str:
    """Collapse consecutive duplicate lines (common in auto-captions)."""
    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Formatting / CLI
# --------------------------------------------------------------------------- #
def _human_views(n: int | None) -> str:
    if n is None:
        return "—"
    for unit, div in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(n)


def _human_duration(seconds: int | None) -> str:
    if not seconds:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def print_table(results: list[dict[str, Any]]) -> None:
    if not results:
        print("No results.")
        return
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['title']}")
        print(
            f"   {r['channel'] or '—'}  ·  "
            f"{_human_views(r['view_count'])} views  ·  "
            f"{_human_duration(r['duration'])}"
        )
        print(f"   {r['url']}")
        if "captions" in r:
            if r["captions"]:
                preview = r["captions"].replace("\n", " ")
                preview = preview[:200] + ("…" if len(preview) > 200 else "")
                print(f"   captions: {preview}")
            else:
                print("   captions: (none available)")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search YouTube and fetch metadata / captions via yt-dlp."
    )
    parser.add_argument("query", nargs="?", help="search query")
    parser.add_argument(
        "--video",
        help="fetch a single video by URL or ID instead of searching",
    )
    parser.add_argument(
        "-n", "--limit", type=int, default=5, help="number of results (default 5)"
    )
    parser.add_argument(
        "--captions", action="store_true", help="extract captions for each result"
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="comma-separated caption language codes (default: en)",
    )
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help="do not fall back to auto-generated captions",
    )
    parser.add_argument("--json", action="store_true", help="output JSON")
    args = parser.parse_args(argv)

    if not args.query and not args.video:
        parser.error("provide a search query or --video URL")

    if args.video:
        results = [fetch_video(args.video)]
    else:
        results = search(args.query, args.limit)

    if args.captions:
        langs = [l.strip() for l in args.lang.split(",") if l.strip()]
        for r in results:
            r["captions"] = extract_captions(
                r, languages=langs, include_auto=not args.no_auto
            )

    # drop the bulky raw entry before output
    for r in results:
        r.pop("_raw", None)

    if args.json:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print_table(results)
    return 0


if __name__ == "__main__":
    # ensure UTF-8 output on Windows consoles
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    raise SystemExit(main())
