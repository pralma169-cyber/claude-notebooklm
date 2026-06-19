#!/usr/bin/env python3
"""
Export content into NotebookLM-ready source files.

NotebookLM has no public "add source" API, so the workflow is:
    1. This script writes clean, self-describing text files into an output
       folder (one file per source, with a title + origin URL header).
    2. You open notebooklm.google.com, click "+ Add source" (or "Upload
       sources"), and drag the whole folder / select the files.

NotebookLM accepts plain text, Markdown, and PDF uploads, plus pasted text and
Google Docs. Plain .txt is the most universally accepted, so it is the default.

It bridges your existing yt_search.py so YouTube transcripts flow straight in,
and can also package arbitrary local files or pasted text.

Examples
--------
    # Search YouTube and export the top 5 transcripts as NotebookLM sources
    python notebooklm_export.py youtube "machine learning basics" -n 5 -o ./nblm_sources

    # Export transcripts for specific videos / URLs
    python notebooklm_export.py youtube --video https://youtu.be/VID1 --video VID2 -o ./out

    # Package existing local files (copies + normalizes them) for upload
    python notebooklm_export.py files notes.md report.txt -o ./out

    # Pipe arbitrary text in as a single source
    echo "some research text" | python notebooklm_export.py stdin --title "My note" -o ./out
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

# Reuse the YouTube tool that already lives next to this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import yt_search
except ImportError:  # pragma: no cover
    yt_search = None  # only needed for the `youtube` subcommand


# --------------------------------------------------------------------------- #
# Writing NotebookLM source files
# --------------------------------------------------------------------------- #
def _slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text or "source").strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return (text[:max_len] or "source").strip("-")


def write_source(
    out_dir: Path,
    title: str,
    body: str,
    origin: str | None = None,
    extra: dict[str, Any] | None = None,
    ext: str = "txt",
    index: int | None = None,
) -> Path:
    """Write one NotebookLM-ready source file and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # A short header gives NotebookLM (and you) provenance for citations.
    header = [f"# {title}"]
    if origin:
        header.append(f"Source: {origin}")
    for key, val in (extra or {}).items():
        if val not in (None, ""):
            header.append(f"{key}: {val}")
    content = "\n".join(header) + "\n\n" + (body or "").strip() + "\n"

    prefix = f"{index:02d}-" if index is not None else ""
    path = out_dir / f"{prefix}{_slugify(title)}.{ext}"
    # avoid clobbering files with identical slugs
    n = 2
    while path.exists():
        path = out_dir / f"{prefix}{_slugify(title)}-{n}.{ext}"
        n += 1
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #
def cmd_youtube(args: argparse.Namespace) -> list[Path]:
    if yt_search is None:
        sys.exit("yt_search.py not found next to this script; cannot fetch YouTube.")

    if args.video:
        results = [yt_search.fetch_video(v) for v in args.video]
    elif args.query:
        results = yt_search.search(args.query, args.limit)
    else:
        sys.exit("provide a search query or one or more --video URLs/IDs")

    langs = [l.strip() for l in args.lang.split(",") if l.strip()]
    written: list[Path] = []
    for i, r in enumerate(results, 1):
        captions = yt_search.extract_captions(
            r, languages=langs, include_auto=not args.no_auto
        )
        if not captions:
            print(f"  ! no captions for: {r['title']} — skipping", file=sys.stderr)
            continue
        path = write_source(
            Path(args.out),
            title=r["title"] or r.get("id") or "video",
            body=captions,
            origin=r["url"],
            extra={
                "Channel": r.get("channel"),
                "Views": r.get("view_count"),
            },
            ext=args.format,
            index=i,
        )
        written.append(path)
    return written


def cmd_files(args: argparse.Namespace) -> list[Path]:
    written: list[Path] = []
    for i, fp in enumerate(args.paths, 1):
        src = Path(fp)
        if not src.is_file():
            print(f"  ! not a file: {src} — skipping", file=sys.stderr)
            continue
        body = src.read_text(encoding="utf-8", errors="replace")
        path = write_source(
            Path(args.out),
            title=src.stem,
            body=body,
            origin=str(src),
            ext=args.format,
            index=i,
        )
        written.append(path)
    return written


def cmd_stdin(args: argparse.Namespace) -> list[Path]:
    body = sys.stdin.read()
    if not body.strip():
        sys.exit("no text received on stdin")
    return [
        write_source(
            Path(args.out),
            title=args.title or "pasted-note",
            body=body,
            ext=args.format,
        )
    ]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    # Shared options, accepted both before AND after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-o", "--out", default="./nblm_sources", help="output folder")
    common.add_argument(
        "--format",
        choices=["txt", "md"],
        default="txt",
        help="file format (txt is most broadly accepted; default txt)",
    )

    parser = argparse.ArgumentParser(
        parents=[common],
        description="Export content into NotebookLM-ready source files.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_yt = sub.add_parser("youtube", parents=[common], help="export YouTube transcripts")
    p_yt.add_argument("query", nargs="?", help="search query")
    p_yt.add_argument("--video", action="append", help="video URL/ID (repeatable)")
    p_yt.add_argument("-n", "--limit", type=int, default=5)
    p_yt.add_argument("--lang", default="en")
    p_yt.add_argument("--no-auto", action="store_true")
    p_yt.set_defaults(func=cmd_youtube)

    p_files = sub.add_parser("files", parents=[common], help="package existing local files")
    p_files.add_argument("paths", nargs="+")
    p_files.set_defaults(func=cmd_files)

    p_stdin = sub.add_parser("stdin", parents=[common], help="read one source from stdin")
    p_stdin.add_argument("--title", help="title for the pasted note")
    p_stdin.set_defaults(func=cmd_stdin)

    args = parser.parse_args(argv)
    written = args.func(args)

    if not written:
        print("No files written.", file=sys.stderr)
        return 1

    out = Path(args.out).resolve()
    print(f"\nWrote {len(written)} source file(s) to:\n  {out}\n")
    for p in written:
        print(f"  • {p.name}")
    print(
        "\nNext: open https://notebooklm.google.com → your notebook →\n"
        '  "+ Add source" → Upload, then select these files (or drag the folder).'
    )
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
