# Browser Automation Agent — Claude Drives a Real Playwright Chromium

> **Give Claude a URL and a task; it navigates, clicks, types, scrolls, extracts data, and streams every screenshot back to a live Streamlit UI. Ships with server-side + client-side compaction so a 40-turn scrape stays under the context window.**

<p align="center"><img src="assets/hero.gif" alt="Claude driving Playwright in a Streamlit UI" width="720"></p>

<p align="center">
  <img src="https://img.shields.io/github/actions/workflow/status/Danush-Aries/browser-automation-agent/ci.yml?branch=main&style=flat-square" alt="build">
  <img src="https://img.shields.io/badge/license-MIT-00ff41?style=flat-square" alt="license">
  <img src="https://img.shields.io/badge/made%20with-Python%203.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="python">
  <img src="https://img.shields.io/badge/Playwright-2EAD33?style=flat-square&logo=playwright&logoColor=white" alt="playwright">
  <img src="https://img.shields.io/badge/Claude-Sonnet%204.6-D97757?style=flat-square&logo=anthropic&logoColor=white" alt="claude">
</p>

## Why this exists

The gap between "cool computer-use demo" and "scraper you'd trust with a 30-minute task" is context management. This repo is what an actual production-shape harness looks like: a Playwright Chromium behind a small toolset (`navigate`, `click`, `type`, `scroll`, `screenshot`, `get_text`, `fill_form`, `press_key`), prompt-cached system prompt, server-side compaction via Anthropic's `compact-2026-01-12` beta, and a client-side compaction fallback that summarises turns 1–N when the conversation crosses 20 messages. Streamlit UI shows the live page and every action Claude picks.

## Try it in 60 seconds

```bash
git clone https://github.com/Danush-Aries/browser-automation-agent.git
cd browser-automation-agent

pip install -r requirements.txt
playwright install chromium

cp .env.example .env                 # add ANTHROPIC_API_KEY
streamlit run app.py                 # http://localhost:8501
```

Docker (headless): `docker compose up --build` — set `ANTHROPIC_API_KEY` in `.env` first.

## How it works

- **`BrowserAgent.run_task()`** (in `agent/browser_agent.py`) — builds an initial message with the URL + task, then loops: call `claude-sonnet-4-6` with the tool list and history, dispatch each `tool_use` block to the matching Playwright helper, feed the result (text or PNG) back as a tool_result content block.
- **Screenshots as vision** — for `screenshot` calls the PNG is sent back as an image content block so Claude literally sees the current page state and can decide the next action.
- **DOM access** — `get_text` extracts page text with Playwright's DOM API and passes it as text; cheaper than a screenshot when Claude just needs to read.
- **Prompt caching** — system prompt uses `cache_control: ephemeral` so the setup cost is paid once per session, not per turn.
- **Two-layer compaction** — server-side `compact-2026-01-12` beta manages very long sessions transparently; a client-side fallback (in `agent/compaction.py`) summarises the first N-5 messages once the conversation exceeds 20 turns, so we never rely solely on the beta.

## Demo tasks

Click a preset in the sidebar to try the agent immediately:
- Python tutorials on Google (search + result extraction)
- Wikipedia Python article (long-form read)
- Hacker News top stories (front-page scrape)
- GitHub trending repositories
- httpbin.org contact form (form fill demo)

## Screenshots

| Streamlit UI + live browser | Action log | Docker headless mode |
|---|---|---|
| ![](assets/screenshot-1.png) | ![](assets/screenshot-2.png) | ![](assets/screenshot-3.png) |

## Features

- **Streamlit UI** — URL input, task description, live screenshot feed, action log
- **Claude controls the browser** via tools: navigate, click, type, scroll, screenshot, get_text, fill_form, press_key
- **DOM access** — extracts and passes page text to Claude
- **Smart scrolling** — detects when more content is available below
- **Prompt caching** — system prompt is cached via `cache_control` for efficiency
- **Server-side compaction** — uses `compact-2026-01-12` beta to trim long conversations
- **Client-side compaction fallback** — summarizes old messages when conversation exceeds 20 turns
- **Docker support** — Dockerfile + docker-compose.yml for headless operation

## Architecture

1. User enters a URL + task in the Streamlit UI
2. `BrowserAgent.run_task()` builds the initial message and enters the agent loop
3. Each iteration calls `claude-sonnet-4-6` with the full tool list and conversation history
4. The system prompt uses `cache_control: ephemeral` so it's cached after the first call
5. When Claude returns `tool_use` blocks, the agent dispatches to the corresponding Playwright function
6. For `screenshot` tool calls, the PNG is passed back to Claude as an image content block so it can "see" the page
7. When the conversation grows beyond 20 messages, client-side compaction summarizes the old history
8. Server-side compaction (`compact-2026-01-12` beta) automatically manages context for very long sessions

## Project structure

```
browser-automation-agent/
├── app.py                    # Streamlit UI
├── agent/
│   ├── browser_agent.py      # Main agent loop with Claude
│   ├── browser_tools.py      # Playwright tool implementations
│   └── compaction.py         # Conversation compaction logic
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Stack

Python 3.11+ · `anthropic>=0.40.0` (with `compact-2026-01-12` beta) · Playwright (Chromium) · `streamlit>=1.32.0` · `python-dotenv` · Docker + Compose.

## Contributing

PRs welcome. New tools implement one function in `agent/browser_tools.py` matching the Anthropic tool schema — `browser_agent.py` dispatches automatically on the tool name. Compaction strategies plug into `agent/compaction.py` as `summarise(messages) → messages`.

## License

MIT — see [LICENSE](./LICENSE).

---

### More from Danush

- [ponytail-for-python](https://github.com/Danush-Aries/ponytail-for-python) — code intelligence for Python codebases
- [Agentic_Systems](https://github.com/Danush-Aries/Agentic_Systems) — reference implementations of agent patterns
- [autonomous-coding-agent](https://github.com/Danush-Aries/autonomous-coding-agent) — full-auto engineering agent
- [computer-use-agent](https://github.com/Danush-Aries/computer-use-agent) — Claude drives your desktop via VNC
- [browser-automation-agent](https://github.com/Danush-Aries/browser-automation-agent) — Claude drives Playwright
- [blinkchat](https://github.com/Danush-Aries/blinkchat) — realtime chat with vibes
