"""
Streamlit UI for the Browser Automation Agent.

Provides:
- URL input field
- Task description textarea
- Demo task quick-fill buttons
- Live screenshot feed (updates each time Claude takes a screenshot)
- Action log with tool call details
- Cache statistics
"""

import asyncio
import base64
import json
import os
import sys
import threading
from queue import Queue, Empty

import streamlit as st
from dotenv import load_dotenv

# Load .env file for ANTHROPIC_API_KEY
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from agent.browser_agent import BrowserAgent

# ---------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------
st.set_page_config(
    page_title="Browser Automation Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #00d4ff, #7b2fff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        margin: 2px;
    }
    .badge-running { background: #1a4a2e; color: #4caf50; border: 1px solid #4caf50; }
    .badge-done { background: #1a3a4a; color: #2196f3; border: 1px solid #2196f3; }
    .badge-error { background: #4a1a1a; color: #f44336; border: 1px solid #f44336; }
    .action-log-entry {
        font-family: monospace;
        font-size: 0.8rem;
        padding: 4px 8px;
        margin: 2px 0;
        border-radius: 4px;
        border-left: 3px solid;
    }
    .log-navigate { border-color: #2196f3; background: #0d2137; }
    .log-click { border-color: #ff9800; background: #1a1200; }
    .log-type { border-color: #4caf50; background: #0d2010; }
    .log-screenshot { border-color: #9c27b0; background: #1a0d24; }
    .log-scroll { border-color: #00bcd4; background: #0d1f24; }
    .log-get_text { border-color: #607d8b; background: #111c24; }
    .log-other { border-color: #555; background: #111; }
    .screenshot-container {
        border: 2px solid #333;
        border-radius: 8px;
        overflow: hidden;
        background: #000;
    }
    .cache-stats {
        font-size: 0.8rem;
        color: #888;
        padding: 4px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------
def init_session_state():
    if "agent" not in st.session_state:
        st.session_state.agent = None
    if "running" not in st.session_state:
        st.session_state.running = False
    if "screenshots" not in st.session_state:
        st.session_state.screenshots = []
    if "action_log" not in st.session_state:
        st.session_state.action_log = []
    if "status_messages" not in st.session_state:
        st.session_state.status_messages = []
    if "final_result" not in st.session_state:
        st.session_state.final_result = ""
    if "error_message" not in st.session_state:
        st.session_state.error_message = ""
    if "cache_hits" not in st.session_state:
        st.session_state.cache_hits = 0
    if "cache_misses" not in st.session_state:
        st.session_state.cache_misses = 0
    if "headless" not in st.session_state:
        st.session_state.headless = True

init_session_state()

# ---------------------------------------------------------------
# Helper: run agent in background thread with asyncio event loop
# ---------------------------------------------------------------

def _run_agent_sync(url: str, task: str, event_queue: Queue, headless: bool):
    """Run the agent in a background thread with its own event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run():
        agent = BrowserAgent(headless=headless)
        try:
            await agent.start()
            async for event in agent.run_task(url or None, task):
                event_queue.put(event)
        except Exception as e:
            event_queue.put({"type": "error", "message": str(e)})
        finally:
            await agent.stop()
            event_queue.put({"type": "_sentinel"})

    loop.run_until_complete(_run())
    loop.close()


# ---------------------------------------------------------------
# Demo tasks
# ---------------------------------------------------------------
DEMO_TASKS = {
    "Python tutorials on Google": {
        "url": "https://www.google.com",
        "task": "Search for 'Python tutorials for beginners' and list the top 5 results with their titles and URLs."
    },
    "Wikipedia Python page": {
        "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "task": "Get the introduction section and list the key features of Python mentioned on the page."
    },
    "Hacker News top stories": {
        "url": "https://news.ycombinator.com",
        "task": "List the top 10 stories on Hacker News with their titles and point counts."
    },
    "GitHub trending repos": {
        "url": "https://github.com/trending",
        "task": "List the top 5 trending repositories on GitHub with their descriptions and star counts."
    },
    "Contact form demo": {
        "url": "https://httpbin.org/forms/post",
        "task": "Fill out the contact form with the following information: Customer name='John Doe', Telephone='555-1234', Email='john@example.com', Quantity='2', Comments='This is a test submission'. Then describe what you filled in (but do not actually submit)."
    },
}

# ---------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------
st.markdown('<div class="main-header">Browser Automation Agent</div>', unsafe_allow_html=True)
st.caption("Powered by Claude claude-sonnet-4-6 + Playwright")

# Check API key
if not os.environ.get("ANTHROPIC_API_KEY"):
    st.error(
        "ANTHROPIC_API_KEY not found. Create a `.env` file with `ANTHROPIC_API_KEY=your-key-here` "
        "or set the environment variable before running."
    )

# ---------------------------------------------------------------
# Sidebar — configuration and demo tasks
# ---------------------------------------------------------------
with st.sidebar:
    st.header("Configuration")

    headless = st.checkbox(
        "Headless browser",
        value=True,
        help="Run browser without a visible window (required in Docker)"
    )
    st.session_state.headless = headless

    st.divider()
    st.header("Demo Tasks")
    st.caption("Click to auto-fill URL and task:")

    for demo_name, demo_config in DEMO_TASKS.items():
        if st.button(demo_name, use_container_width=True):
            st.session_state["demo_url"] = demo_config["url"]
            st.session_state["demo_task"] = demo_config["task"]
            st.rerun()

    st.divider()

    # Cache statistics
    if st.session_state.cache_hits > 0 or st.session_state.cache_misses > 0:
        st.header("Cache Statistics")
        total = st.session_state.cache_hits + st.session_state.cache_misses
        hit_rate = (st.session_state.cache_hits / total * 100) if total > 0 else 0
        st.metric("Cache Hits", st.session_state.cache_hits)
        st.metric("Cache Misses", st.session_state.cache_misses)
        st.metric("Hit Rate", f"{hit_rate:.0f}%")

    st.divider()
    st.caption("Built with Anthropic SDK + Playwright + Streamlit")

# ---------------------------------------------------------------
# Main content area — two columns
# ---------------------------------------------------------------
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("Task Configuration")

    # URL input
    default_url = st.session_state.get("demo_url", "")
    url = st.text_input(
        "Start URL (optional)",
        value=default_url,
        placeholder="https://example.com",
        help="Leave blank to start without navigating anywhere"
    )

    # Task description
    default_task = st.session_state.get("demo_task", "")
    task = st.text_area(
        "Task Description",
        value=default_task,
        height=120,
        placeholder="Describe what you want Claude to do in the browser...",
        help="Be specific about what to search for, click, or extract"
    )

    # Control buttons
    btn_col1, btn_col2 = st.columns(2)

    with btn_col1:
        run_clicked = st.button(
            "Run Agent",
            type="primary",
            disabled=st.session_state.running or not task.strip(),
            use_container_width=True
        )

    with btn_col2:
        clear_clicked = st.button(
            "Clear Results",
            disabled=st.session_state.running,
            use_container_width=True
        )

    if clear_clicked:
        st.session_state.screenshots = []
        st.session_state.action_log = []
        st.session_state.status_messages = []
        st.session_state.final_result = ""
        st.session_state.error_message = ""
        st.session_state.cache_hits = 0
        st.session_state.cache_misses = 0
        st.session_state.pop("demo_url", None)
        st.session_state.pop("demo_task", None)
        st.rerun()

    # Status area
    if st.session_state.running:
        st.markdown('<span class="status-badge badge-running">Running...</span>', unsafe_allow_html=True)
    elif st.session_state.error_message:
        st.error(st.session_state.error_message)
    elif st.session_state.final_result:
        st.markdown('<span class="status-badge badge-done">Done</span>', unsafe_allow_html=True)

    # Final result
    if st.session_state.final_result:
        st.subheader("Result")
        st.markdown(st.session_state.final_result)

    # Status messages
    if st.session_state.status_messages:
        with st.expander("Status Log", expanded=False):
            for msg in st.session_state.status_messages[-20:]:
                st.caption(msg)

with col_right:
    st.subheader("Live Browser View")

    # Screenshot display
    screenshot_placeholder = st.empty()

    if st.session_state.screenshots:
        latest = st.session_state.screenshots[-1]
        screenshot_placeholder.image(
            base64.b64decode(latest),
            caption=f"Screenshot {len(st.session_state.screenshots)}",
            use_container_width=True,
        )
    else:
        screenshot_placeholder.info("Screenshots will appear here when the agent runs.")

    # Screenshot counter
    if st.session_state.screenshots:
        st.caption(f"Total screenshots: {len(st.session_state.screenshots)}")

    # Action log
    st.subheader("Action Log")
    action_log_placeholder = st.empty()

    def render_action_log():
        if not st.session_state.action_log:
            action_log_placeholder.info("Tool calls will appear here during execution.")
            return

        log_html = []
        for entry in st.session_state.action_log[-30:]:  # show last 30 entries
            tool = entry.get("tool", "other")
            text = entry.get("text", "")
            css_class = f"log-{tool}" if tool in ["navigate", "click", "type", "screenshot", "scroll", "get_text"] else "log-other"
            # Escape for HTML
            text_escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            log_html.append(f'<div class="action-log-entry {css_class}">{text_escaped}</div>')

        action_log_placeholder.markdown(
            "<div>" + "".join(log_html) + "</div>",
            unsafe_allow_html=True,
        )

    render_action_log()

# ---------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------
if run_clicked and task.strip():
    # Reset state
    st.session_state.running = True
    st.session_state.screenshots = []
    st.session_state.action_log = []
    st.session_state.status_messages = []
    st.session_state.final_result = ""
    st.session_state.error_message = ""
    st.session_state.cache_hits = 0
    st.session_state.cache_misses = 0

    # Start agent in background thread
    event_queue = Queue()
    thread = threading.Thread(
        target=_run_agent_sync,
        args=(url.strip(), task.strip(), event_queue, headless),
        daemon=True,
    )
    thread.start()

    # Process events
    progress_placeholder = st.empty()

    while True:
        try:
            event = event_queue.get(timeout=60)
        except Empty:
            st.session_state.error_message = "Timed out waiting for agent response."
            break

        if event["type"] == "_sentinel":
            break

        elif event["type"] == "status":
            msg = event["message"]
            st.session_state.status_messages.append(msg)
            progress_placeholder.caption(f"Status: {msg}")

        elif event["type"] == "screenshot":
            st.session_state.screenshots.append(event["data"])
            # Update live view
            screenshot_placeholder.image(
                base64.b64decode(event["data"]),
                caption=f"Screenshot {len(st.session_state.screenshots)}",
                use_container_width=True,
            )

        elif event["type"] == "tool_call":
            name = event["name"]
            inp = event.get("input", {})

            # Format log entry
            if name == "navigate":
                log_text = f"Navigate → {inp.get('url', '')}"
                log_tool = "navigate"
            elif name == "click":
                sel = inp.get("selector") or inp.get("text", "")
                log_text = f"Click → {sel}"
                log_tool = "click"
            elif name == "type_text":
                text_val = inp.get("text", "")[:40]
                log_text = f"Type → '{text_val}...' into {inp.get('selector', '')}"
                log_tool = "type"
            elif name == "screenshot":
                log_text = "Screenshot"
                log_tool = "screenshot"
            elif name == "scroll":
                log_text = f"Scroll {inp.get('direction', 'down')} {inp.get('amount', 300)}px"
                log_tool = "scroll"
            elif name == "get_text":
                sel = inp.get("selector", "page")
                log_text = f"Get text from {sel}"
                log_tool = "get_text"
            elif name == "fill_form":
                n = len(inp.get("fields", []))
                log_text = f"Fill form ({n} fields)"
                log_tool = "other"
            elif name == "press_key":
                log_text = f"Press key: {inp.get('key', '')}"
                log_tool = "other"
            elif name == "get_page_info":
                log_text = "Get page info"
                log_tool = "other"
            else:
                log_text = f"{name}({json.dumps(inp)[:60]})"
                log_tool = "other"

            st.session_state.action_log.append({"tool": log_tool, "text": log_text})
            render_action_log()

        elif event["type"] == "tool_result":
            result = event.get("result", {})
            if not result.get("success", True):
                err = result.get("error", "unknown error")
                st.session_state.action_log.append({
                    "tool": "other",
                    "text": f"  Error: {err[:80]}"
                })
                render_action_log()

        elif event["type"] == "text":
            # Show Claude's running commentary in status
            text = event["text"]
            st.session_state.status_messages.append(f"Claude: {text[:200]}")
            st.session_state.final_result = text  # keep last text as the final result

        elif event["type"] == "compacted":
            st.session_state.action_log.append({
                "tool": "other",
                "text": f"[Compacted conversation history]"
            })

        elif event["type"] == "cache_stats":
            st.session_state.cache_hits = event.get("hits", 0)
            st.session_state.cache_misses = event.get("misses", 0)

        elif event["type"] == "error":
            st.session_state.error_message = event["message"]

        elif event["type"] == "done":
            final = event.get("final_text", "")
            if final:
                st.session_state.final_result = final

    # Cleanup
    st.session_state.running = False
    progress_placeholder.empty()
    thread.join(timeout=5)
    st.rerun()
