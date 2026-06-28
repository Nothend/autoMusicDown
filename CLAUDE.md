# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A tool that auto-downloads songs from NetEase Cloud Music (网易云音乐) daily-recommendation
playlists. The user manually adds songs into a playlist named after the current date (e.g.
`20251025`); on a cron schedule the tool scans for that playlist, filters out songs already in
the library, and downloads the rest with full metadata (lyrics, year, cover art, artists)
embedded as audio tags. Designed for incremental updates to an existing music library
(~30 songs/day), not bulk downloading. Requires a NetEase 黑胶 (VIP) account.

All code comments and log messages are in Chinese; match that when editing.

## Running and developing

The app is a one-shot batch job — `src/main.py` runs the full sync once and `exit()`s. The
cron loop that repeats it lives in `entrypoint.sh`, not in Python.

```bash
# Run the sync once (must be run from the src/ dir, or with src/ on sys.path — imports are flat)
cd src && python main.py

# Install deps
pip install -r requirements.txt        # use the root one — src/requirements.txt is missing Pillow
```

There are **no tests, linter, or build step**. Several modules have a `__main__` block but they
are stubs/scratch, not a test harness.

### Debug mode
Set `DEBUG_MODE=True` to make `main.py` use a hardcoded date (`20251025`) instead of today's
date when searching for the playlist. The VSCode launch config (`.vscode/launch.json`,
"Python Debugger: Current File") sets this automatically.

## Configuration

`config.yaml` at the repo root drives everything. It is **gitignored and contains live secrets**
(NetEase cookie, DB passwords) — never commit it. Copy `config.example.yaml` to start.

- `Config` (`src/config.py`) resolves the path as: `CONFIG_PATH` env → `<repo root>/config.yaml`
  → `<cwd>/config.yaml`. In Docker the file is mounted read-only at `/app/repo/config.yaml`.
- `cookie`: raw NetEase cookie string (must contain `MUSIC_U`), parsed by `utils.parse_cookie`.
- `QUALITY_LEVEL`: one of `standard`/`exhigh`/`lossless`/`hires`/`sky`/`jyeffect`/`jymaster`.
- `is_enabled("NAVIDROME")` and `is_enabled("MUSIC-TAG-WEB")` are the only feature toggles —
  they key off `NAVIDROME.USE_NAVIDROME` and `music-tag-web.USE_MYSQL`. Note the string
  `"MUSIC-TAG-WEB"` maps to the lowercase `music-tag-web` YAML node (see `Config.is_enabled`).

## Architecture

Flat module layout under `src/` (no packages — imports are bare like `from netease import ...`).
`MusicSyncApp.run_task()` in `main.py` is the orchestrator and the best entry point to read.

The pipeline:
1. **Cookie validation** — `NeteaseMusic.is_cookie_valid()` hits the account API and returns
   `{'valid', 'is_vip'}`. Non-VIP accounts abort the run (only VIP can fetch lossless URLs).
2. **Find playlist** — `find_todays_playlist(uid, date)` lists the user's playlists and matches
   one whose name exactly equals the date string.
3. **Filter** — for each track, dedupe in this order (cheap checks first):
   1. **Library check** — Navidrome enabled → `NavidromeChecker.exists()` (Subsonic API);
      music-tag-web enabled → `MusicTagWebChecker.exists()` (queries its MySQL DB directly);
      neither → skipped. Both live in `library.py` behind `LibraryChecker`.
   2. **Local-file check** — `is_song_already_downloaded(name, artists)` globs the download
      dir by name+artists (no network); skip if found. Runs *before* the heavy network calls
      so already-downloaded tracks cost nothing on re-runs.
   3. **Fetch download info** — `SongDownloader.get_music_info()` fetches the song URL first
      and returns `None` immediately for MP3-only results, skipping the detail/album/lyric
      calls. **MP3 is skipped on purpose** (library standardizes on lossless; see commit
      "MP3格式数据暂不下载").
4. **Download** — `SongDownloader.download_songs()` downloads to `/app/downloads` (hardcoded
   dir), then embeds tags via `_write_flac_tags` / `_write_m4a_tags` / `_write_mp3_tags`
   (mutagen). Cover art is fetched and downscaled by `_compress_image` (Pillow).
5. **Notify** — `BarkNotifier` sends a filter-stage report and a download-result summary to the
   Bark push API if `BARK_API` is set.

### Module map
- `netease.py` — NetEase API client. `CryptoUtils`/`APIConstants` implement the eapi AES
  request signing; `NeteaseMusic` wraps playlist/song/lyric/album endpoints.
- `downloader.py` — `SongDownloader` + `MusicInfo`/`DownloadResult` dataclasses; file download,
  filename sanitizing, tag writing, image compression.
- `utils.py` — shared pure helpers: `parse_cookie` (raw cookie string → dict),
  `timestamp_to_date`, `quality_display_name`.
- `library.py` — the whole library-dedupe subsystem behind the `LibraryChecker` interface:
  `NavidromeChecker` (Subsonic API, token auth) + `MusicTagWebChecker` (music-tag-web MySQL),
  plus the `make_library_checker` factory. `main` only depends on the interface.
- `bark.py` — push notifications. `logger.py` — root logger to stdout + `logs/<date>.log`.

## Deployment

Docker is the intended runtime (`docker-compose.yml`, image
`leonautilus/auto-music-downloader`). The container does **not** bake in the app code — instead
`entrypoint.sh` `git clone`/`git pull`s `REPO_URL` into `/app/repo` at startup and on the
`PULL_CRON` schedule, then installs `requirements.txt`, then registers two crontab entries:
`PULL_CRON` (default daily 18:00) re-pulls code, and `CRON_SCHEDULE` runs
`python -u /app/repo/src/main.py`. So pushing to the GitHub repo is effectively the deploy
mechanism — running containers self-update on the next pull. `CRON_SCHEDULE` and `REPO_URL` are
required env vars or the entrypoint exits.

A GitHub Actions workflow (`.github/`) builds and pushes the image.
