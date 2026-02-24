"""
Kwork integration tools.

Provides functionality to:
- Log in to Kwork
- Monitor service orders/projects
- Apply to orders automatically
- Manage Kwork profile
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


def _kwork_login(ctx: ToolContext, email: str, password: str) -> str:
    """
    Log in to Kwork using browser automation.
    """
    try:
        from ouroboros.tools.browser import _ensure_browser
        
        page = _ensure_browser(ctx)
        page.goto("https://www.kwork.ru/login", wait_until="domcontentloaded")
        
        # Fill login credentials
        page.fill("#login_email", email)
        page.fill("#login_password", password)
        
        # Click login button
        page.click("input[type='submit']")
        
        # Wait for login process
        page.wait_for_timeout(3000)
        
        # Check if login was successful by looking for dashboard elements
        if "dashboard" in page.url or "profile" in page.url:
            return "Successfully logged in to Kwork"
        else:
            # Check for error messages
            try:
                error_elements = page.query_selector_all(".error, .alert-danger, .notification-error")
                error_messages = []
                for elem in error_elements:
                    error_messages.append(elem.inner_text().strip())
                
                if error_messages:
                    return f"Login failed: {'; '.join(error_messages)}"
                else:
                    return "Login may have failed - please check manually. Possible 2FA required."
            except Exception as e:
                log.debug(f"Error checking for error message: {e}")
                return "Login may have failed - please check manually. Possible 2FA required."
    
    except Exception as e:
        return f"Error during Kwork login: {str(e)}"


def _kwork_search_orders(ctx: ToolContext, keywords: str = "", category: str = "", 
                        min_budget: int = 0, max_budget: int = 0) -> str:
    """
    Search for orders/projects on Kwork with specified criteria.
    """
    try:
        from ouroboros.tools.browser import _ensure_browser
        
        page = _ensure_browser(ctx)
        
        # Build search URL
        base_url = "https://www.kwork.ru/projects"
        search_params = []
        
        if keywords:
            search_params.append(f"q={keywords}")
        if category:
            search_params.append(f"category={category}")
        if min_budget > 0:
            search_params.append(f"min_price={min_budget}")
        if max_budget > 0:
            search_params.append(f"max_price={max_budget}")
        
        search_url = f"{base_url}?" + "&".join(search_params) if search_params else base_url
        page.goto(search_url, wait_until="domcontentloaded")
        
        # Wait for project listings to load
        page.wait_for_selector(".projects-list", timeout=10000)
        
        # Extract project listings
        projects = page.query_selector_all(".project-item, .kwork-item")
        project_list = []
        
        for i, project in enumerate(projects[:10]):  # Limit to first 10 projects
            try:
                title_elem = project.query_selector(".project-title, .kwork-title, h3")
                title = title_elem.inner_text().strip() if title_elem else "No title"
                
                budget_elem = project.query_selector(".project-price, .kwork-price, .price")
                budget = budget_elem.inner_text().strip() if budget_elem else "No budget"
                
                description_elem = project.query_selector(".project-description, .kwork-description, .desc")
                description = description_elem.inner_text().strip()[:200] + "..." if description_elem else "No description"
                
                user_elem = project.query_selector(".project-user, .kwork-user, .username")
                user = user_elem.inner_text().strip() if user_elem else "Unknown user"
                
                link_elem = project.query_selector("a")
                link = link_elem.get_attribute("href") if link_elem else ""
                if link and not link.startswith("http"):
                    link = "https://www.kwork.ru" + link
                
                project_list.append({
                    "title": title,
                    "budget": budget,
                    "description": description,
                    "user": user,
                    "link": link
                })
                
                if len(project_list) >= 10:  # Limit to 10 projects
                    break
            except Exception as e:
                log.debug(f"Error parsing project {i}: {e}")
                continue
        
        if not project_list:
            return "No projects found with the specified criteria"
        
        return json.dumps(project_list, indent=2, ensure_ascii=False)
    
    except Exception as e:
        return f"Error searching Kwork projects: {str(e)}"


def _kwork_submit_proposal(ctx: ToolContext, order_url: str, proposal_text: str, 
                          bid_amount: float = 0.0) -> str:
    """
    Submit a proposal to a Kwork order/project.
    """
    try:
        from ouroboros.tools.browser import _ensure_browser
        
        page = _ensure_browser(ctx)
        page.goto(order_url, wait_until="domcontentloaded")
        
        # Wait for place bid button or proposal form
        try:
            # Look for the bid/proposal button first
            bid_button_selector = ".place-bid-btn, .proposal-btn, button.bid, button.proposal"
            page.wait_for_selector(bid_button_selector, timeout=5000)
            
            # Click the bid button to open the form
            page.click(bid_button_selector)
            
            # Wait for form to appear
            page.wait_for_selector("form.proposal-form, .bid-form", timeout=3000)
            
            # Fill in the proposal text
            proposal_textarea = page.query_selector("textarea[name='description'], textarea[name='text'], .proposal-text")
            if proposal_textarea:
                proposal_textarea.fill(proposal_text)
            
            # Fill in bid amount if specified
            if bid_amount > 0:
                bid_input = page.query_selector("input[name='price'], input[name='bid'], .bid-amount")
                if bid_input:
                    bid_input.fill(str(bid_amount))
            
            # Submit the proposal
            submit_button = page.query_selector("button[type='submit'], .submit-btn")
            if submit_button:
                submit_button.click()
            
            # Wait a bit to see if submission was successful
            page.wait_for_timeout(2000)
            
            # Check for success message
            success_messages = page.query_selector_all(".success, .notification-success, .bid-success")
            if success_messages:
                return f"Successfully submitted proposal for: {order_url}"
            else:
                return f"Attempted to submit proposal for: {order_url} (form filled but success not confirmed)"
        
        except Exception as e:
            return f"Could not find proposal form for order: {order_url} - {str(e)}"
    
    except Exception as e:
        return f"Error submitting proposal: {str(e)}"


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry(
            name="kwork_login",
            schema={
                "name": "kwork_login",
                "description": "Log in to Kwork using email and password",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "description": "Kwork email"},
                        "password": {"type": "string", "description": "Kwork password"}
                    },
                    "required": ["email", "password"]
                }
            },
            handler=_kwork_login,
            timeout_sec=60
        ),
        ToolEntry(
            name="kwork_search_orders",
            schema={
                "name": "kwork_search_orders",
                "description": "Search for orders/projects on Kwork with keywords, category, and budget filters",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keywords": {"type": "string", "description": "Keywords to search for in projects"},
                        "category": {"type": "string", "description": "Category filter (optional)"},
                        "min_budget": {"type": "integer", "description": "Minimum budget filter (optional)"},
                        "max_budget": {"type": "integer", "description": "Maximum budget filter (optional)"}
                    },
                    "required": []
                }
            },
            handler=_kwork_search_orders,
            timeout_sec=60
        ),
        ToolEntry(
            name="kwork_submit_proposal",
            schema={
                "name": "kwork_submit_proposal",
                "description": "Submit a proposal to a specific Kwork order/project",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_url": {"type": "string", "description": "URL of the order/project to bid on"},
                        "proposal_text": {"type": "string", "description": "Text of the proposal/bid"},
                        "bid_amount": {"type": "number", "description": "Bid amount in USD (optional, system may use existing settings)"}
                    },
                    "required": ["order_url", "proposal_text"]
                }
            },
            handler=_kwork_submit_proposal,
            timeout_sec=60
        )
    ]