"""LinkedIn integration tools.

Tools for LinkedIn automation: login, post, job search, apply.
Uses browser automation via browse_page and browser_action.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.tools.credentials import _load_credentials


def _linkedin_login_impl(ctx: ToolContext, email: Optional[str] = None) -> str:
    """Login to LinkedIn using stored credentials."""
    credentials = _load_credentials(ctx)
    
    if "linkedin" not in credentials:
        return "⚠️ No LinkedIn credentials found. Use store_credentials first."
    
    creds = credentials["linkedin"]
    login_email = email or creds.get("email")
    login_password = creds.get("password")
    
    if not login_email or not login_password:
        return "⚠️ Incomplete credentials"
    
    try:
        # Navigate to LinkedIn login
        page = ctx.browser_state.page
        page.goto("https://www.linkedin.com/login", wait_until="networkidle", timeout=30000)
        
        # Fill email
        email_input = page.locator("#username")
        email_input.fill(login_email)
        
        # Fill password
        password_input = page.locator("#password")
        password_input.fill(login_password)
        
        # Click submit
        submit_btn = page.locator('button[type="submit"]')
        submit_btn.click()
        
        # Wait for navigation
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(3)  # Extra wait for LinkedIn's slow redirects
        
        # Check if login succeeded
        current_url = page.url
        if "feed" in current_url or "mynetwork" in current_url:
            return f"✅ LinkedIn login successful: {login_email}"
        elif "checkpoint" in current_url:
            return "⚠️ LinkedIn requires additional verification (checkpoint)"
        else:
            return f"⚠️ LinkedIn login failed. Current URL: {current_url}"
    
    except Exception as e:
        return f"⚠️ LinkedIn login error: {repr(e)}"


def _linkedin_post_impl(
    ctx: ToolContext,
    content: str,
    visibility: str = "public"
) -> str:
    """Create a post on LinkedIn."""
    try:
        page = ctx.browser_state.page
        
        # Navigate to post creation
        page.goto("https://www.linkedin.com/feed/", wait_until="networkidle", timeout=30000)
        time.sleep(2)
        
        # Find and click the post input
        try:
            post_input = page.locator('div[role="textbox"]').first
            post_input.click()
            time.sleep(1)
            
            # Clear and fill
            post_input.fill(content)
            time.sleep(1)
            
            # Find and click post button
            post_btn = page.locator('button:has-text("Post")').first
            post_btn.click()
            
            time.sleep(3)
            
            return f"✅ LinkedIn post published ({len(content)} chars)"
        
        except Exception as inner_e:
            return f"⚠️ Could not create post: {repr(inner_e)}"
    
    except Exception as e:
        return f"⚠️ LinkedIn post error: {repr(e)}"


def _linkedin_job_search_impl(
    ctx: ToolContext,
    keywords: str,
    location: str = "Remote",
    date_posted: str = "week",
    max_results: int = 10
) -> str:
    """Search for jobs on LinkedIn."""
    try:
        page = ctx.browser_state.page
        
        # Build search URL
        date_filters = {"all": "", "month": "r2592000", "week": "r604800", "day": "r86400"}
        date_param = date_filters.get(date_posted, "r604800")
        
        search_url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={keywords.replace(' ', '%20')}"
            f"&location={location.replace(' ', '%20')}"
            f"&f_TPR={date_param}"
        )
        
        page.goto(search_url, wait_until="networkidle", timeout=30000)
        time.sleep(3)
        
        # Extract job listings
        jobs = []
        job_cards = page.locator('div.job-card-container--clickable').all()
        
        for i, card in enumerate(job_cards[:max_results]):
            try:
                title_el = card.locator('div.job-card-list__title').first
                company_el = card.locator('div.job-card-container__company-name').first
                location_el = card.locator('div.job-card-container__metadata-item').first
                
                title = title_el.inner_text() if title_el.count() > 0 else "Unknown"
                company = company_el.inner_text() if company_el.count() > 0 else "Unknown"
                job_location = location_el.inner_text() if location_el.count() > 0 else "Unknown"
                
                # Get job link
                link_el = card.locator('a.job-card-list__title').first
                link = link_el.get_attribute('href') if link_el.count() > 0 else ""
                
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": job_location,
                    "url": f"https://www.linkedin.com{link}" if link else ""
                })
            except Exception:
                continue
        
        if not jobs:
            return f"📭 No jobs found for '{keywords}' in {location}"
        
        # Format results
        lines = [f"💼 Found {len(jobs)} jobs for '{keywords}':\n"]
        for i, job in enumerate(jobs, 1):
            lines.append(
                f"{i}. **{job['title']}** at {job['company']}\n"
                f"   📍 {job['location']}\n"
                f"   🔗 {job['url']}\n"
            )
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"⚠️ Job search error: {repr(e)}"


def _linkedin_apply_impl(ctx: ToolContext, job_url: str) -> str:
    """Apply to a LinkedIn job (Easy Apply only)."""
    try:
        page = ctx.browser_state.page
        
        # Navigate to job
        page.goto(job_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        
        # Look for Easy Apply button
        try:
            apply_btn = page.locator('button.jobs-apply-button').first
            apply_btn.click()
            time.sleep(2)
            
            # Check if it's Easy Apply (modal should appear)
            modal = page.locator('div.jobs-easy-apply-modal')
            if modal.count() > 0:
                return "✅ Easy Apply started. Check browser for additional steps."
            else:
                return "⚠️ Not an Easy Apply job. Manual application required."
        
        except Exception:
            return "⚠️ No Easy Apply button found. Manual application required."
    
    except Exception as e:
        return f"⚠️ Apply error: {repr(e)}"


def _schedule_linkedin_post_impl(
    ctx: ToolContext,
    content: str,
    times_per_day: int = 2,
    interval_hours: int = 12
) -> str:
    """Schedule regular LinkedIn posts."""
    import uuid
    from supervisor.queue import enqueue_task
    
    schedule_id = uuid.uuid4().hex[:8]
    
    enqueue_task({
        "id": schedule_id,
        "type": "linkedin_post_schedule",
        "chat_id": int(ctx.current_chat_id or 0),
        "text": f"SCHEDULED LINKEDIN POST: {content[:100]}...",
        "content": content,
        "times_per_day": times_per_day,
        "interval_hours": interval_hours,
    })
    
    return f"✅ LinkedIn post scheduled (ID: {schedule_id}), {times_per_day}x/day"


def _schedule_linkedin_monitoring_impl(
    ctx: ToolContext,
    keywords: str,
    location: str = "Remote",
    check_interval_hours: int = 6
) -> str:
    """Schedule LinkedIn job monitoring."""
    import uuid
    from supervisor.queue import enqueue_task
    
    schedule_id = uuid.uuid4().hex[:8]
    
    enqueue_task({
        "id": schedule_id,
        "type": "linkedin_job_monitor",
        "chat_id": int(ctx.current_chat_id or 0),
        "text": f"SCHEDULED LINKEDIN MONITOR: {keywords}",
        "keywords": keywords,
        "location": location,
        "check_interval_hours": check_interval_hours,
    })
    
    return f"✅ LinkedIn monitoring scheduled (ID: {schedule_id}), every {check_interval_hours}h"


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("linkedin_login", {
            "name": "linkedin_login",
            "description": "Login to LinkedIn using stored credentials. Requires store_credentials first.",
            "parameters": {"type": "object", "properties": {
                "email": {"type": "string", "description": "Optional: override email"},
            }},
        }, _linkedin_login_impl),
        
        ToolEntry("linkedin_post", {
            "name": "linkedin_post",
            "description": "Create a post on LinkedIn. Must be logged in first.",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string", "description": "Post content"},
                "visibility": {"type": "string", "description": "public, connections, or group"},
            }, "required": ["content"]},
        }, _linkedin_post_impl),
        
        ToolEntry("linkedin_job_search", {
            "name": "linkedin_job_search",
            "description": "Search for jobs on LinkedIn with filters.",
            "parameters": {"type": "object", "properties": {
                "keywords": {"type": "string", "description": "Job keywords"},
                "location": {"type": "string", "description": "Location (default: Remote)"},
                "date_posted": {"type": "string", "description": "all, month, week, day"},
                "max_results": {"type": "integer", "description": "Max results (default: 10)"},
            }, "required": ["keywords"]},
        }, _linkedin_job_search_impl),
        
        ToolEntry("linkedin_apply", {
            "name": "linkedin_apply",
            "description": "Apply to a LinkedIn job (Easy Apply only).",
            "parameters": {"type": "object", "properties": {
                "job_url": {"type": "string", "description": "LinkedIn job URL"},
            }, "required": ["job_url"]},
        }, _linkedin_apply_impl),
        
        ToolEntry("schedule_linkedin_post", {
            "name": "schedule_linkedin_post",
            "description": "Schedule regular LinkedIn posts (e.g., 2x/day).",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string", "description": "Post content"},
                "times_per_day": {"type": "integer", "description": "Posts per day (default: 2)"},
                "interval_hours": {"type": "integer", "description": "Hours between posts"},
            }, "required": ["content"]},
        }, _schedule_linkedin_post_impl),
        
        ToolEntry("schedule_linkedin_monitoring", {
            "name": "schedule_linkedin_monitoring",
            "description": "Schedule LinkedIn job monitoring with keywords.",
            "parameters": {"type": "object", "properties": {
                "keywords": {"type": "string", "description": "Job keywords to monitor"},
                "location": {"type": "string", "description": "Location (default: Remote)"},
                "check_interval_hours": {"type": "integer", "description": "Hours between checks"},
            }, "required": ["keywords"]},
        }, _schedule_linkedin_monitoring_impl),
    ]
