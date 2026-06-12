# Browser Automation Agent

A Claude-powered browser automation agent with a live Streamlit UI. Claude controls a real Playwright browser to navigate, click, type, scroll, and extract data from web pages.

## Features

- **Streamlit UI** — URL input, task description, live screenshot feed, action log
- **Claude controls the browser** via tools: navigate, click, type, scroll, screenshot, get_text, fill_form, press_key
- **DOM access** — extracts and passes page text to Claude
- **Smart scrolling** — detects when more content is available below
- **Prompt caching** — system prompt is cached via `cache_control` for efficiency
- **Server-side compaction** — uses `compact-2026-01-12` beta to trim long conversations
- **Client-side compaction fallback** — summarizes old messages when conversation exceeds 20 turns
- **Docker support** — includes Dockerfile and docker-compose.yml for headless operation

## Quick Start

### 1. Install dependencies

```bash
cd browser-automation-agent
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure API key

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 3. Run

```bash
streamlit run app.py
```

Open http://localhost:8501

## Demo Tasks

Click any demo button in the sidebar:

- **Python tutorials on Google** — searches Google and lists top results
- **Wikipedia Python page** — reads the Python article
- **Hacker News top stories** — scrapes HN front page
- **GitHub trending repos** — reads trending repositories
- **Contact form demo** — fills out a form on httpbin.org

## Docker

```bash
# Set your API key in .env first
docker compose up --build
```

## File Structure

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

## Architecture

1. User enters a URL + task in the Streamlit UI
2. `BrowserAgent.run_task()` builds the initial message and enters the agent loop
3. Each iteration calls `claude-sonnet-4-6` with the full tool list and conversation history
4. The system prompt uses `cache_control: ephemeral` so it's cached after the first call
5. When Claude returns `tool_use` blocks, the agent dispatches to the corresponding Playwright function
6. For `screenshot` tool calls, the PNG is passed back to Claude as an image content block so it can "see" the page
7. When the conversation grows beyond 20 messages, client-side compaction summarizes the old history
8. Server-side compaction (`compact-2026-01-12` beta) automatically manages context for very long sessions
