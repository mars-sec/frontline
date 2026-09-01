# Frontline

Claude kept refusing to tell me modern research on malware and EDR systems, so why not make it give me the research each morning? Here's frontline: an AI-scored daily newspaper from your RSS feeds.

Frontline pulls articles from your RSS feeds, scores them against your interests using AI, composes a daily broadsheet newspaper, and renders it as a static HTML page you can host anywhere.

**Three backends, one pipeline:**

| Backend | Scoring | Edition composition | Cost |
|---------|---------|-------------------|------|
| **Claude** (default) | Structured output, batch API (50% off) | AI-written headlines, summaries, editor's letter | ~$0.05-0.15/day |
| **Ollama** | Local JSON mode | AI-written (local, free) | Free |
| **Heuristic** | Profile keyword matching | Curated list (no rewriting) | Free |

## Quickstart

### 1. Install

```bash
git clone https://github.com/youruser/frontline.git
cd frontline
pip install -e ".[all]"
```

The `[all]` extra installs Claude, Ollama, and FastEmbed support. Install only what you need:

```bash
pip install -e "."                  # core only (heuristic backend)
pip install -e ".[claude]"          # + Claude API
pip install -e ".[ollama]"          # + Ollama
pip install -e ".[embeddings]"      # + FastEmbed (better pre-filtering)
pip install -e ".[claude,embeddings]"  # common combo
```

### 2. Initialize

```bash
frontline init
```

This creates your config files:
- `config/profile.md` - **edit this first.** It's the single most important input. Be specific about your interests, anti-interests, and what you're working on. The AI scores every article against this.
- `config/sources.yaml` - your feed list (starts empty)
- `.env` - your API key (if using Claude)

### 3. Configure your backend

**Claude (best quality):**

```bash
# Add your API key to .env
# Get one at https://console.anthropic.com/settings/keys
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

No changes needed in `config/settings.yaml` - Claude is the default.

**Ollama (local, free):**

```bash
# Install Ollama: https://ollama.com
ollama pull llama3.1:8b
```

Edit `config/settings.yaml`:
```yaml
scoring_backend: ollama
ollama_model: llama3.1:8b    # or any model you've pulled
```

**Heuristic (no AI, no setup):**

Edit `config/settings.yaml`:
```yaml
scoring_backend: heuristic
```

### 4. Add feeds

**Automatic discovery (Claude only):**
```bash
frontline discover
```
Claude reads your profile, searches the web for relevant RSS feeds, verifies each one, and adds them to `config/sources.yaml`.

**Manual:**
```bash
frontline add-source https://blog.python.org/feeds/posts/default
frontline add-source https://feeds.arstechnica.com/arstechnica/index --name "Ars Technica"
```

**By hand:** Edit `config/sources.yaml` directly:
```yaml
feeds:
  - name: Python Blog
    url: https://blog.python.org/feeds/posts/default
  - name: Ars Technica
    url: https://feeds.arstechnica.com/arstechnica/index
    weight: 1.5    # boost this source in ranking
```

### 5. Run

```bash
frontline run
```

This runs the full pipeline:
1. Fetches articles from all feeds (conditional GET - polite to servers)
2. Extracts full text from article pages
3. Enriches with CVE/KEV data (security feeds)
4. Embeds articles and pre-filters by relevance (~70% dropped, saves cost)
5. Scores remaining articles against your profile
6. Composes a newspaper edition
7. Renders to `editions/YYYY-MM-DD.html`

Open the HTML file in your browser. That's your newspaper. See [CLI Reference](#cli-reference) for all flags.

## CLI Reference

| Command | Description |
|---------|-------------|
| `frontline init` | Set up config files for first use |
| `frontline run` | Fetch, score, compose, and render today's edition |
| `frontline discover` | Have Claude find feeds from your profile |
| `frontline add-source <url>` | Verify and add a single feed URL |
| `frontline sources` | List configured feed sources |
| `frontline costs` | Show API spend from the local cost ledger |
| `frontline serve` | Start the dashboard at localhost:8787 |

### Flags

**`frontline run`**
| Flag | Description |
|------|-------------|
| `--dry-run` | Score only, print candidates, skip edition |
| `--sync` | Synchronous API calls instead of batch (faster, full price) |
| `--rescore` | Re-score articles that already have scores |
| `--force` | Rebuild even if today's edition exists |
| `--date YYYY-MM-DD` | Override the edition date |

**`frontline discover`**
| Flag | Description |
|------|-------------|
| `--max-searches N` | Web search cap (default 15, billed ~$0.01/search) |

**`frontline add-source`**
| Flag | Description |
|------|-------------|
| `--name NAME` | Display name (auto-detected from feed if omitted) |
| `--weight N` | Source weight for ranking (default 1.0, >1 boosts, <1 dampens) |

**`frontline serve`**
| Flag | Description |
|------|-------------|
| `--port PORT` | Port (default from settings.yaml, 8787) |
| `--host HOST` | Host to bind (default from settings.yaml, 127.0.0.1) |

## Dashboard

```bash
frontline serve
# Open http://localhost:8787/dashboard
```

The dashboard shows:
- **Articles tab** - scored articles with thumbs up/down feedback buttons
- **Editions tab** - links to rendered editions
- **Feedback tab** - your feedback history
- **Costs tab** - API spend breakdown by day, stage, and model

Feedback improves scoring: liked/disliked articles are injected as few-shot examples into future scoring prompts.

## How it works

### Pipeline

```
RSS feeds → extract full text → CVE/KEV enrichment
  → embed (FastEmbed/hashing) → dedup clustering
  → Stage 0 pre-filter (embeddings, ~70% dropped)
  → Stage 1 scoring (LLM or heuristic)
  → rank (relevance × recency × source weight)
  → compose edition (LLM or heuristic)
  → render HTML broadsheet
```

### Scoring (0-10 scale)

The scorer reads your profile and assigns each article:
- **Score** (0-10) - how relevant to your interests
- **Section** - which newspaper section it belongs in
- **Reason** - why it scored this way
- **TL;DR** - one-line summary
- **Fluff flag** - marketing/PR detection

### Edition composition

The AI editor picks a lead story, groups the rest into 2-5 sections, writes sharp headlines in the paper's own voice, and composes an editor's letter connecting the day's themes to your world. It works from the scored and ranked article pool - a tight paper beats a padded one.

### Pre-filter (Stage 0)

Before expensive LLM scoring, local embeddings compare each article to your profile and liked articles. Only the top ~30% proceed to scoring. KEV (actively-exploited vulnerability) articles always bypass the filter. This cuts API cost by 70-80% with minimal recall loss.

### Prompt injection hardening

Article text is wrapped in `<ARTICLE>` delimiters with explicit instructions that the content is untrusted data. The LLM is told to ignore any instructions embedded in article text.

## Configuration

### `config/profile.md`

Free-form markdown. Include:
- Who you are and what you do
- What topics you care about (be specific)
- What you're working on right now
- Tastes and anti-tastes (what to skip)
- Goals (what "a good day of reading" looks like)

### `config/settings.yaml`

All settings have defaults. Key knobs:

| Setting | Default | Description |
|---------|---------|-------------|
| `scoring_backend` | `claude` | `claude`, `ollama`, or `heuristic` |
| `use_batch` | `true` | Batch API for 50% off (Claude only) |
| `min_score` | `4` | Minimum score (0-10) to make the paper |
| `min_articles` | `5` | If fewer articles pass min_score, threshold is relaxed |
| `top_articles` | `30` | Max candidates for the editor |
| `window_days` | `10` | Rolling window for unpublished articles |
| `prefilter.keep_fraction` | `0.30` | Fraction kept by Stage 0 |
| `drop_fluff` | `true` | Exclude marketing/PR content |
| `sections` | 7 defaults | Customize to match your interests |

### `config/sources.yaml`

```yaml
feeds:
  - name: Example Blog
    url: https://example.com/feed.xml
    weight: 1.0        # default; >1 boosts, <1 dampens
    enabled: true       # set false to pause without removing
```

### `.env`

```bash
ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_WORKSPACE_ID=wrkspc_...   # only for identity-linked keys
```

## Project structure

```
frontline/
├── config.py          # settings, feeds, profile loading
├── models.py          # Article, Score, Edition dataclasses
├── store.py           # SQLite persistence (8 tables, WAL mode)
├── textutil.py        # HTML-to-text, sentence extraction
├── llm.py             # Anthropic client wrapper, cost tracking, batch API
├── embeddings.py      # FastEmbed + hashing fallback
├── editor.py          # AI newspaper composer (3 backends)
├── render.py          # Jinja2 HTML broadsheet renderer
├── discover.py        # Claude web search feed finder
├── run.py             # Pipeline orchestrator
├── cli.py             # CLI entry point
├── scoring/
│   ├── base.py        # Prompt builders, parse_judgment, Scorer protocol
│   ├── claude.py      # Claude structured output scorer
│   ├── ollama.py      # Ollama JSON mode scorer
│   ├── heuristic.py   # Profile-keyword offline fallback
│   └── fewshot.py     # Feedback → few-shot examples
├── pipeline/
│   ├── extract.py     # Full-text extraction (trafilatura)
│   ├── enrich.py      # CVE/KEV/PoC enrichment
│   ├── dedup.py       # Embedding-based clustering
│   ├── prefilter.py   # Stage 0 embedding filter
│   └── rank.py        # Composite ranking
├── sources/
│   ├── base.py        # Source adapter registry
│   ├── rss.py         # RSS/Atom adapter
│   └── cve_kev.py     # CISA KEV adapter
├── web/
│   ├── app.py         # FastAPI dashboard
│   └── templates/     # Dashboard HTML
└── templates/
    ├── edition.html.j2  # Broadsheet template
    └── index.html.j2    # Archive index
```

## Cost

With the default Claude config (Haiku triage + batch, Sonnet editor):
- **Scoring:** ~100 articles × Haiku batch = ~$0.01-0.03
- **Edition:** 1 Sonnet call = ~$0.02-0.05
- **Discovery:** ~$0.15 per run (web search + Sonnet, run occasionally)
- **Daily total:** ~$0.05-0.10

Use `frontline costs` to see your actual spend.

The Ollama and heuristic backends cost nothing.

## Scheduling a daily run

Frontline doesn't bundle a scheduler - use whatever your OS provides.

**Linux/macOS (cron):**

```bash
# Edit your crontab
crontab -e

# Add a line to run at 6:00 AM daily
0 6 * * * cd /path/to/frontline && /path/to/venv/bin/frontline run >> logs/cron.log 2>&1
```

**Windows (Task Scheduler):**

First, find where `frontline.exe` is on your system. Open a terminal and run:

```powershell
(Get-Command frontline).Source
```

Then:

1. Open Task Scheduler -> Create Basic Task
2. Trigger: Daily, 6:00 AM
3. Action: Start a Program
   - Program: the full path from the command above (e.g. `C:\Users\you\...\Scripts\frontline.exe`)
   - Arguments: `run`
   - Start in: the folder where you cloned frontline (e.g. `C:\Users\you\frontline`)

**systemd timer (Linux):**

```ini
# ~/.config/systemd/user/frontline.timer
[Unit]
Description=Daily Frontline newspaper

[Timer]
OnCalendar=06:00
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# ~/.config/systemd/user/frontline.service
[Unit]
Description=Frontline newspaper run

[Service]
Type=oneshot
WorkingDirectory=/path/to/frontline
ExecStart=/path/to/venv/bin/frontline run
```

```bash
systemctl --user enable --now frontline.timer
```

## Known limitations

- **Ollama editor:** Works but is untested end-to-end. JSON mode reliability varies by model. If the editor produces malformed JSON, the edition silently fails - check logs.
- **Heuristic edition:** No AI rewriting - uses original article titles and summaries. The editor's letter is a placeholder. Functional but plain.
- **Feed discovery** is Claude-only (requires web search tool).
- **No authentication** on the dashboard - it binds to localhost only. Don't expose `frontline serve` to the internet.

## Development

```bash
pip install -e ".[all,dev]"
pytest tests/ -v
```

51 tests covering store, scoring, pipeline, editor, web API, and discovery.

## License

MIT
