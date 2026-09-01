"""CLI entry point: frontline {init|run|serve|discover|add-source|sources|costs}"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import date
from pathlib import Path

from . import config
from .config import (CONFIG_DIR, EDITIONS_DIR, Feed, load_feeds, load_settings,
                     save_feeds)


def cmd_init(_args) -> None:
    """Set up config directory with example files."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    example_profile = CONFIG_DIR / "profile.example.md"
    profile = CONFIG_DIR / "profile.md"
    sources = CONFIG_DIR / "sources.yaml"
    settings = CONFIG_DIR / "settings.yaml"
    env_example = Path(".env.example")
    env_file = Path(".env")

    if not profile.exists() and example_profile.exists():
        shutil.copy(example_profile, profile)
        print(f"Created {profile}. Edit it with your interests.")
    elif not profile.exists():
        print(f"Warning: {example_profile} not found. Create {profile} "
              f"manually.")

    if not sources.exists():
        sources.write_text("feeds: []\n", encoding="utf-8")
        print(f"Created {sources}. Add feeds or run `frontline discover`.")

    if not settings.exists():
        print(f"Note: {settings} not found. Defaults will be used.")

    if not env_file.exists() and env_example.exists():
        shutil.copy(env_example, env_file)
        print(f"Created {env_file} from {env_example}. Add your API key.")

    print("\nSetup complete. Next steps:")
    print("  1. Edit config/profile.md with your interests")
    print("  2. Add your API key to .env (or use Ollama)")
    print("  3. Run `frontline discover` to find feeds, or add them manually")
    print("  4. Run `frontline run` to generate your first edition")


def cmd_run(args) -> None:
    """Full pipeline: collect, score, compose, render."""
    settings = load_settings()
    feeds = load_feeds()
    if not feeds:
        raise SystemExit(
            "No feeds configured. Run `frontline discover` or "
            "`frontline add-source <url>` first.")

    from .store import Store
    store = Store()
    today = args.date or date.today().isoformat()

    # Check for existing edition
    existing = store.get_editions()
    if any(e["date"] == today for e in existing) and not args.force:
        print(f"Edition {today} already exists. Use --force to rebuild.")
        return

    # Stage 1: Pipeline (collect, extract, enrich, embed, dedup, score, rank)
    from .run import run_cycle
    use_batch = not args.sync
    print(f"[1/3] Pipeline ({settings.scoring_backend} backend, "
          f"{'batch' if use_batch else 'sync'})")
    summary = run_cycle(settings, rescore=args.rescore)
    print(f"  collected={summary['collected']} new={summary['new']} "
          f"scored={summary['scored']} top={summary['top']}")

    if args.dry_run:
        print("\n[dry run] Top candidates:")
        candidates = store.candidates(settings.min_score,
                                      settings.top_articles,
                                      settings.window_days,
                                      settings.drop_fluff)
        for row in candidates:
            wscore = row["score"] * row["weight"]
            print(f"  {wscore:5.1f}  [{row['section']}] "
                  f"{row['title'][:80]}")
        return

    # Stage 2: Compose edition
    from .editor import compose_edition
    print(f"[2/3] Composing edition ({settings.scoring_backend})")
    edition = compose_edition(store, settings, use_batch=use_batch)
    if edition is None:
        raise SystemExit("No edition produced: not enough scored articles.")

    # Stage 3: Render
    from .render import render_edition
    print("[3/3] Rendering")
    edition.date = today
    out = render_edition(store, settings, edition, today)
    print(f"\nToday's paper: {out}")
    _print_cost(store, today)


def _print_cost(store, today: str) -> None:
    costs = store.costs_by_day()
    today_cost = sum(float(r["cost_usd"]) for r in costs
                     if r["day"] == today)
    if today_cost > 0:
        print(f"API spend today: ${today_cost:.4f}")


def cmd_discover(args) -> None:
    """Use Claude web search to find feeds matching your profile."""
    settings = load_settings()
    if settings.scoring_backend != "claude":
        print("Warning: feed discovery requires Claude API access.")
        print("Set scoring_backend: claude in settings.yaml, or add "
              "feeds manually.")
        return

    from .store import Store
    from .discover import discover
    store = Store()
    discover(settings, store, max_searches=args.max_searches)


def cmd_add_source(args) -> None:
    """Verify and add a single feed URL."""
    import feedparser
    print(f"Verifying {args.url} ...", end=" ", flush=True)
    parsed = feedparser.parse(args.url, agent=config.USER_AGENT)
    if not parsed.entries:
        raise SystemExit(f"\n{args.url} does not look like a working feed.")
    print("ok")

    feeds = load_feeds()
    if any(f.url == args.url for f in feeds):
        print("Already in sources.yaml.")
        return

    name = args.name or parsed.feed.get("title", args.url)
    weight = args.weight or 1.0
    feeds.append(Feed(name=name, url=args.url, weight=weight))
    save_feeds(feeds)
    print(f"Added: {name}")


def cmd_sources(_args) -> None:
    """List configured feed sources."""
    feeds = load_feeds()
    if not feeds:
        print("No feeds configured. Run `frontline discover` or "
              "`frontline add-source <url>`.")
        return
    print(f"{len(feeds)} feeds configured:\n")
    for f in feeds:
        status = "" if f.enabled else " [disabled]"
        weight = f" (weight {f.weight})" if f.weight != 1.0 else ""
        print(f"  {f.name}{weight}{status}")
        print(f"    {f.url}")


def cmd_costs(_args) -> None:
    """Show API cost ledger."""
    from .store import Store
    store = Store()
    rows = store.costs_by_day()
    if not rows:
        print("No API usage recorded yet.")
        return
    total = 0.0
    print(f"{'day':<12}{'stage':<10}{'model':<25}"
          f"{'in tok':>10}{'out tok':>10}{'cost':>10}")
    print("-" * 77)
    for row in rows:
        total += float(row["cost_usd"])
        print(f"{row['day']:<12}{row['stage']:<10}{row['model']:<25}"
              f"{row['input_tokens']:>10}{row['output_tokens']:>10}"
              f"{float(row['cost_usd']):>9.4f}$")
    print("-" * 77)
    print(f"{'':>57}{'total':>10}{total:>9.4f}$")


def cmd_serve(args) -> None:
    """Start the dashboard web server."""
    import uvicorn
    settings = load_settings()
    host = args.host or settings.web.host
    port = args.port or settings.web.port
    print(f"Starting Frontline dashboard at http://localhost:{port}/dashboard")
    uvicorn.run("frontline.web.app:app",
                host=host, port=port,
                log_level="info")


def main() -> None:
    config.load_env()
    parser = argparse.ArgumentParser(
        prog="frontline",
        description="AI-scored daily newspaper from your RSS feeds.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init",
                            help="set up config files for first use")
    p_init.set_defaults(func=cmd_init)

    # run
    p_run = sub.add_parser("run",
                           help="fetch, score, compose, and render today's edition")
    p_run.add_argument("--dry-run", action="store_true",
                       help="run pipeline only; print candidates, skip the editor")
    p_run.add_argument("--sync", action="store_true",
                       help="use synchronous API calls instead of batch")
    p_run.add_argument("--rescore", action="store_true",
                       help="re-score articles even if they already have scores")
    p_run.add_argument("--force", action="store_true",
                       help="rebuild even if today's edition exists")
    p_run.add_argument("--date",
                       help="edition date override (YYYY-MM-DD)")
    p_run.add_argument("-v", "--verbose", action="store_true",
                       help="show detailed progress (DEBUG logging)")
    p_run.set_defaults(func=cmd_run)

    # discover
    p_disc = sub.add_parser("discover",
                            help="have Claude find feeds from your profile")
    p_disc.add_argument("--max-searches", type=int, default=15,
                        help="web search cap (default 15, billed $0.01/search)")
    p_disc.set_defaults(func=cmd_discover)

    # add-source
    p_add = sub.add_parser("add-source",
                           help="verify and add a single feed URL")
    p_add.add_argument("url", help="feed URL to add")
    p_add.add_argument("--name", help="display name (auto-detected if omitted)")
    p_add.add_argument("--weight", type=float,
                       help="source weight for ranking (default 1.0)")
    p_add.set_defaults(func=cmd_add_source)

    # sources
    p_src = sub.add_parser("sources",
                           help="list configured feed sources")
    p_src.set_defaults(func=cmd_sources)

    # costs
    p_costs = sub.add_parser("costs",
                             help="show API spend from the local ledger")
    p_costs.set_defaults(func=cmd_costs)

    # serve
    p_serve = sub.add_parser("serve",
                             help="start the dashboard web server")
    p_serve.add_argument("--port", type=int, default=0,
                         help="port (default from settings.yaml, 8787)")
    p_serve.add_argument("--host", default="",
                         help="host to bind to (default from settings.yaml, 127.0.0.1)")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()

    settings = load_settings()
    level = "DEBUG" if getattr(args, "verbose", False) else settings.logging.console_level
    log_level = getattr(logging, level, logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers[0].setFormatter(logging.Formatter("%(name)s %(levelname)s: %(message)s"))

    log_dir = config.ROOT / settings.logging.dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today().isoformat()}_{args.command}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S"))
    fh.setLevel(logging.DEBUG)
    handlers.append(fh)

    logging.basicConfig(level=log_level, handlers=handlers)

    _prune_logs(log_dir, settings.logging.keep_runs)

    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        _handle_api_errors(exc)
        raise


def _prune_logs(log_dir: Path, keep: int) -> None:
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in logs[keep:]:
        old.unlink(missing_ok=True)


def _handle_api_errors(exc: Exception) -> None:
    try:
        import anthropic
    except ImportError:
        return
    if isinstance(exc, anthropic.BadRequestError) and \
            "anthropic-workspace-id" in str(exc):
        raise SystemExit(
            "\nYour API key is identity-linked and needs a workspace id.\n"
            "Add ANTHROPIC_WORKSPACE_ID=wrkspc_... to your .env "
            "(see .env.example).\nFind it in the Claude Console under "
            "Settings -> Workspaces.")
    if isinstance(exc, anthropic.AuthenticationError) or (
            isinstance(exc, (TypeError, anthropic.AnthropicError))
            and "api_key" in str(exc)):
        raise SystemExit(
            "\nNo Anthropic API credentials found.\n"
            "Set ANTHROPIC_API_KEY "
            "(https://platform.claude.com/settings/keys)\n"
            "or switch to Ollama/heuristic backend in "
            "config/settings.yaml.")


if __name__ == "__main__":
    main()
