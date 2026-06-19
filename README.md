# claude-notebooklm

Tools that bridge YouTube content into [NotebookLM](https://notebooklm.google.com),
plus a GitHub Action that keeps the source files refreshed automatically.

## What's here

| File | Purpose |
|------|---------|
| `yt_search.py` | Search YouTube via yt-dlp; fetch title/channel/views; extract captions. |
| `notebooklm_export.py` | Write NotebookLM-ready source files (one per video/file/note). |
| `nblm_queries.txt` | The list of YouTube queries the scheduled Action exports. |
| `.github/workflows/export-sources.yml` | Runs the exporter on a schedule and commits results. |
| `nblm_sources/` | Generated source files (created on first run). |

## Local use

```bash
pip install -r requirements.txt

# Search + metadata
python yt_search.py "lo-fi hip hop" -n 5

# Export transcripts as NotebookLM sources
python notebooklm_export.py youtube "machine learning basics" -n 5 -o ./nblm_sources
```

## Automated refresh (GitHub Action)

The workflow `Export NotebookLM sources`:

- runs **every Monday 06:00 UTC** (`schedule` cron) and on **manual dispatch**,
- reads `nblm_queries.txt` (or an ad-hoc query you type when dispatching),
- exports the top transcripts into `nblm_sources/`,
- commits the changes back to the repo.

### Feeding the results into NotebookLM

NotebookLM has no API to add sources, but it accepts **Website** URLs. Each
committed file has a raw URL, e.g.:

```
https://raw.githubusercontent.com/<user>/<repo>/main/nblm_sources/01-foo.txt
```

In NotebookLM: **+ Add source → Website → paste the raw URL**.

> The repo (or at least these files) must be **public** for NotebookLM to fetch
> them. Don't commit anything sensitive.

## One-time setup

1. Create a GitHub repo and push this folder (see commands in the setup notes).
2. In the repo: **Settings → Actions → General → Workflow permissions →
   "Read and write permissions"** so the Action can commit. (Or rely on the
   `permissions: contents: write` block already in the workflow.)
3. Trigger a first run: **Actions tab → Export NotebookLM sources → Run workflow**.
