# ohayo-ai (おはようAI)

A beginner-friendly Japanese AI news site that rebuilds itself every morning. GitHub Actions collects AI news from primary sources, an LLM ranks and summarizes up to 20 items in plain Japanese, Python renders static HTML into `public/`, and Cloudflare Workers (static assets only) serves it at `ohayo-ai.<account>.workers.dev`. The site doubles as an AILEAP showcase: "this is what AI automation can do for you."

Talk to the user in Japanese.

## Source of truth

- `docs/requirements.md` — requirements v2 (Japanese). Read the relevant section before any feature work. It overrides v1.
- `docs/requirements-v1.md` — the original draft. History only.
- `docs/design/` — top page and mascot design. `docs/design/README.md` explains how to read the `.dc.html` files and lists colors, fonts, mascot moods and layout.

If code and docs disagree, ask before changing either.

## Hard constraints

- **$0 running cost.** Free tiers only: GitHub Actions on a public repo, Cloudflare Workers static assets, Gemini API free tier, Groq free tier as fallback. Never add a paid service or a dependency that needs one.
- **No server code on Workers.** `wrangler.jsonc` sets `assets.directory` to `./public` and nothing else runs. No `main` script.
- **Pre-rendered HTML.** Python (Jinja2) writes every page. JavaScript is progressive enhancement only (tab filter, term bottom sheet, mascot motion, reading streak). Every page must be readable with JS off.
- **Copy rules.** Summaries in our own short words with a link to the primary source. Never translate a full article. Never reuse images from source articles.
- **Secrets** live only in GitHub Actions secrets (`GEMINI_API_KEY`, `GROQ_API_KEY`). Never commit keys or `.env`. Do not run workflows on pull requests from forks.

## Stack and conventions

- Python 3.12+, managed with **uv** (`pyproject.toml` + `uv.lock`). Never use pip or `requirements.txt`.
- Planned libraries: feedparser, httpx, trafilatura, jinja2, pydantic, openai (OpenAI-compatible client for both Gemini and Groq), lxml (HTML/feed parsing), pillow (daily OGP image, drawn with the bundled `templates/fonts/` M PLUS Rounded 1c, SIL OFL).
- Frontend: hand-written CSS and vanilla JS. No Tailwind, no frameworks, no animation libraries.
- Fonts: system Japanese gothic for body text; M PLUS Rounded 1c (Google Fonts, weights 700/800) for headings and mascot speech only.
- All user-facing text is Japanese, aimed at non-engineers. Code, identifiers, comments and commit messages are English.
- Generated files go only to `public/` and `data/`. Templates live in `templates/`.

## Pipeline (requirements: 記事選定パイプライン, LLM構成)

collect last 36h from 10 sources → dedupe against `data/seen.json` (7 days) and by title similarity → rule filter to ~60 → **1** LLM ranking call (score 1–5 + category) → keep up to 20 with score ≥ 3 → fetch body with trafilatura (first 6,000 chars) → **20** summary calls → **1** daily-summary call (3-line digest, AI weather, mascot line) → render → commit only if something changed.

- LLM budget: 22 calls per day. Do not add calls without updating the requirements.
- Provider switch via `LLM_PROVIDER` (`gemini` | `groq`). Primary: Gemini 3.5 Flash-Lite. Fallback: Groq `qwen/qwen3.8-27b` with thinking off; its 8K TPM limit means pacing to about 2 requests per minute.
- Retry once, then fall back to the other provider.
- Validate every LLM output with Pydantic, then: reject simplified-Chinese characters, drop numbers that do not appear in the source text, enforce field length limits.
- Categories are fixed: 注目トピック / 画像・動画 / 便利なツール / 新モデル / 研究・論文.
- A source that returns 0 items two days in a row fails the run so the owner gets GitHub's failure email.

## Mascot: ニュー助 (Nyusuke)

Mint-colored round robot with an antenna and a chest screen. Four moods (normal, surprised, smile, thinking) differ only in eyes and mouth; exact shapes are in `docs/design/README.md`. Motion rules: reading content (titles, summaries) never animates; the only infinite loop is blinking; honor `prefers-reduced-motion`.

## Testing

- pytest. Tests never hit the network or an LLM API. Use recorded fixtures under `tests/fixtures/`.
- Provide a `--dry-run` mode that runs the whole pipeline on fixtures and renders `public/` locally.

## Development phases

1. **Scaffold**: `pyproject.toml`, `src/ai_news/` layout, `wrangler.jsonc`, `.gitignore`, workflow skeleton with `workflow_dispatch` only.
2. **Collectors**: one module per source, each with fixtures and tests; dedupe and state files in `data/`.
3. **LLM layer**: provider abstraction, schemas, ranking, summarizing, validation, dry-run with recorded responses.
4. **Rendering**: port `docs/design/top-page.dc.html` to Jinja2 templates + `public/assets/style.css` + `app.js`; then archive, glossary, `/behind/`, 404 and the daily OGP image.
5. **Automation**: schedule the workflow (`17 21 * * *` UTC = 06:17 JST), commit-if-changed, connect Workers Builds, add the Web Analytics snippet.

Finish and verify each phase before starting the next. Record real commands in a "Commands" section here as they are created.

## Operations

Public URL: https://ohayo-ai.aileap.workers.dev (workers.dev subdomain `aileap`; the `ohayo-ai` Worker was first created by a manual `npx wrangler deploy` on 2026-10-09, so Workers Builds is attached through the Worker's Settings → Builds → Connect).

`docs/operations.md` (Japanese, for the owner) covers first-time setup (Secrets, Workers Builds, `SITE_URL` and `CF_WEB_ANALYTICS_TOKEN` repository variables) and what to do when the morning run fails.

- `.github/workflows/update-news.yml`: daily at `17 21 * * *` UTC and on manual dispatch. Runs `ai-news`, commits `data/` and `public/` only if they changed (even when the pipeline failed, so state keeps moving), then fails the run if `ai-news` exited non-zero. No tests here, so a test failure never blocks the morning edition. Dispatch with `dry_run` commits nothing.
- `.github/workflows/ci.yml`: `pytest` on pushes to `main` that touch code. Bot commits made with `GITHUB_TOKEN` do not trigger it.
- Both jobs only run in `appdevelopmentworks/ohayo-ai`; neither has a `pull_request` trigger.

## Commands

- `uv sync` — create `.venv` and install dependencies (CI uses `uv sync --locked`)
- `uv add <pkg>` / `uv add --dev <pkg>` — add a dependency (updates `pyproject.toml` and `uv.lock`)
- `uv run pytest` — run the test suite
- `uv run ai-news --dry-run` — run the pipeline on recorded sources and LLM answers (`tests/fixtures/`) and render `public/` from it plus existing `data/`; never writes `data/` (add `-v` to list articles); also `uv run python -m ai_news`. Do not commit the `public/` it produces
- `uv run ai-news` — live run (needs `GEMINI_API_KEY` and/or `GROQ_API_KEY`): writes `data/daily/<JST date>.json`, `data/seen.json`, `data/source_health.json`, `data/glossary.json`, then renders `public/`; exits 1 if no edition was made or a source returned 0 items two JST days in a row
- `uv run ai-news --render-only` — rebuild `public/` from `data/` (after template or CSS changes)
- `SITE_URL=https://ohayo-ai.<account>.workers.dev` — env var for canonical and `og:image` URLs; without it those tags are omitted
- `CF_WEB_ANALYTICS_TOKEN=<32 hex chars>` — env var that adds the Cloudflare Web Analytics beacon to every page; omitted when unset or malformed
- `uv run python -m http.server 8000 --directory public` — preview the rendered site (also the `public` entry in `.claude/launch.json`)
- `uv run ai-news --record-fixtures` — re-fetch every source into `tests/fixtures/sources/` (feeds trimmed to 40 entries); the LLM fixtures then no longer match, so follow with `--record-llm`
- `uv run ai-news --record-llm` — call the real LLMs on the recorded sources (feed text as the body, like `--dry-run`) and save answers to `tests/fixtures/llm/`; delete stale `summary-*.json` first
- `uv run ai-news --provider groq` — choose the primary LLM provider (default: `$LLM_PROVIDER` or `gemini`)

## Open items

- AILEAP contact URL for the 「AILEAPに相談する」 button (not decided yet; leave a TODO, never invent a URL).
