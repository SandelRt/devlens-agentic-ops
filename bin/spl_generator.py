#!/usr/bin/env python3
"""
DevLens — SPL Generator

Translates natural language developer questions into Splunk Query Language (SPL).
Uses Splunk Hosted Models as the primary translation engine, with a curated
library of template queries as a fallback.

Key capability: A developer who doesn't know SPL can ask plain English questions
and get expert-level observability queries automatically.
"""

import re
import json
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from hosted_models import SplunkHostedModels

logger = logging.getLogger("devlens.spl_generator")

# --------------------------------------------------------------------------------------
# Template SPL library — used as fallback and for prompt enrichment
# Each template has: pattern (regex), spl (query), description
# --------------------------------------------------------------------------------------
SPL_TEMPLATES = [
    {
        "id": "http_error_rate",
        "pattern": r"(error|500|4\d\d|fail|broken|down|unavailable)",
        "spl": '| stats count as total, count(eval(status>=500)) as server_errors, count(eval(status>=400 AND status<500)) as client_errors by uri_path, service | eval error_rate=round(server_errors/total*100,2) | sort -error_rate | head 20',
        "description": "HTTP error rates by endpoint and service",
        "intent": "error_analysis",
    },
    {
        "id": "latency_spike",
        "pattern": r"(slow|latency|timeout|performance|response.?time|fast|speed)",
        "spl": '| stats avg(response_time_ms) as avg_ms, p50(response_time_ms) as p50_ms, p95(response_time_ms) as p95_ms, p99(response_time_ms) as p99_ms, max(response_time_ms) as max_ms by service, endpoint | sort -p99_ms | head 20',
        "description": "Response time percentiles by service and endpoint",
        "intent": "latency_analysis",
    },
    {
        "id": "deployment_correlation",
        "pattern": r"(deploy|release|version|rollout|push|update|upgrade|canary)",
        "spl": '| eval is_recent_deploy=if(_time > relative_time(now(), "-2h"), "yes", "no") | stats count, avg(response_time_ms) as avg_ms, count(eval(status>=500)) as errors by version, is_recent_deploy | sort -_time | head 20',
        "description": "Impact of recent deployments on error rates and latency",
        "intent": "deployment_analysis",
    },
    {
        "id": "throughput_drop",
        "pattern": r"(traffic|throughput|request.?rate|rps|tps|volume|drop|spike)",
        "spl": '| timechart span=5m count as requests, avg(response_time_ms) as avg_latency_ms, count(eval(status>=500)) as errors by service | head 100',
        "description": "Request volume and error rates over time (5-minute buckets)",
        "intent": "throughput_analysis",
    },
    {
        "id": "service_health",
        "pattern": r"(health|status|up|down|available|ok|alive|working)",
        "spl": '| stats latest(_time) as last_seen, count as events, avg(response_time_ms) as avg_ms, count(eval(status>=500)) as errors by service | eval health_score=round((1-(errors/events))*100,1) | sort -health_score',
        "description": "Overall health score per service",
        "intent": "health_check",
    },
    {
        "id": "database_errors",
        "pattern": r"(database|db|sql|query|postgres|mysql|redis|mongo|cassandra)",
        "spl": 'sourcetype=db_logs | stats count as queries, count(eval(status="error")) as errors, avg(duration_ms) as avg_ms, max(duration_ms) as max_ms by db_name, query_type | eval error_rate=round(errors/queries*100,2) | sort -error_rate',
        "description": "Database query error rates and latency",
        "intent": "database_analysis",
    },
    {
        "id": "top_errors",
        "pattern": r"(top|most.?common|frequent|worst|biggest|highest)",
        "spl": '| stats count by error_message, service, status | sort -count | head 20',
        "description": "Most frequent error messages by service",
        "intent": "error_frequency",
    },
    {
        "id": "resource_saturation",
        "pattern": r"(cpu|memory|disk|resource|saturation|capacity|host|node|pod|container)",
        "spl": 'sourcetype=metrics | stats max(cpu_percent) as max_cpu, avg(memory_percent) as avg_mem, max(disk_io_wait) as disk_wait by host | sort -max_cpu | head 20',
        "description": "Resource utilization by host",
        "intent": "resource_analysis",
    },
    {
        "id": "user_impact",
        "pattern": r"(user|customer|session|journey|experience|impact|affect|ux)",
        "spl": '| stats dc(user_id) as affected_users, count as sessions, avg(response_time_ms) as avg_ms, count(eval(status>=500)) as failed_requests by service | sort -affected_users',
        "description": "User impact analysis - affected sessions and errors",
        "intent": "user_impact_analysis",
    },
    {
        "id": "timeline_comparison",
        "pattern": r"(before|after|since|yesterday|last week|previous|compar|trend|change|regression)",
        "spl": '| timechart span=1h count as requests, avg(response_time_ms) as avg_ms, count(eval(status>=500)) as errors | addtotals col=false row=true | head 48',
        "description": "48-hour timeline comparison of key metrics",
        "intent": "timeline_analysis",
    },
]


class SPLGenerator:
    """
    Generates optimized SPL queries from natural language developer questions.

    Uses a two-stage approach:
    1. Template matching for common patterns (fast, reliable)
    2. LLM generation via Splunk Hosted Models for complex queries (flexible)
    """

    def __init__(self, hosted_models: Optional["SplunkHostedModels"] = None):
        self.hosted_models = hosted_models

    def generate(self, question: str, context: dict = None) -> dict:
        """
        Generate an SPL query from a natural language question.

        Args:
            question: Developer's natural language question
            context: Optional dict with 'index', 'timerange', 'prior_findings'

        Returns:
            dict with:
                - spl: the generated SPL query string
                - intent: detected intent category
                - method: 'template' | 'llm' | 'fallback'
                - matched_template: template ID if matched
        """
        context = context or {}

        # Stage 1: Try template matching first (fast path)
        template_match = self._match_template(question)
        if template_match:
            logger.info(f"Template match: {template_match['id']} | intent: {template_match['intent']}")
            return {
                "spl": template_match["spl"],
                "intent": template_match["intent"],
                "method": "template",
                "matched_template": template_match["id"],
                "description": template_match["description"],
            }

        # Stage 2: Use hosted model for complex/novel queries
        if self.hosted_models:
            llm_spl = self._generate_with_llm(question, context)
            if llm_spl:
                return {
                    "spl": llm_spl,
                    "intent": "llm_generated",
                    "method": "llm",
                    "matched_template": None,
                    "description": "LLM-generated query",
                }

        # Stage 3: Fallback to generic query
        return {
            "spl": self.generate_fallback_spl(question),
            "intent": "general",
            "method": "fallback",
            "matched_template": None,
            "description": "Generic observability query",
        }

    def generate_fallback_spl(self, question: str, timerange: str = "-1h") -> str:
        """Generate a basic fallback SPL query when all else fails."""
        question_lower = question.lower()

        if any(kw in question_lower for kw in ["error", "fail", "500", "exception"]):
            return "status>=400 | stats count by status, service, uri_path | sort -count | head 20"
        elif any(kw in question_lower for kw in ["slow", "latency", "time"]):
            return "| stats avg(response_time_ms) as avg_ms, p95(response_time_ms) as p95_ms by service | sort -p95_ms"
        else:
            return "| stats count by service, status | timechart span=5m count by service | head 50"

    def get_suggested_queries(self, question: str) -> list[dict]:
        """
        Return up to 3 relevant template queries to suggest to the developer.
        Used by the UI to show "related queries" next to the main answer.
        """
        suggestions = []
        question_lower = question.lower()

        for template in SPL_TEMPLATES:
            if re.search(template["pattern"], question_lower, re.IGNORECASE):
                suggestions.append({
                    "id": template["id"],
                    "description": template["description"],
                    "spl": template["spl"],
                    "intent": template["intent"],
                })
            if len(suggestions) >= 3:
                break

        # If nothing matched, return top 3 most common templates
        if not suggestions:
            suggestions = [
                {"id": t["id"], "description": t["description"], "spl": t["spl"], "intent": t["intent"]}
                for t in SPL_TEMPLATES[:3]
            ]

        return suggestions

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _match_template(self, question: str) -> Optional[dict]:
        """Find the best matching SPL template for the question."""
        question_lower = question.lower()
        for template in SPL_TEMPLATES:
            if re.search(template["pattern"], question_lower, re.IGNORECASE):
                return template
        return None

    def _generate_with_llm(self, question: str, context: dict) -> Optional[str]:
        """Use the hosted model to generate a custom SPL query."""
        # Build few-shot examples from templates for the LLM
        examples = "\n".join([
            f'Q: "{t["description"]}"\nSPL: {t["spl"]}'
            for t in SPL_TEMPLATES[:5]
        ])

        system_prompt = f"""You are an expert Splunk engineer. Generate a single, valid SPL query to answer a developer's observability question.

Guidelines:
- Use field names common in web application logs: status, response_time_ms, uri_path, service, version, user_id, error_message
- Always aggregate results: use | stats, | timechart, or | top
- Include | sort and | head 20 to limit results
- Return ONLY the SPL query string, no explanation

Examples:
{examples}
"""

        user_message = f'Generate SPL for: "{question}"\n\nIndex hint: {context.get("index", "*")}\nTime range: {context.get("timerange", "-1h")}'

        try:
            spl = self.hosted_models.chat(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=256,
                temperature=0.1,
            )
            # Clean up the response
            spl = spl.strip().strip("`").strip()
            # Remove "search" prefix if present
            if spl.lower().startswith("search "):
                spl = spl[7:]
            if spl:
                logger.info(f"LLM generated SPL: {spl[:100]}...")
                return spl
        except Exception as e:
            logger.error(f"LLM SPL generation failed: {e}")

        return None
