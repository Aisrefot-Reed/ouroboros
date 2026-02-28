"""Kwork integration tools.

Tools for Kwork automation: login, search orders, submit proposals.
Uses browser automation via browse_page and browser_action.
Supports persistent sessions via cookies stored on Google Drive.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.tools.credentials import _load_credentials


def _check_kwork_logged_in(ctx: ToolContext) -> bool:
    """Check if already logged in to Kwork by checking current page or cookies."""
    try:
        page = ctx.browser_state.page
        if page is None:
            return False
        
        # Check if we're on kwork.ru and not on login page
        current_url = page.url
        if "kwork.ru" in current_url and "login" not in current_url:
            return True
        
        # Check for auth cookies
        cookies = page.context.cookies()
        for cookie in cookies:
            if cookie.get("name") in ("PHPSESSID", "user_id", "kwork"):
                return True
        
        return False
    except Exception:
        return False


def _kwork_login_impl(ctx: ToolContext, force: bool = False) -> str:
    """Login to Kwork using stored credentials.
    
    If session cookies exist, auto-login without credentials.
    If force=True, re-login even if session exists.
    """
    # Set browser session name for Kwork
    ctx.browser_session_name = "kwork"
    
    # Check if already logged in (skip login if session exists)
    if not force and _check_kwork_logged_in(ctx):
        return "✅ Already logged in to Kwork (session restored from cookies)"
    
    credentials = _load_credentials(ctx)

    if "kwork" not in credentials:
        return "⚠️ No Kwork credentials found. Use store_credentials first."

    creds = credentials["kwork"]
    login_email = creds.get("email")
    login_password = creds.get("password")

    if not login_email or not login_password:
        return "⚠️ Incomplete credentials"

    try:
        page = ctx.browser_state.page

        # Navigate to Kwork login
        page.goto("https://kwork.ru/login", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Fill email
        email_input = page.locator('input[name="login"]')
        email_input.fill(login_email)

        # Fill password
        password_input = page.locator('input[name="password"]')
        password_input.fill(login_password)

        # Click submit
        submit_btn = page.locator('button[type="submit"]').first
        submit_btn.click()

        # Wait for navigation
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(3)

        # Check if login succeeded
        current_url = page.url
        if "kwork.ru" in current_url and "login" not in current_url:
            # Session will be saved automatically by cleanup_browser
            return f"✅ Kwork login successful: {login_email} (session saved)"
        else:
            return f"⚠️ Kwork login failed. Current URL: {current_url}"

    except Exception as e:
        return f"⚠️ Kwork login error: {repr(e)}"


def _search_kwork_orders_impl(
    ctx: ToolContext,
    keywords: str,
    min_budget: int = 0,
    max_budget: Optional[int] = None,
    skills: Optional[str] = None,
    max_results: int = 15,
    auto_login: bool = True
) -> str:
    """Search for orders on Kwork.
    
    Args:
        keywords: Search keywords
        min_budget: Minimum budget in RUB
        max_budget: Maximum budget in RUB
        skills: Comma-separated skills filter
        max_results: Max results (default: 15)
        auto_login: If True, auto-login using saved session
    """
    # Set browser session name for Kwork
    ctx.browser_session_name = "kwork"
    
    # Auto-login if needed
    if auto_login and not _check_kwork_logged_in(ctx):
        login_result = _kwork_login_impl(ctx, force=False)
        if "⚠️" in login_result or "Error" in login_result:
            return f"⚠️ Cannot search orders: {login_result}"
    
    try:
        page = ctx.browser_state.page

        # Build search URL
        search_url = f"https://kwork.ru/birza?keyword={keywords.replace(' ', '%20')}"

        page.goto(search_url, wait_until="networkidle", timeout=30000)
        time.sleep(3)
        
        # Extract order listings
        orders = []
        
        # Find order cards
        order_cards = page.locator('div.kwork-card').all()
        
        for i, card in enumerate(order_cards[:max_results]):
            try:
                # Extract title
                title_el = card.locator('a.kwork-card__title').first
                title = title_el.inner_text() if title_el.count() > 0 else "Unknown"
                title_link = title_el.get_attribute('href') if title_el.count() > 0 else ""
                
                # Extract budget
                budget_el = card.locator('div.kwork-card__price').first
                budget = budget_el.inner_text() if budget_el.count() > 0 else "Договорная"
                
                # Extract description
                desc_el = card.locator('div.kwork-card__description').first
                description = desc_el.inner_text() if desc_el.count() > 0 else ""
                
                # Extract skills
                skills_els = card.locator('a.kwork-card__skill')
                order_skills = [el.inner_text() for el in skills_els.all()[:5]]
                
                # Filter by budget
                budget_value = int(''.join(filter(str.isdigit, budget)) or "0")
                if budget_value < min_budget:
                    continue
                if max_budget and budget_value > max_budget:
                    continue
                
                # Filter by skills if specified
                if skills:
                    required_skills = [s.strip().lower() for s in skills.split(',')]
                    has_skill = any(
                        any(rs in skill.lower() for rs in required_skills)
                        for skill in order_skills
                    )
                    if not has_skill:
                        continue
                
                orders.append({
                    "title": title,
                    "budget": budget,
                    "budget_value": budget_value,
                    "description": description[:200],
                    "skills": order_skills,
                    "url": f"https://kwork.ru{title_link}" if title_link else ""
                })
                
            except Exception:
                continue
        
        if not orders:
            return f"📭 No orders found for '{keywords}'"
        
        # Format results
        lines = [f"💼 Found {len(orders)} orders on Kwork:\n"]
        for i, order in enumerate(orders, 1):
            skills_str = ", ".join(order["skills"]) if order["skills"] else "N/A"
            lines.append(
                f"{i}. **{order['title']}**\n"
                f"   💰 {order['budget']}\n"
                f"   🏷️ Skills: {skills_str}\n"
                f"   📝 {order['description']}\n"
                f"   🔗 {order['url']}\n"
            )
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"⚠️ Order search error: {repr(e)}"


def _submit_kwork_proposal_impl(
    ctx: ToolContext,
    order_url: str,
    proposal_text: str,
    price: Optional[int] = None,
    deadline_days: int = 3
) -> str:
    """Submit a proposal to a Kwork order."""
    try:
        page = ctx.browser_state.page
        
        # Navigate to order
        page.goto(order_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        
        # Look for proposal form
        try:
            # Find and click "Make proposal" button
            proposal_btn = page.locator('button:has-text("Сделать предложение"), button:has-text("Откликнуться")').first
            
            if proposal_btn.count() > 0:
                proposal_btn.click()
                time.sleep(2)
                
                # Fill proposal text
                textarea = page.locator('textarea[name="message"], textarea[placeholder*="предложение"]').first
                textarea.fill(proposal_text)
                time.sleep(1)
                
                # Fill price if specified
                if price:
                    price_input = page.locator('input[name="price"], input[type="number"]').first
                    price_input.fill(str(price))
                    time.sleep(1)
                
                # Fill deadline if specified
                if deadline_days:
                    deadline_input = page.locator('input[name="deadline"], input[placeholder*="дней"]').first
                    deadline_input.fill(str(deadline_days))
                    time.sleep(1)
                
                # Submit proposal
                submit_btn = page.locator('button:has-text("Отправить"), button[type="submit"]').first
                submit_btn.click()
                
                time.sleep(3)
                
                return f"✅ Kwork proposal submitted (price: {price or 'negotiable'}, deadline: {deadline_days} days)"
            
            else:
                return "⚠️ Could not find proposal button. Order may be closed."
        
        except Exception as inner_e:
            return f"⚠️ Could not submit proposal: {repr(inner_e)}"
    
    except Exception as e:
        return f"⚠️ Proposal error: {repr(e)}"


def _schedule_kwork_monitoring_impl(
    ctx: ToolContext,
    keywords: str,
    min_budget: int = 0,
    max_budget: Optional[int] = None,
    skills: Optional[str] = None,
    check_interval_hours: int = 3,
    auto_proposal: bool = False,
    proposal_template: Optional[str] = None
) -> str:
    """Schedule Kwork order monitoring."""
    import uuid
    from supervisor.queue import enqueue_task

    schedule_id = uuid.uuid4().hex[:8]

    enqueue_task({
        "id": schedule_id,
        "type": "kwork_order_monitor",
        "chat_id": int(ctx.current_chat_id or 0),
        "text": f"SCHEDULED KWORK MONITOR: {keywords}",
        "keywords": keywords,
        "min_budget": min_budget,
        "max_budget": max_budget,
        "skills": skills,
        "check_interval_hours": check_interval_hours,
        "auto_proposal": auto_proposal,
        "proposal_template": proposal_template,
    })

    auto_text = " with auto-proposal" if auto_proposal else ""
    return f"✅ Kwork monitoring scheduled (ID: {schedule_id}), every {check_interval_hours}h{auto_text}"


def _get_kwork_orders_impl(
    ctx: ToolContext,
    keywords: str,
    min_budget: int = 0,
    max_budget: Optional[int] = None,
    skills: Optional[str] = None,
    max_results: int = 10,
    notify: bool = True
) -> str:
    """Get new Kwork orders and optionally send notification.
    
    This tool is designed for continuous monitoring in background consciousness.
    It searches for orders and can send a message to the owner if new orders are found.
    
    Args:
        keywords: Search keywords
        min_budget: Minimum budget in RUB
        max_budget: Maximum budget in RUB
        skills: Comma-separated skills filter
        max_results: Max results (default: 10)
        notify: If True, send message to owner with results
    """
    # Set browser session name for Kwork
    ctx.browser_session_name = "kwork"
    
    # Auto-login if needed
    if not _check_kwork_logged_in(ctx):
        login_result = _kwork_login_impl(ctx, force=False)
        if "⚠️" in login_result or "Error" in login_result:
            return f"⚠️ Cannot get orders: {login_result}"
    
    # Search for orders (reuse search implementation)
    search_result = _search_kwork_orders_impl(
        ctx, keywords, min_budget, max_budget, skills, max_results, auto_login=False
    )
    
    # If notify is True and orders found, send message to owner
    if notify and "📭" not in search_result and ctx.current_chat_id:
        from ouroboros.tools.control import _send_owner_message
        try:
            _send_owner_message(ctx, search_result)
            return f"✅ Found new Kwork orders and sent notification (keywords: {keywords})"
        except Exception:
            pass
    
    return search_result


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("kwork_login", {
            "name": "kwork_login",
            "description": "Login to Kwork using stored credentials. If session cookies exist, auto-login without credentials. Use force=true to re-login.",
            "parameters": {"type": "object", "properties": {
                "force": {"type": "boolean", "description": "Force re-login even if session exists (default: false)"},
            }},
        }, _kwork_login_impl),

        ToolEntry("search_kwork_orders", {
            "name": "search_kwork_orders",
            "description": "Search for orders on Kwork with filters for budget and skills. Auto-logs in using saved session.",
            "parameters": {"type": "object", "properties": {
                "keywords": {"type": "string", "description": "Search keywords"},
                "min_budget": {"type": "integer", "description": "Minimum budget in RUB"},
                "max_budget": {"type": "integer", "description": "Maximum budget in RUB"},
                "skills": {"type": "string", "description": "Comma-separated skills filter"},
                "max_results": {"type": "integer", "description": "Max results (default: 15)"},
                "auto_login": {"type": "boolean", "description": "Auto-login using saved session (default: true)"},
            }, "required": ["keywords"]},
        }, _search_kwork_orders_impl),
        
        ToolEntry("submit_kwork_proposal", {
            "name": "submit_kwork_proposal",
            "description": "Submit a proposal to a Kwork order.",
            "parameters": {"type": "object", "properties": {
                "order_url": {"type": "string", "description": "Kwork order URL"},
                "proposal_text": {"type": "string", "description": "Proposal message"},
                "price": {"type": "integer", "description": "Proposed price in RUB"},
                "deadline_days": {"type": "integer", "description": "Deadline in days"},
            }, "required": ["order_url", "proposal_text"]},
        }, _submit_kwork_proposal_impl),
        
        ToolEntry("schedule_kwork_monitoring", {
            "name": "schedule_kwork_monitoring",
            "description": "Schedule Kwork order monitoring with optional auto-proposals.",
            "parameters": {"type": "object", "properties": {
                "keywords": {"type": "string", "description": "Keywords to monitor"},
                "min_budget": {"type": "integer", "description": "Minimum budget in RUB"},
                "max_budget": {"type": "integer", "description": "Maximum budget in RUB"},
                "skills": {"type": "string", "description": "Required skills (comma-separated)"},
                "check_interval_hours": {"type": "integer", "description": "Hours between checks"},
                "auto_proposal": {"type": "boolean", "description": "Enable auto-proposals"},
                "proposal_template": {"type": "string", "description": "Template for auto-proposals"},
            }, "required": ["keywords"]},
        }, _schedule_kwork_monitoring_impl),
        
        ToolEntry("get_kwork_orders", {
            "name": "get_kwork_orders",
            "description": "Get new Kwork orders and optionally notify owner. Designed for background consciousness monitoring.",
            "parameters": {"type": "object", "properties": {
                "keywords": {"type": "string", "description": "Search keywords"},
                "min_budget": {"type": "integer", "description": "Minimum budget in RUB"},
                "max_budget": {"type": "integer", "description": "Maximum budget in RUB"},
                "skills": {"type": "string", "description": "Comma-separated skills filter"},
                "max_results": {"type": "integer", "description": "Max results (default: 10)"},
                "notify": {"type": "boolean", "description": "Send notification to owner if orders found (default: true)"},
            }, "required": ["keywords"]},
        }, _get_kwork_orders_impl),
    ]
