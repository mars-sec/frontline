# Changelog

All changes to the personal fork of [Frontline](https://github.com/mars-sec/frontline), relative to the public repo.

## 2026-09-01

### Pipeline

- **Always force-rebuild on scheduled runs** - daily container runs now pass `--force` so the pipeline never skips a day due to stale SQLite state from a previous run.
- **Back up previous edition on --force** - when `--force` overwrites an existing edition, the old file is renamed to `{date}_1.html`, `{date}_2.html`, etc. instead of being silently replaced.

### Rendering

- **Landing page shows latest edition only** - `render_index` now copies the latest edition as `index.html` instead of generating an archive listing. Archive is still generated as `archive.html` for repo-level access.
- **Center dateline tagline** - the "An edition of one" text in the masthead is now properly centered using equal-width flex items, regardless of date or volume text width.
- **Favicon** - added `favicon.svg`, `favicon.png`, and `favicon.ico` from marshallyanis.com. All editions and the index page reference them.
- **Footer links** - edition footer links to the GitHub repo and marshallyanis.com/frontline. Archive link removed since the site only serves the current edition.

### Infrastructure

- **Vercel deployment** - `vercel.json` configures static deployment from `editions/` at `frontline.marshallyanis.com`. All URL paths except `/` and favicon files redirect to `/` so visitors can only see the current edition.
- **Docker container** - `Dockerfile` builds a Python 3.13-slim image with git. `daily.sh` is the entry script.
- **daily.sh** - automated daily run script for Synology NAS:
  - Configures git identity and the `personal` remote using `GITHUB_TOKEN`
  - Pulls latest changes from `personal/main` before running so config/profile/code changes propagate automatically
  - Runs `frontline run --force`
  - Commits new edition to `editions/` and pushes to `personal/main`, triggering Vercel auto-deploy
  - Uses editable pip install (`pip install -e`) so config paths resolve to the mounted `/repo` directory, not site-packages
- **daily.ps1** - Windows equivalent of daily.sh for local Task Scheduler use.

### Configuration

- **Personal profile** - `config/profile.md` configured for offensive security, malware development, Windows internals, aerospace security, RF/SDR, and related interests.
- **Starter feeds** - `config/sources.yaml` seeded with 8 feeds: Krebs on Security, Schneier on Security, Simon Willison, Ars Technica, Rust Blog, Python Insider, LWN, Hacker News.
- **`.gitignore` adjusted** - `editions/` and `config/profile.md` are tracked (not ignored) so they deploy to Vercel and persist across clones.

## 2026-08-30

### Initial fork

- Forked from [mars-sec/frontline](https://github.com/mars-sec/frontline) at commit `44d6ef8`.
