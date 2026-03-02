"""Kwork integration tools.

Tools for Kwork automation: login, search orders, submit proposals.
Uses browser automation via browse_page and browser_action.
Supports persistent sessions via cookies stored on Google Drive.
"""

from __future__ import annotations

import json
import time
import random
from typing import Any, Dict, List, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.tools.credentials import _load_credentials


def _check_kwork_logged_in(ctx: ToolContext) -> bool:
    """Check if already logged in to Kwork."""
    try:
        page = ctx.browser_state.page
        if page is None:
            return False
        
        current_url = page.url
        if "kwork.ru" in current_url and "login" not in current_url:
            return True
        
        cookies = page.context.cookies()
        for cookie in cookies:
            if cookie.get("name") in ("PHPSESSID", "user_id", "kwork"):
                return True
        return False
    except Exception:
        return False


def _kwork_login_impl(ctx: ToolContext, force: bool = False) -> str:
    """Login to Kwork using stored credentials."""
    ctx.browser_session_name = "kwork"
    from ouroboros.tools.browser import _ensure_browser, _human_type, _human_click, _human_delay
    
    page = _ensure_browser(ctx)
    if not force and _check_kwork_logged_in(ctx):
        return "✅ Already logged in to Kwork (session restored)"
    
    credentials = _load_credentials(ctx)
    if "kwork" not in credentials:
        return "⚠️ No Kwork credentials found. Use store_credentials first."

    creds = credentials["kwork"]
    login_email = creds.get("email")
    login_password = creds.get("password")

    try:
        page.goto("https://kwork.ru/login", wait_until="networkidle", timeout=30000)
        _human_delay(1, 3)

        # Fill email with human typing
        _human_type(page, 'input[name="login"]', login_email)
        _human_delay(0.5, 1.5)

        # Fill password with human typing
        _human_type(page, 'input[name="password"]', login_password)
        _human_delay(1, 2)

        # Click submit with human mouse move
        _human_click(page, 'button[type="submit"]')

        page.wait_for_load_state("networkidle", timeout=30000)
        _human_delay(3, 5)

        if "login" not in page.url:
            return f"✅ Kwork login successful: {login_email}"
        else:
            return f"⚠️ Kwork login failed. URL: {page.url}"
    except Exception as e:
        return f"⚠️ Kwork login error: {repr(e)}"


def _search_kwork_orders_impl(
    ctx: ToolContext,
    keywords: str,
    min_budget: int = 0,
    max_results: int = 15,
    auto_login: bool = True
) -> str:
    """Search for orders on Kwork with improved stability."""
    ctx.browser_session_name = "kwork"
    from ouroboros.tools.browser import _ensure_browser, _human_delay
    
    page = _ensure_browser(ctx)
    if auto_login and not _check_kwork_logged_in(ctx):
        _kwork_login_impl(ctx)
    
    try:
        search_url = f"https://kwork.ru/birza?keyword={keywords.replace(' ', '%20')}"
        page.goto(search_url, wait_until="networkidle", timeout=30000)
        
        # Scroll down to trigger lazy loading of orders
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 1000)")
            _human_delay(0.5, 1.0)
        page.evaluate("window.scrollTo(0, 0)")
        _human_delay(1.0, 2.0)
        
        orders = []
        # Update selectors to be more robust
        order_cards = page.locator('div.kwork-card, div.card__item').all()
        
        for card in order_cards[:max_results]:
            try:
                title_el = card.locator('a.kwork-card__title, a.card__title').first
                title = title_el.inner_text()
                link = title_el.get_attribute('href')
                
                budget_el = card.locator('div.kwork-card__price, div.card__price').first
                budget = budget_el.inner_text()
                
                desc_el = card.locator('div.kwork-card__description, div.card__desc').first
                description = desc_el.inner_text()
                
                budget_val = int(''.join(filter(str.isdigit, budget)) or "0")
                if budget_val < min_budget:
                    continue
                
                orders.append({
                    "title": title,
                    "budget": budget,
                    "description": description[:300],
                    "url": f"https://kwork.ru{link}" if link.startswith('/') else link
                })
            except Exception:
                continue
        
        if not orders:
            return f"📭 No orders found for '{keywords}'"
        
        lines = [f"💼 Found {len(orders)} orders on Kwork for '{keywords}':\n"]
        for i, order in enumerate(orders, 1):
            lines.append(f"{i}. **{order['title']}** ({order['budget']})\n   {order['description']}\n   🔗 {order['url']}\n")
        
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Order search error: {repr(e)}"


def _submit_kwork_proposal_impl(
    ctx: ToolContext,
    order_url: str,
    proposal_text: str,
    price: Optional[int] = None
) -> str:
    """Submit proposal with human-like interaction."""
    ctx.browser_session_name = "kwork"
    from ouroboros.tools.browser import _ensure_browser, _human_type, _human_click, _human_delay
    
    page = _ensure_browser(ctx)
    try:
        page.goto(order_url, wait_until="networkidle", timeout=30000)
        _human_delay(2, 4)
        
        # Click proposal button
        btn = page.locator('button:has-text("Сделать предложение"), button:has-text("Откликнуться")').first
        if btn.count() == 0:
            return "⚠️ Proposal button not found. Order closed?"
        
        _human_click(page, 'button:has-text("Сделать предложение"), button:has-text("Откликнуться")')
        _human_delay(1.5, 3)
        
        # Fill proposal text with human typing
        _human_type(page, 'textarea[name="message"]', proposal_text)
        _human_delay(1, 2)
        
        if price:
            _human_type(page, 'input[name="price"]', str(price))
            _human_delay(0.5, 1)
            
        # Final submit
        _human_click(page, 'button:has-text("Отправить")')
        _human_delay(3, 5)
        
        return "✅ Proposal submitted successfully."
    except Exception as e:
        return f"⚠️ Proposal error: {repr(e)}"


def get_tools() -> List[ToolEntry]:
    # Keeping the same tool definitions
    from ouroboros.tools.kwork import _get_kwork_orders_impl, _schedule_kwork_monitoring_impl
    return [
        ToolEntry("kwork_login", {"name": "kwork_login", "parameters": {"type": "object", "properties": {"force": {"type": "boolean"}}}}, _kwork_login_impl),
        ToolEntry("search_kwork_orders", {"name": "search_kwork_orders", "parameters": {"type": "object", "properties": {"keywords": {"type": "string"}, "min_budget": {"type": "integer"}}, "required": ["keywords"]}}, _search_kwork_orders_impl),
        ToolEntry("submit_kwork_proposal", {"name": "submit_kwork_proposal", "parameters": {"type": "object", "properties": {"order_url": {"type": "string"}, "proposal_text": {"type": "string"}}, "required": ["order_url", "proposal_text"]}}, _submit_kwork_proposal_impl),
        ToolEntry("get_kwork_orders", {"name": "get_kwork_orders", "parameters": {"type": "object", "properties": {"keywords": {"type": "string"}}, "required": ["keywords"]}}, _get_kwork_orders_impl),
        ToolEntry("schedule_kwork_monitoring", {"name": "schedule_kwork_monitoring", "parameters": {"type": "object", "properties": {"keywords": {"type": "string"}}, "required": ["keywords"]}}, _schedule_kwork_monitoring_impl),
    ]
