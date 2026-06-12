"""
Playwright browser tool implementations for the Browser Automation Agent.
Each function maps to a Claude tool and controls a real Playwright browser.
"""

import asyncio
import base64
import json
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class BrowserTools:
    """Manages a Playwright browser instance and exposes tool functions for Claude."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._action_log: list[dict] = []

    async def start(self):
        """Launch the browser and create a page."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        self._log("browser_started", {"headless": self.headless})

    async def stop(self):
        """Close the browser cleanly."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    def _log(self, action: str, details: dict):
        entry = {"action": action, "details": details}
        self._action_log.append(entry)

    def get_action_log(self) -> list[dict]:
        return list(self._action_log)

    def clear_log(self):
        self._action_log.clear()

    # ---------------------------------------------------------------
    # Tool implementations
    # ---------------------------------------------------------------

    async def navigate(self, url: str) -> str:
        """Navigate the browser to a URL."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            response = await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            status = response.status if response else "unknown"
            title = await self._page.title()
            current_url = self._page.url
            self._log("navigate", {"url": url, "status": status, "title": title})
            return json.dumps({"success": True, "url": current_url, "title": title, "status": status})
        except Exception as e:
            self._log("navigate_error", {"url": url, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    async def screenshot(self) -> str:
        """Take a screenshot of the current page and return as base64."""
        try:
            png_bytes = await self._page.screenshot(type="png", full_page=False)
            b64 = base64.standard_b64encode(png_bytes).decode("utf-8")
            self._log("screenshot", {"size_bytes": len(png_bytes)})
            return json.dumps({"success": True, "image_base64": b64, "media_type": "image/png"})
        except Exception as e:
            self._log("screenshot_error", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    async def click(self, selector: str, text: Optional[str] = None) -> str:
        """Click an element by CSS selector or by visible text."""
        try:
            if text:
                # Try to find element by text content
                locator = self._page.get_by_text(text, exact=False).first
                await locator.click(timeout=10_000)
                self._log("click", {"method": "text", "text": text})
            else:
                await self._page.click(selector, timeout=10_000)
                self._log("click", {"method": "selector", "selector": selector})
            await self._page.wait_for_load_state("domcontentloaded", timeout=10_000)
            return json.dumps({"success": True, "clicked": selector or text})
        except Exception as e:
            self._log("click_error", {"selector": selector, "text": text, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    async def type_text(self, selector: str, text: str, clear_first: bool = True) -> str:
        """Type text into an input field."""
        try:
            await self._page.wait_for_selector(selector, timeout=10_000)
            if clear_first:
                await self._page.fill(selector, "")
            await self._page.type(selector, text, delay=50)
            self._log("type_text", {"selector": selector, "text": text[:50]})
            return json.dumps({"success": True, "selector": selector, "text": text})
        except Exception as e:
            self._log("type_text_error", {"selector": selector, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    async def scroll(self, direction: str = "down", amount: int = 300) -> str:
        """Scroll the page up or down by a pixel amount."""
        try:
            scroll_y = amount if direction == "down" else -amount
            await self._page.evaluate(f"window.scrollBy(0, {scroll_y})")
            await asyncio.sleep(0.3)

            # Check if more content is available
            scroll_info = await self._page.evaluate("""() => ({
                scrollTop: window.scrollY,
                scrollHeight: document.documentElement.scrollHeight,
                clientHeight: window.innerHeight,
                atBottom: (window.scrollY + window.innerHeight) >= document.documentElement.scrollHeight - 10
            })""")
            self._log("scroll", {"direction": direction, "amount": amount, "info": scroll_info})
            return json.dumps({
                "success": True,
                "direction": direction,
                "amount": amount,
                "scroll_position": scroll_info["scrollTop"],
                "scroll_height": scroll_info["scrollHeight"],
                "at_bottom": scroll_info["atBottom"],
                "more_content": not scroll_info["atBottom"],
            })
        except Exception as e:
            self._log("scroll_error", {"direction": direction, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    async def get_text(self, selector: Optional[str] = None, max_chars: int = 5000) -> str:
        """Extract text content from a selector or the whole page."""
        try:
            if selector:
                await self._page.wait_for_selector(selector, timeout=10_000)
                text = await self._page.inner_text(selector)
            else:
                # Get meaningful page text via JS — strips scripts/styles
                text = await self._page.evaluate("""() => {
                    const clone = document.cloneNode(true);
                    const scripts = clone.querySelectorAll('script, style, noscript');
                    scripts.forEach(el => el.remove());
                    return clone.body ? clone.body.innerText : '';
                }""")
            text = text.strip()
            truncated = len(text) > max_chars
            text = text[:max_chars]
            self._log("get_text", {"selector": selector, "chars": len(text), "truncated": truncated})
            return json.dumps({
                "success": True,
                "text": text,
                "truncated": truncated,
                "char_count": len(text),
            })
        except Exception as e:
            self._log("get_text_error", {"selector": selector, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    async def fill_form(self, fields: list[dict]) -> str:
        """Fill multiple form fields at once.
        Each field: {"selector": "...", "value": "...", "type": "text|select|checkbox"}
        """
        results = []
        try:
            for field in fields:
                sel = field.get("selector", "")
                val = field.get("value", "")
                field_type = field.get("type", "text")
                try:
                    await self._page.wait_for_selector(sel, timeout=8_000)
                    if field_type == "select":
                        await self._page.select_option(sel, value=val)
                    elif field_type == "checkbox":
                        checked = val.lower() in ("true", "1", "yes", "on")
                        current = await self._page.is_checked(sel)
                        if current != checked:
                            await self._page.click(sel)
                    else:
                        await self._page.fill(sel, val)
                    results.append({"selector": sel, "success": True})
                except Exception as fe:
                    results.append({"selector": sel, "success": False, "error": str(fe)})

            self._log("fill_form", {"fields": len(fields), "results": results})
            all_ok = all(r["success"] for r in results)
            return json.dumps({"success": all_ok, "results": results})
        except Exception as e:
            self._log("fill_form_error", {"error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    async def get_page_info(self) -> str:
        """Get current page URL, title, and basic structure info."""
        try:
            url = self._page.url
            title = await self._page.title()
            # Count interactive elements
            info = await self._page.evaluate("""() => ({
                links: document.querySelectorAll('a[href]').length,
                buttons: document.querySelectorAll('button, input[type=submit], input[type=button]').length,
                inputs: document.querySelectorAll('input, textarea, select').length,
                images: document.querySelectorAll('img').length,
                headings: document.querySelectorAll('h1,h2,h3').length,
            })""")
            return json.dumps({"success": True, "url": url, "title": title, **info})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    async def press_key(self, key: str) -> str:
        """Press a keyboard key (e.g. Enter, Tab, Escape)."""
        try:
            await self._page.keyboard.press(key)
            self._log("press_key", {"key": key})
            return json.dumps({"success": True, "key": key})
        except Exception as e:
            self._log("press_key_error", {"key": key, "error": str(e)})
            return json.dumps({"success": False, "error": str(e)})

    async def wait_for_element(self, selector: str, timeout: int = 10000) -> str:
        """Wait for an element to appear on the page."""
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            self._log("wait_for_element", {"selector": selector})
            return json.dumps({"success": True, "selector": selector, "found": True})
        except Exception as e:
            return json.dumps({"success": False, "selector": selector, "found": False, "error": str(e)})

    # ---------------------------------------------------------------
    # Tool definitions for Claude API
    # ---------------------------------------------------------------

    @staticmethod
    def get_tool_definitions() -> list[dict]:
        """Return the tool schema list to pass to Claude."""
        return [
            {
                "name": "navigate",
                "description": "Navigate the browser to a URL. Waits for the page to load before returning.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to navigate to (e.g. https://google.com)"
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "screenshot",
                "description": "Take a screenshot of the current browser viewport. Returns a base64-encoded PNG image. Use this to see what the page looks like before deciding next actions.",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "click",
                "description": "Click on an element. Provide either a CSS selector or the visible text of the element.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector of the element to click (e.g. '#submit-btn', '.search-input')"
                        },
                        "text": {
                            "type": "string",
                            "description": "Visible text of the element to click (alternative to selector)"
                        }
                    }
                }
            },
            {
                "name": "type_text",
                "description": "Type text into an input field. Clears the field first by default.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector of the input field"
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to type into the field"
                        },
                        "clear_first": {
                            "type": "boolean",
                            "description": "Whether to clear the field before typing (default: true)"
                        }
                    },
                    "required": ["selector", "text"]
                }
            },
            {
                "name": "scroll",
                "description": "Scroll the page up or down. Returns whether more content is available below.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": ["up", "down"],
                            "description": "Direction to scroll"
                        },
                        "amount": {
                            "type": "integer",
                            "description": "Number of pixels to scroll (default: 300)"
                        }
                    }
                }
            },
            {
                "name": "get_text",
                "description": "Extract text content from the page or a specific element. Use this to read page content, search results, or form values.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector of element to get text from. Omit to get full page text."
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum characters to return (default: 5000)"
                        }
                    }
                }
            },
            {
                "name": "fill_form",
                "description": "Fill multiple form fields at once. Supports text inputs, selects, and checkboxes.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "fields": {
                            "type": "array",
                            "description": "List of form fields to fill",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "selector": {"type": "string", "description": "CSS selector"},
                                    "value": {"type": "string", "description": "Value to set"},
                                    "type": {
                                        "type": "string",
                                        "enum": ["text", "select", "checkbox"],
                                        "description": "Field type (default: text)"
                                    }
                                },
                                "required": ["selector", "value"]
                            }
                        }
                    },
                    "required": ["fields"]
                }
            },
            {
                "name": "get_page_info",
                "description": "Get current page URL, title, and counts of interactive elements (links, buttons, inputs).",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "press_key",
                "description": "Press a keyboard key. Common keys: Enter, Tab, Escape, ArrowDown, ArrowUp.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to press (e.g. 'Enter', 'Tab', 'Escape')"
                        }
                    },
                    "required": ["key"]
                }
            },
            {
                "name": "wait_for_element",
                "description": "Wait for a specific element to appear on the page (useful after navigation or clicks).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "selector": {
                            "type": "string",
                            "description": "CSS selector to wait for"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default: 10000)"
                        }
                    },
                    "required": ["selector"]
                }
            }
        ]
