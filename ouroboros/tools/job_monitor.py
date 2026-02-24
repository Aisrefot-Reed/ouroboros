"""
Job and order monitoring system for LinkedIn and Kwork.

This module provides functionality to:
- Monitor LinkedIn for new job postings matching specific criteria
- Monitor Kwork for new orders matching specific criteria
- Automatically submit applications/proposals based on predefined rules
- Schedule periodic checks for new opportunities
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from pathlib import Path

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)


def _monitor_linkedin_jobs(ctx: ToolContext, criteria: Dict[str, Any]) -> str:
    """
    Monitor LinkedIn for jobs matching specified criteria and apply automatically.
    
    Args:
        ctx: Tool context
        criteria: Job matching criteria (title, location, salary, etc.)
        
    Returns:
        Status message
    """
    try:
        from ouroboros.tools.linkedin import linkedin_search_jobs, linkedin_apply_to_job
        
        search_params = {
            "query": criteria.get("query", ""),
            "location": criteria.get("location", ""),
            "remote": criteria.get("remote", None),
            "job_type": criteria.get("job_type", ""),
            "experience_level": criteria.get("experience_level", ""),
            "date_posted": criteria.get("date_posted", "w"),
        }
        
        # Perform job search
        search_results = linkedin_search_jobs(ctx, search_params)
        if "Error" in search_results or "error" in search_results.lower():
            return f"Search failed: {search_results}"
            
        try:
            jobs = json.loads(search_results)
            applied_count = 0
            
            for job in jobs:
                # Check if job matches additional criteria
                if _job_matches_criteria(job, criteria):
                    # Apply to job
                    apply_result = linkedin_apply_to_job(ctx, {
                        "job_id": job.get("job_id"),
                        "cover_letter": criteria.get("cover_letter", "")
                    })
                    
                    if "successfully" in apply_result.lower():
                        applied_count += 1
                        log.info(f"Applied to job {job.get('job_id')}: {job.get('title')}")
                    else:
                        log.warning(f"Failed to apply to job {job.get('job_id')}: {apply_result}")
                        
            return f"LinkedIn monitoring completed. Found {len(jobs)} jobs, applied to {applied_count} jobs."
        except json.JSONDecodeError:
            return f"Failed to parse search results: {search_results}"
    except Exception as e:
        log.error(f"Error in LinkedIn monitoring: {e}")
        return f"Error in LinkedIn monitoring: {str(e)}"


def _monitor_kwork_orders(ctx: ToolContext, criteria: Dict[str, Any]) -> str:
    """
    Monitor Kwork for orders matching specified criteria and submit proposals.
    
    Args:
        ctx: Tool context
        criteria: Order matching criteria (budget, skills, etc.)
        
    Returns:
        Status message
    """
    try:
        from ouroboros.tools.kwork import kwork_search_orders, kwork_submit_proposal
        
        search_params = {
            "query": criteria.get("query", ""),
            "category": criteria.get("category", ""),
            "subcategory": criteria.get("subcategory", ""),
            "min_budget": criteria.get("min_budget", 0),
            "max_budget": criteria.get("max_budget", 0),
            "skills": criteria.get("skills", ""),
        }
        
        # Perform order search
        search_results = kwork_search_orders(ctx, search_params)
        if "Error" in search_results or "error" in search_results.lower():
            return f"Search failed: {search_results}"
            
        try:
            orders = json.loads(search_results)
            proposed_count = 0
            
            for order in orders:
                # Check if order matches criteria
                if _order_matches_criteria(order, criteria):
                    # Submit proposal
                    proposal_result = kwork_submit_proposal(ctx, {
                        "order_id": order.get("order_id"),
                        "proposal_text": criteria.get("proposal_text", ""),
                        "bid_amount": order.get("budget", 0),  # Use order's budget or custom amount
                        "delivery_days": criteria.get("delivery_days", 7)
                    })
                    
                    if "successfully" in proposal_result.lower() or "proposal submitted" in proposal_result.lower():
                        proposed_count += 1
                        log.info(f"Submitted proposal to order {order.get('order_id')}: {order.get('title')}")
                    else:
                        log.warning(f"Failed to submit proposal for order {order.get('order_id')}: {proposal_result}")
                        
            return f"Kwork monitoring completed. Found {len(orders)} orders, submitted {proposed_count} proposals."
        except json.JSONDecodeError:
            return f"Failed to parse search results: {search_results}"
    except Exception as e:
        log.error(f"Error in Kwork monitoring: {e}")
        return f"Error in Kwork monitoring: {str(e)}"


def _job_matches_criteria(job: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
    """
    Check if a LinkedIn job matches the specified criteria.
    
    Args:
        job: Job data from LinkedIn search
        criteria: Criteria to match against
        
    Returns:
        True if job matches criteria, False otherwise
    """
    # Check title keywords
    title = job.get("title", "").lower()
    title_keywords = criteria.get("title_keywords", [])
    if title_keywords:
        if not any(keyword.lower() in title for keyword in title_keywords):
            return False
    
    # Check company
    company = job.get("company", "").lower()
    if "company" in criteria and criteria["company"].lower() not in company:
        return False
    
    # Check employment type (full-time, part-time, contract, etc.)
    emp_type = job.get("employment_type", "").lower()
    if "employment_type" in criteria and criteria["employment_type"].lower() != emp_type:
        return False
    
    # Check if remote work is acceptable
    is_remote = job.get("remote", False)
    if "remote_only" in criteria and criteria["remote_only"] and not is_remote:
        return False
    
    # Check salary if specified
    salary = job.get("salary", "")
    min_salary = criteria.get("min_salary", 0)
    if min_salary > 0 and salary:
        # Simple check - in real implementation we'd need better parsing
        try:
            # Extract numeric salary value (this is simplified)
            import re
            salary_nums = re.findall(r'\d+', salary.replace(',', ''))
            if salary_nums:
                max_salary = max(int(n) for n in salary_nums)
                if max_salary < min_salary:
                    return False
        except:
            pass  # If parsing fails, continue without salary check
    
    return True


def _order_matches_criteria(order: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
    """
    Check if a Kwork order matches the specified criteria.
    
    Args:
        order: Order data from Kwork search
        criteria: Criteria to match against
        
    Returns:
        True if order matches criteria, False otherwise
    """
    # Check title keywords
    title = order.get("title", "").lower()
    title_keywords = criteria.get("title_keywords", [])
    if title_keywords:
        if not any(keyword.lower() in title for keyword in title_keywords):
            return False
    
    # Check budget
    budget = order.get("budget", 0)
    min_budget = criteria.get("min_budget", 0)
    max_budget = criteria.get("max_budget", float('inf'))
    
    if budget < min_budget or budget > max_budget:
        return False
    
    # Check required skills
    required_skills = order.get("skills", [])
    desired_skills = criteria.get("required_skills", [])
    if desired_skills:
        skill_match = any(skill.lower() in [s.lower() for s in required_skills] for skill in desired_skills)
        if not skill_match:
            return False
    
    # Check category
    category = order.get("category", "").lower()
    if "category" in criteria and criteria["category"].lower() not in category:
        return False
    
    return True


def _schedule_monitoring(ctx: ToolContext, platform: str, criteria: Dict[str, Any], interval_minutes: int) -> str:
    """
    Schedule periodic monitoring for a platform.
    
    Args:
        ctx: Tool context
        platform: Platform to monitor ('linkedin' or 'kwork')
        criteria: Criteria for matching jobs/orders
        interval_minutes: How often to check (in minutes)
        
    Returns:
        Status message
    """
    try:
        # Save monitoring configuration
        config_path = ctx.drive_path("job_monitor_config.json")
        
        if config_path.exists():
            config = json.loads(config_path.read_text())
        else:
            config = {}
        
        config[f"{platform}_monitoring"] = {
            "criteria": criteria,
            "interval_minutes": interval_minutes,
            "enabled": True,
            "last_run": None
        }
        
        config_path.write_text(json.dumps(config, indent=2))
        
        return f"Successfully scheduled {platform} monitoring every {interval_minutes} minutes with specified criteria."
    except Exception as e:
        log.error(f"Error scheduling monitoring: {e}")
        return f"Error scheduling monitoring: {str(e)}"


def _get_monitoring_status(ctx: ToolContext) -> str:
    """
    Get current status of job/order monitoring.
    
    Args:
        ctx: Tool context
        
    Returns:
        JSON string with monitoring status
    """
    try:
        config_path = ctx.drive_path("job_monitor_config.json")
        if config_path.exists():
            config = json.loads(config_path.read_text())
            return json.dumps(config, indent=2)
        else:
            return json.dumps({}, indent=2)
    except Exception as e:
        log.error(f"Error getting monitoring status: {e}")
        return f"Error getting monitoring status: {str(e)}"


def _stop_monitoring(ctx: ToolContext, platform: str) -> str:
    """
    Stop scheduled monitoring for a platform.
    
    Args:
        ctx: Tool context
        platform: Platform to stop monitoring ('linkedin' or 'kwork')
        
    Returns:
        Status message
    """
    try:
        config_path = ctx.drive_path("job_monitor_config.json")
        
        if config_path.exists():
            config = json.loads(config_path.read_text())
            
            if f"{platform}_monitoring" in config:
                config[f"{platform}_monitoring"]["enabled"] = False
                config_path.write_text(json.dumps(config, indent=2))
                return f"Stopped {platform} monitoring."
            else:
                return f"No active monitoring found for {platform}."
        else:
            return f"No monitoring configuration found for {platform}."
    except Exception as e:
        log.error(f"Error stopping monitoring: {e}")
        return f"Error stopping monitoring: {str(e)}"


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry(
            name="monitor_linkedin_jobs",
            schema={
                "name": "monitor_linkedin_jobs",
                "description": "Monitor LinkedIn for jobs matching criteria and apply automatically",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "criteria": {
                            "type": "object",
                            "description": "Job matching criteria",
                            "properties": {
                                "query": {"type": "string", "description": "Job search query"},
                                "location": {"type": "string", "description": "Job location"},
                                "remote": {"type": "boolean", "description": "Whether remote work is acceptable"},
                                "job_type": {"type": "string", "description": "Job type (full-time, part-time, contract)"},
                                "experience_level": {"type": "string", "description": "Required experience level"},
                                "date_posted": {"type": "string", "description": "Date posted filter (any, w=week, m=month)"},
                                "title_keywords": {
                                    "type": "array", 
                                    "items": {"type": "string"},
                                    "description": "Keywords that must be in job title"
                                },
                                "company": {"type": "string", "description": "Specific company to target"},
                                "employment_type": {"type": "string", "description": "Employment type (full-time, part-time)"},
                                "remote_only": {"type": "boolean", "description": "Only show remote jobs"},
                                "min_salary": {"type": "number", "description": "Minimum salary requirement"},
                                "cover_letter": {"type": "string", "description": "Cover letter template for applications"}
                            }
                        }
                    },
                    "required": ["criteria"]
                }
            },
            handler=_monitor_linkedin_jobs,
            timeout_sec=120
        ),
        ToolEntry(
            name="monitor_kwork_orders",
            schema={
                "name": "monitor_kwork_orders",
                "description": "Monitor Kwork for orders matching criteria and submit proposals",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "criteria": {
                            "type": "object",
                            "description": "Order matching criteria",
                            "properties": {
                                "query": {"type": "string", "description": "Order search query"},
                                "category": {"type": "string", "description": "Order category"},
                                "subcategory": {"type": "string", "description": "Order subcategory"},
                                "min_budget": {"type": "number", "description": "Minimum budget"},
                                "max_budget": {"type": "number", "description": "Maximum budget"},
                                "skills": {"type": "string", "description": "Required skills"},
                                "title_keywords": {
                                    "type": "array", 
                                    "items": {"type": "string"},
                                    "description": "Keywords that must be in order title"
                                },
                                "required_skills": {
                                    "type": "array", 
                                    "items": {"type": "string"},
                                    "description": "Skills required for the order"
                                },
                                "proposal_text": {"type": "string", "description": "Proposal template text"},
                                "delivery_days": {"type": "number", "description": "Delivery time in days"}
                            }
                        }
                    },
                    "required": ["criteria"]
                }
            },
            handler=_monitor_kwork_orders,
            timeout_sec=120
        ),
        ToolEntry(
            name="schedule_monitoring",
            schema={
                "name": "schedule_monitoring",
                "description": "Schedule periodic monitoring for LinkedIn or Kwork with specified criteria",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "description": "Platform to monitor (linkedin or kwork)"},
                        "criteria": {
                            "type": "object",
                            "description": "Criteria for matching jobs/orders",
                            "properties": {
                                "query": {"type": "string", "description": "Search query"},
                                "title_keywords": {
                                    "type": "array", 
                                    "items": {"type": "string"},
                                    "description": "Keywords that must be in title"
                                },
                                "min_budget": {"type": "number", "description": "Minimum budget (for Kwork)"},
                                "max_budget": {"type": "number", "description": "Maximum budget (for Kwork)"},
                                "required_skills": {
                                    "type": "array", 
                                    "items": {"type": "string"},
                                    "description": "Skills required"
                                },
                                "location": {"type": "string", "description": "Location (for LinkedIn)"},
                                "min_salary": {"type": "number", "description": "Minimum salary (for LinkedIn)"},
                                "cover_letter": {"type": "string", "description": "Cover letter template (for LinkedIn)"},
                                "proposal_text": {"type": "string", "description": "Proposal template (for Kwork)"},
                                "delivery_days": {"type": "number", "description": "Delivery days (for Kwork)"}
                            }
                        },
                        "interval_minutes": {"type": "number", "description": "How often to check in minutes"}
                    },
                    "required": ["platform", "criteria", "interval_minutes"]
                }
            },
            handler=_schedule_monitoring,
            timeout_sec=30
        ),
        ToolEntry(
            name="get_monitoring_status",
            schema={
                "name": "get_monitoring_status",
                "description": "Get current status of job/order monitoring",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            handler=_get_monitoring_status,
            timeout_sec=30
        ),
        ToolEntry(
            name="stop_monitoring",
            schema={
                "name": "stop_monitoring",
                "description": "Stop scheduled monitoring for a platform",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "description": "Platform to stop monitoring (linkedin or kwork)"}
                    },
                    "required": ["platform"]
                }
            },
            handler=_stop_monitoring,
            timeout_sec=30
        )
    ]