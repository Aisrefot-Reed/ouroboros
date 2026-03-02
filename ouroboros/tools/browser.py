"""
Browser automation tools via Playwright (sync API).

Provides browse_page (open URL, get content/screenshot)
and browser_action (click, fill, evaluate JS on current page).

Browser state lives in ToolContext (per-task lifecycle),
not module-level globals — safe across threads.

Supports persistent sessions via cookies storage on Google Drive.
Includes Human-like interaction for anti-bot bypass.
"""

from __future__ import annotations

import base64
import json
import logging
import random
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from playwright_stealth import Stealth
    _HAS_STEALTH = True
except ImportError:
    _HAS_STEALTH = False

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

_playwright_ready = False
_pw_instance = None
_pw_thread_id = None 


def _get_session_path(ctx: ToolContext, session_name: str = "default") -> Path:
    """Get path for storing browser session data on Drive."""
    sessions_dir = ctx.drive_root() / "browser_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir / f"{session_name}_session.json"


def _save_cookies(ctx: ToolContext, session_name: str = "default") -> None:
    """Save current browser cookies to Drive."""
    try:
        if ctx.browser_state.page is None:
            return
        cookies = ctx.browser_state.page.context.cookies()
        session_path = _get_session_path(ctx, session_name)
        
        storage_state = {
            "cookies": cookies,
            "saved_at": time.time(),
        }
        
        try:
            local_storage = ctx.browser_state.page.evaluate("() => JSON.stringify(localStorage)")
            storage_state["localStorage"] = local_storage
        except Exception:
            pass
        
        # Atomic write
        tmp_path = session_path.with_suffix('.tmp')
        tmp_path.write_text(json.dumps(storage_state, indent=2))
        tmp_path.rename(session_path)
        log.info(f"Saved browser session to {session_path}")
    except Exception as e:
        log.warning(f"Failed to save browser session: {e}")


def _load_cookies(ctx: ToolContext, session_name: str = "default") -> bool:
    """Load and apply cookies from Drive."""
    try:
        session_path = _get_session_path(ctx, session_name)
        if not session_path.exists():
            return False
        
        storage_state = json.loads(session_path.read_text())
        cookies = storage_state.get("cookies", [])
        
        if ctx.browser_state.page is None:
            return False
        
        ctx.browser_state.page.context.add_cookies(cookies)
        
        if "localStorage" in storage_state:
            try:
                ctx.browser_state.page.evaluate(f"""
                    () => {{
                        const data = {storage_state["localStorage"]};
                        try {{
                            const obj = typeof data === 'string' ? JSON.parse(data) : data;
                            Object.keys(obj).forEach(key => {{
                                localStorage.setItem(key, obj[key]);
                            }});
                        }} catch (e) {{}}
                    }}
                """)
            except Exception:
                pass
        
        log.info(f"Loaded browser session from {session_path}")
        return True
    except Exception as e:
        log.warning(f"Failed to load browser session: {e}")
        return False


def _ensure_playwright_installed():
    """Install Playwright and Chromium if not already available."""
    global _playwright_ready
    if _playwright_ready:
        return

    try:
        import playwright  # noqa: F401
    except ImportError:
        log.info("Playwright not found, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.executable_path
        log.info("Playwright chromium binary found")
    except Exception:
        log.info("Installing Playwright chromium binary...")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install-deps", "chromium"])

    _playwright_ready = True


def _reset_playwright_greenlet():
    """Fully reset Playwright state to fix threading issues."""
    global _pw_instance, _pw_thread_id
    log.info("Resetting Playwright greenlet state...")
    try:
        subprocess.run(["pkill", "-9", "-f", "chromium"], capture_output=True, timeout=5)
    except Exception:
        pass
    mods_to_remove = [k for k in sys.modules.keys() if k.startswith('playwright') or 'greenlet' in k.lower()]
    for k in mods_to_remove:
        try:
            del sys.modules[k]
        except Exception:
            pass
    _pw_instance = None
    _pw_thread_id = None


def _human_delay(min_sec=1.0, max_sec=3.0):
    """Wait for a random amount of time."""
    time.sleep(random.uniform(min_sec, max_sec))


def _human_type(page: Any, selector: str, text: str):
    """Type text char by char like a human."""
    page.click(selector)
    for char in text:
        page.type(selector, char, delay=random.randint(50, 150))
        if random.random() < 0.1:
            time.sleep(random.uniform(0.1, 0.3))


def _human_click(page: Any, selector: str):
    """Simulate human-like click with mouse movement."""
    try:
        element = page.wait_for_selector(selector, timeout=5000)
        box = element.bounding_box()
        if box:
            # Move mouse to random point inside element
            x = box['x'] + random.uniform(2, box['width'] - 2)
            y = box['y'] + random.uniform(2, box['height'] - 2)
            page.mouse.move(x, y, steps=random.randint(5, 15))
            _human_delay(0.1, 0.5)
            page.mouse.click(x, y)
        else:
            page.click(selector)
    except Exception:
        page.click(selector)


def _ensure_browser(ctx: ToolContext, session_name: str = "default"):
    """Create or reuse browser for this task."""
    global _pw_instance, _pw_thread_id
    
    if session_name == "default" and ctx.browser_session_name:
        session_name = ctx.browser_session_name

    current_thread_id = threading.get_ident()
    if _pw_instance is not None and _pw_thread_id != current_thread_id:
        _reset_playwright_greenlet()

    if ctx.browser_state.browser is not None:
        try:
            if ctx.browser_state.browser.is_connected():
                return ctx.browser_state.page
        except Exception:
            pass
        cleanup_browser(ctx)

    _ensure_playwright_installed()

    if _pw_instance is None:
        from playwright.sync_api import sync_playwright
        try:
            _pw_instance = sync_playwright().start()
            _pw_thread_id = current_thread_id
        except RuntimeError:
            _reset_playwright_greenlet()
            from playwright.sync_api import sync_playwright
            _pw_instance = sync_playwright().start()
            _pw_thread_id = current_thread_id

    ctx.browser_state.pw_instance = _pw_instance

    ctx.browser_state.browser = _pw_instance.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--window-size=1920,1080",
        ],
    )
    
    # Random User-Agent for variety
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ]
    
    ctx.browser_state.page = ctx.browser_state.browser.new_page(
        viewport={"width": 1920, "height": 1080},
        user_agent=random.choice(user_agents),
        extra_http_headers={
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/"
        }
    )

    if _HAS_STEALTH:
        stealth = Stealth()
        stealth.apply_stealth_sync(ctx.browser_state.page)

    ctx.browser_state.page.set_default_timeout(30000)
    _load_cookies(ctx, session_name)
    
    return ctx.browser_state.page


def cleanup_browser(ctx: ToolContext, session_name: str = "default") -> None:
    """Close browser and page, save session."""
    global _pw_instance
    if session_name == "default" and ctx.browser_session_name:
        session_name = ctx.browser_session_name
    _save_cookies(ctx, session_name)
    try:
        if ctx.browser_state.page is not None:
            ctx.browser_state.page.close()
        if ctx.browser_state.browser is not None:
            ctx.browser_state.browser.close()
    except Exception as e:
        if "cannot switch" in str(e) or "different thread" in str(e):
            _reset_playwright_greenlet()
    ctx.browser_state.page = None
    ctx.browser_state.browser = None
    ctx.browser_state.pw_instance = None


_MARKDOWN_JS = """() => {
    const walk = (el) => {
        let out = '';
        for (const child of el.childNodes) {
            if (child.nodeType === 3) {
                const t = child.textContent.trim();
                if (t) out += t + ' ';
            } else if (child.nodeType === 1) {
                const tag = child.tagName;
                if (['SCRIPT','STYLE','NOSCRIPT'].includes(tag)) continue;
                if (['H1','H2','H3','H4','H5','H6'].includes(tag))
                    out += '\\n' + '#'.repeat(parseInt(tag[1])) + ' ';
                if (tag === 'P' || tag === 'DIV' || tag === 'BR') out += '\\n';
                if (tag === 'LI') out += '\\n- ';
                if (tag === 'A') out += '[';
                out += walk(child);
                if (tag === 'A') out += '](' + (child.href||'') + ')';
            }
        }
        return out;
    };
    return walk(document.body);
}"""


def _extract_page_output(page: Any, output: str, ctx: ToolContext) -> str:
    """Extract page content in requested format."""
    # Scroll to ensure dynamic content loads
    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
    _human_delay(0.5, 1.0)
    page.evaluate("window.scrollTo(0, 0)")
    _human_delay(0.5, 1.0)
    
    if output == "screenshot":
        data = page.screenshot(type="png", full_page=False)
        b64 = base64.b64encode(data).decode()
        ctx.browser_state.last_screenshot_b64 = b64
        return f"Screenshot captured ({len(b64)} bytes base64). Call send_photo to deliver."
    elif output == "html":
        return page.content()[:50000]
    elif output == "markdown":
        return page.evaluate(_MARKDOWN_JS)[:30000]
    else:  # text
        return page.inner_text("body")[:30000]


def _browse_page(ctx: ToolContext, url: str, output: str = "text",
                 wait_for: str = "", timeout: int = 30000) -> str:
    try:
        page = _ensure_browser(ctx)
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        if wait_for:
            page.wait_for_selector(wait_for, timeout=timeout)
        return _extract_page_output(page, output, ctx)
    except Exception as e:
        if "greenlet" in str(e).lower() or "thread" in str(e).lower():
            cleanup_browser(ctx)
            _reset_playwright_greenlet()
            page = _ensure_browser(ctx)
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return _extract_page_output(page, output, ctx)
        raise


def _browser_action(ctx: ToolContext, action: str, selector: str = "",
                    value: str = "", timeout: int = 5000) -> str:
    def _do_action():
        page = _ensure_browser(ctx)
        if action == "click":
            _human_click(page, selector)
            page.wait_for_timeout(random.randint(500, 1500))
            return f"Human-clicked: {selector}"
        elif action == "fill":
            _human_type(page, selector, value)
            return f"Human-typed {selector} with: {value}"
        elif action == "select":
            page.select_option(selector, value, timeout=timeout)
            return f"Selected {value} in {selector}"
        elif action == "screenshot":
            data = page.screenshot(type="png", full_page=False)
            b64 = base64.b64encode(data).decode()
            ctx.browser_state.last_screenshot_b64 = b64
            return f"Screenshot captured ({len(b64)} bytes base64)."
        elif action == "evaluate":
            result = page.evaluate(value)
            return str(result)[:20000]
        elif action == "scroll":
            dir_map = {"down": "window.scrollBy(0, 600)", "up": "window.scrollBy(0, -600)", 
                       "top": "window.scrollTo(0, 0)", "bottom": "window.scrollTo(0, document.body.scrollHeight)"}
            page.evaluate(dir_map.get(value, "window.scrollBy(0, 600)"))
            return f"Scrolled {value or 'down'}"
        return f"Unknown action: {action}"

    try:
        return _do_action()
    except Exception as e:
        if "greenlet" in str(e).lower() or "thread" in str(e).lower():
            cleanup_browser(ctx)
            _reset_playwright_greenlet()
            return _do_action()
        raise


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry(name="browse_page", schema={"name": "browse_page", "description": "Open URL in headless browser. Returns text/html/markdown or screenshot.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to open"}, "output": {"type": "string", "enum": ["text", "html", "markdown", "screenshot"], "description": "Output format"}}, "required": ["url"]}}, handler=_browse_page, timeout_sec=60),
        ToolEntry(name="browser_action", schema={"name": "browser_action", "description": "Perform action on current page: click, fill, select, screenshot, evaluate JS, scroll.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["click", "fill", "select", "screenshot", "evaluate", "scroll"], "description": "Action to perform"}, "selector": {"type": "string", "description": "CSS selector"}, "value": {"type": "string", "description": "Value for fill/select/evaluate/scroll"}}, "required": ["action"]}}, handler=_browser_action, timeout_sec=60),
    ]
