"""
Main Browser Agent loop.

Manages the conversation with Claude (claude-sonnet-4-6), executes Playwright
tool calls, applies prompt caching on the system prompt, and performs
server-side (and client-side fallback) compaction when conversations grow long.
"""

import asyncio
import base64
import json
import os
from typing import AsyncGenerator, Optional

import anthropic

from agent.browser_tools import BrowserTools
from agent.compaction import (
    MAX_MESSAGES,
    compact_messages,
    needs_client_compaction,
    build_server_compaction_request,
)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
MAX_ITERATIONS = 40  # safety limit per task

# ---------------------------------------------------------------
# System prompt — cached via cache_control so it only pays full
# price once per session and subsequent turns use the cached version.
# ---------------------------------------------------------------
SYSTEM_PROMPT_TEXT = """You are an expert browser automation agent. You control a real Chromium browser via Playwright tools to complete web tasks accurately and efficiently.

## Your capabilities
You have access to these browser tools:
- navigate(url): Go to a URL
- screenshot(): Take a screenshot and see what the page looks like (returns base64 PNG image)
- click(selector, text): Click an element by CSS selector or by its visible text
- type_text(selector, text): Type into an input field
- scroll(direction, amount): Scroll up or down; returns whether more content exists
- get_text(selector, max_chars): Extract text from the page or a specific element
- fill_form(fields): Fill multiple form fields at once
- get_page_info(): Get current URL, title, and page structure
- press_key(key): Press a keyboard key (Enter, Tab, Escape, etc.)
- wait_for_element(selector, timeout): Wait for an element to appear

## How to work
1. Start by taking a screenshot to see the current page state
2. Use get_page_info() to understand the page structure before interacting
3. Take screenshots after important actions to verify they worked
4. Use get_text() to read page content — it's cheaper than screenshots for text-heavy pages
5. For search: navigate to the site, find the search box, type, press Enter or click Search
6. For forms: use fill_form() to fill multiple fields at once, then click the submit button
7. After clicking navigation links, wait briefly for the page to load
8. If an action fails, try an alternative approach (different selector, scroll to reveal)
9. Report what you found, what actions you took, and the outcome clearly

## Smart scrolling
- scroll() returns "more_content: true/false" — use this to know if there's more to see
- Scroll to explore long pages, especially search results
- Don't scroll more than needed

## Error handling
- If a selector fails, try variations: #id, .class, input[type=text], [placeholder="Search"], etc.
- For Google search: the search box is typically textarea[name="q"] or input[name="q"]
- For navigation, try clicking by text if selectors are complex

## Communication
- Narrate what you're doing: "I'll search for... / I'm clicking... / I found..."
- Summarize findings clearly at the end
- If you can't complete a task, explain what you tried and why it failed

Always be precise and thorough. Complete the task fully before stopping."""


def _build_system_with_cache() -> list[dict]:
    """Build the system prompt with cache_control for prompt caching."""
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT_TEXT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _build_tools_for_api() -> list[dict]:
    """Get tool definitions — deterministic ordering ensures stable cache prefix."""
    tools = BrowserTools.get_tool_definitions()
    # Sort deterministically to avoid cache invalidation
    return sorted(tools, key=lambda t: t["name"])


class BrowserAgent:
    """
    Manages the Claude + Playwright agent loop.

    Usage:
        agent = BrowserAgent(headless=True)
        await agent.start()
        async for event in agent.run_task(url, task_description):
            # event is {"type": "...", ...}
        await agent.stop()
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._tools_obj = BrowserTools(headless=headless)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._messages: list[dict] = []
        self._system = _build_system_with_cache()
        self._tools = _build_tools_for_api()
        self._running = False
        self._cache_stats = {"hits": 0, "misses": 0}

    async def start(self):
        """Start the Playwright browser."""
        await self._tools_obj.start()
        self._running = True

    async def stop(self):
        """Stop the browser and clean up."""
        await self._tools_obj.stop()
        self._running = False
        self._messages.clear()

    async def reset(self):
        """Reset conversation and browser state for a new task."""
        await self._tools_obj.stop()
        await self._tools_obj.start()
        self._messages.clear()
        self._tools_obj.clear_log()

    def get_action_log(self) -> list[dict]:
        return self._tools_obj.get_action_log()

    def get_cache_stats(self) -> dict:
        return dict(self._cache_stats)

    # ---------------------------------------------------------------
    # Tool dispatch
    # ---------------------------------------------------------------

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return the result string."""
        try:
            if tool_name == "navigate":
                return await self._tools_obj.navigate(tool_input.get("url", ""))
            elif tool_name == "screenshot":
                return await self._tools_obj.screenshot()
            elif tool_name == "click":
                return await self._tools_obj.click(
                    tool_input.get("selector", ""),
                    tool_input.get("text"),
                )
            elif tool_name == "type_text":
                return await self._tools_obj.type_text(
                    tool_input.get("selector", ""),
                    tool_input.get("text", ""),
                    tool_input.get("clear_first", True),
                )
            elif tool_name == "scroll":
                return await self._tools_obj.scroll(
                    tool_input.get("direction", "down"),
                    tool_input.get("amount", 300),
                )
            elif tool_name == "get_text":
                return await self._tools_obj.get_text(
                    tool_input.get("selector"),
                    tool_input.get("max_chars", 5000),
                )
            elif tool_name == "fill_form":
                return await self._tools_obj.fill_form(
                    tool_input.get("fields", [])
                )
            elif tool_name == "get_page_info":
                return await self._tools_obj.get_page_info()
            elif tool_name == "press_key":
                return await self._tools_obj.press_key(tool_input.get("key", "Enter"))
            elif tool_name == "wait_for_element":
                return await self._tools_obj.wait_for_element(
                    tool_input.get("selector", ""),
                    tool_input.get("timeout", 10000),
                )
            else:
                return json.dumps({"success": False, "error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    # ---------------------------------------------------------------
    # Main agent loop
    # ---------------------------------------------------------------

    async def run_task(
        self,
        start_url: Optional[str],
        task_description: str,
    ) -> AsyncGenerator[dict, None]:
        """
        Run a browser automation task.

        Yields event dicts:
          {"type": "status", "message": str}
          {"type": "screenshot", "data": base64_str}
          {"type": "tool_call", "name": str, "input": dict}
          {"type": "tool_result", "name": str, "result": dict}
          {"type": "thinking", "text": str}
          {"type": "text", "text": str}
          {"type": "done", "final_text": str}
          {"type": "error", "message": str}
          {"type": "cache_stats", "hits": int, "misses": int}
          {"type": "compacted", "message": str}
        """
        # Reset for new task
        self._messages.clear()
        self._tools_obj.clear_log()
        self._cache_stats = {"hits": 0, "misses": 0}

        # Build initial user message
        user_content = []
        if start_url:
            user_content.append({
                "type": "text",
                "text": f"Please navigate to {start_url} and then: {task_description}"
            })
        else:
            user_content.append({"type": "text", "text": task_description})

        self._messages.append({"role": "user", "content": user_content})

        yield {"type": "status", "message": f"Starting task: {task_description}"}

        iteration = 0
        final_text = ""

        try:
            while iteration < MAX_ITERATIONS:
                iteration += 1
                yield {"type": "status", "message": f"Claude thinking... (step {iteration})"}

                # Check if client-side compaction is needed
                if needs_client_compaction(self._messages):
                    yield {"type": "compacted", "message": "Compacting conversation history..."}
                    self._messages = compact_messages(
                        self._client, self._messages, MODEL, SYSTEM_PROMPT_TEXT
                    )

                # Call Claude API — use server-side compaction (beta)
                try:
                    response = build_server_compaction_request(
                        client=self._client,
                        model=MODEL,
                        system=self._system,
                        tools=self._tools,
                        messages=self._messages,
                        max_tokens=MAX_TOKENS,
                    )
                except anthropic.BadRequestError:
                    # Fall back to standard (non-beta) call if compaction beta unavailable
                    response = self._client.messages.create(
                        model=MODEL,
                        max_tokens=MAX_TOKENS,
                        system=self._system,
                        tools=self._tools,
                        messages=self._messages,
                    )

                # Track cache statistics
                if hasattr(response, "usage"):
                    usage = response.usage
                    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
                    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
                    if cache_read > 0:
                        self._cache_stats["hits"] += 1
                    elif cache_create > 0:
                        self._cache_stats["misses"] += 1
                    yield {
                        "type": "cache_stats",
                        "hits": self._cache_stats["hits"],
                        "misses": self._cache_stats["misses"],
                        "cache_read_tokens": cache_read,
                        "cache_write_tokens": cache_create,
                    }

                # Process response content blocks
                tool_use_blocks = []
                text_blocks = []

                for block in response.content:
                    block_type = getattr(block, "type", None)

                    if block_type == "text":
                        text = block.text
                        if text.strip():
                            text_blocks.append(text)
                            final_text = text
                            yield {"type": "text", "text": text}

                    elif block_type == "thinking":
                        thinking = getattr(block, "thinking", "")
                        if thinking:
                            yield {"type": "thinking", "text": thinking}

                    elif block_type == "tool_use":
                        tool_use_blocks.append(block)
                        tool_input = dict(block.input) if hasattr(block.input, "items") else block.input
                        yield {
                            "type": "tool_call",
                            "name": block.name,
                            "input": tool_input,
                        }

                # Append assistant response (IMPORTANT: preserve full content for compaction)
                self._messages.append({
                    "role": "assistant",
                    "content": response.content,
                })

                # If no tool calls, Claude is done
                if response.stop_reason == "end_turn" and not tool_use_blocks:
                    break

                if response.stop_reason == "refusal":
                    yield {"type": "error", "message": "Claude refused the request."}
                    break

                # Execute all tool calls and collect results
                if tool_use_blocks:
                    tool_results = []
                    for tool_block in tool_use_blocks:
                        tool_name = tool_block.name
                        tool_input = dict(tool_block.input) if hasattr(tool_block.input, "items") else tool_block.input

                        yield {"type": "status", "message": f"Executing: {tool_name}"}
                        result_str = await self._execute_tool(tool_name, tool_input)

                        try:
                            result_data = json.loads(result_str)
                        except Exception:
                            result_data = {"raw": result_str}

                        yield {
                            "type": "tool_result",
                            "name": tool_name,
                            "result": result_data,
                        }

                        # For screenshot results, also emit the image separately for the UI
                        if tool_name == "screenshot" and result_data.get("success"):
                            b64 = result_data.get("image_base64", "")
                            if b64:
                                yield {"type": "screenshot", "data": b64}

                        # Build tool result content for the API
                        # For screenshot: include the actual image so Claude can see it
                        if tool_name == "screenshot" and result_data.get("success"):
                            tool_result_content = [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": result_data["image_base64"],
                                    }
                                }
                            ]
                        else:
                            # For other tools: send back the JSON result as text
                            tool_result_content = result_str

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": tool_result_content,
                        })

                    # Append tool results as user message
                    self._messages.append({
                        "role": "user",
                        "content": tool_results,
                    })

            if iteration >= MAX_ITERATIONS:
                yield {"type": "status", "message": f"Reached maximum iterations ({MAX_ITERATIONS})."}

        except anthropic.AuthenticationError:
            yield {"type": "error", "message": "Invalid API key. Set ANTHROPIC_API_KEY in your .env file."}
        except anthropic.RateLimitError as e:
            yield {"type": "error", "message": f"Rate limited: {e}. Please wait and try again."}
        except anthropic.APIStatusError as e:
            yield {"type": "error", "message": f"API error ({e.status_code}): {e.message}"}
        except Exception as e:
            yield {"type": "error", "message": f"Unexpected error: {str(e)}"}
        finally:
            yield {"type": "done", "final_text": final_text}
            yield {
                "type": "cache_stats",
                "hits": self._cache_stats["hits"],
                "misses": self._cache_stats["misses"],
            }
