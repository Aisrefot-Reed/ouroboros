"""
LinkedIn integration tools.

Provides functionality to:
- Log in to LinkedIn
- Monitor job postings
- Apply to jobs automatically
- Manage LinkedIn profile
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


def _linkedin_login(ctx: ToolContext, email: str, password: str) -> str:
    """
    Log in to LinkedIn using browser automation.
    """
    try:
        from ouroboros.tools.browser import _ensure_browser
        
        page = _ensure_browser(ctx)
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        
        # Fill login credentials
        page.fill("#username", email)
        page.fill("#password", password)
        
        # Click login button
        page.click("button[type='submit']")
        
        # Wait for potential 2FA or dashboard
        page.wait_for_timeout(3000)
        
        # Check if login was successful by looking for dashboard elements
        if page.url.startswith("https://www.linkedin.com/feed"):
            return "Successfully logged in to LinkedIn"
        else:
            # Check for error messages
            try:
                error = page.inner_text(".error")
                return f"Login failed: {error}"
            except Exception as e:
                log.debug(f"Error checking for error message: {e}")
                return "Login may have failed - please check manually. Possible 2FA required."
    
    except Exception as e:
        return f"Error during LinkedIn login: {str(e)}"


def _linkedin_search_jobs(ctx: ToolContext, keywords: str, location: str = "", 
                          easy_apply_only: bool = False) -> str:
    """
    Search for jobs on LinkedIn with specified criteria.
    """
    try:
        from ouroboros.tools.browser import _ensure_browser
        
        page = _ensure_browser(ctx)
        
        # Build search URL
        search_params = f"keywords={keywords}"
        if location:
            search_params += f"&location={location}"
        if easy_apply_only:
            search_params += "&f_AL=true"  # Easy apply only
        
        search_url = f"https://www.linkedin.com/jobs/search/?{search_params}"
        page.goto(search_url, wait_until="domcontentloaded")
        
        # Wait for job listings to load
        page.wait_for_selector(".jobs-search__job-results-list", timeout=10000)
        
        # Extract job listings
        jobs = page.query_selector_all(".job-card-list__title")
        job_list = []
        
        for i, job in enumerate(jobs[:10]):  # Limit to first 10 jobs
            try:
                title = job.inner_text().strip()
                company = ""
                location = ""
                
                # Get company and location - these are relative to the job card
                job_card = job.locator("..")  # Get parent element
                
                try:
                    company_elem = job_card.locator(".job-card-container__primary-description")
                    if company_elem.count() > 0:
                        company = company_elem.inner_text().strip()
                except Exception as e:
                    log.debug(f"Error getting company for job {i}: {e}")
                
                try:
                    location_elem = job_card.locator(".job-card-container__metadata-item")
                    if location_elem.count() > 0:
                        location = location_elem.inner_text().strip()
                except Exception as e:
                    log.debug(f"Error getting location for job {i}: {e}")
                
                job_list.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "link": job.get_attribute("href")
                })
                
                if len(job_list) >= 10:  # Limit to 10 jobs
                    break
            except Exception as e:
                log.debug(f"Error parsing job {i}: {e}")
                continue
        
        if not job_list:
            return "No jobs found with the specified criteria"
        
        return json.dumps(job_list, indent=2, ensure_ascii=False)
    
    except Exception as e:
        return f"Error searching LinkedIn jobs: {str(e)}"


def _linkedin_apply_to_job(ctx: ToolContext, job_url: str) -> str:
    """
    Apply to a job on LinkedIn using Easy Apply if available.
    """
    try:
        from ouroboros.tools.browser import _ensure_browser
        
        page = _ensure_browser(ctx)
        page.goto(job_url, wait_until="domcontentloaded")
        
        # Wait for apply button
        try:
            # Look for Easy Apply button
            easy_apply_selector = "button.jobs-apply-button:has-text('Easy Apply')"
            page.wait_for_selector(easy_apply_selector, timeout=5000)
            
            # Click Easy Apply
            page.click(easy_apply_selector)
            
            # Handle the application process (simplified for now)
            # In a real implementation, this would need to handle multiple steps
            page.wait_for_selector("iframe[role='dialog']", timeout=5000)
            
            # For now, just close the dialog to avoid getting stuck
            try:
                page.click("button[aria-label='Dismiss']")
            except Exception as e:
                log.debug(f"Could not click dismiss button: {e}")
                try:
                    page.keyboard.press("Escape")
                except Exception as e2:
                    log.debug(f"Could not press escape key: {e2}")
            
            return f"Attempted to apply to job: {job_url} (Easy Apply process started but not completed automatically)"
        
        except Exception as e:
            # If Easy Apply isn't available, look for regular Apply button
            try:
                apply_selector = "button.jobs-apply-button:has-text('Apply')"
                page.wait_for_selector(apply_selector, timeout=3000)
                page.click(apply_selector)
                
                return f"Started application process for job: {job_url} (Redirected to external site)"
            except Exception as e2:
                return f"Could not find apply button for job: {job_url} - {str(e2)}"
    
    except Exception as e:
        return f"Error applying to job: {str(e)}"


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry(
            name="linkedin_login",
            schema={
                "name": "linkedin_login",
                "description": "Log in to LinkedIn using email and password",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "description": "LinkedIn email"},
                        "password": {"type": "string", "description": "LinkedIn password"}
                    },
                    "required": ["email", "password"]
                }
            },
            handler=_linkedin_login,
            timeout_sec=60
        ),
        ToolEntry(
            name="linkedin_search_jobs",
            schema={
                "name": "linkedin_search_jobs",
                "description": "Search for jobs on LinkedIn with keywords, location, and filters",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keywords": {"type": "string", "description": "Job keywords to search for"},
                        "location": {"type": "string", "description": "Location filter (optional)"},
                        "easy_apply_only": {"type": "boolean", "description": "Only show Easy Apply jobs (optional, default: false)"}
                    },
                    "required": ["keywords"]
                }
            },
            handler=_linkedin_search_jobs,
            timeout_sec=60
        ),
        ToolEntry(
            name="linkedin_apply_to_job",
            schema={
                "name": "linkedin_apply_to_job",
                "description": "Apply to a specific LinkedIn job posting",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_url": {"type": "string", "description": "URL of the job posting to apply to"}
                    },
                    "required": ["job_url"]
                }
            },
            handler=_linkedin_apply_to_job,
            timeout_sec=60
        )
    ]