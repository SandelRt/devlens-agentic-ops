#!/usr/bin/env python3
"""
DevLens — Agentic Observability for Developers
Core AI Agent Module

This module implements the agentic investigation loop. Given a natural language
question from a developer, the agent:
  1. Plans a multi-step investigation strategy
  2. Generates and executes SPL queries against Splunk
  3. Analyzes results using Splunk Hosted Models
  4. Iterates if more information is needed
  5. Returns a developer-friendly root cause analysis

Targets the Splunk Agentic Ops Hackathon:
  - Observability track
  - Platform & Developer Experience track
  - Best Use of Splunk MCP Server
  - Best Use of Splunk Hosted Models
"""

import sys
import os
import json
import time
import logging
from typing import Optional

# Add bin directory to path for sibling module imports
sys.path.insert(0, os.path.dirname(__file__))

from spl_generator import SPLGenerator
from rca import RootCauseAnalyzer
from hosted_models import SplunkHostedModels

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("devlens.agent")

# Maximum agentic loop iterations to prevent runaway
MAX_ITERATIONS = 5


class DevLensAgent:
    """
    Agentic observability investigator for Splunk.

    The agent uses an iterative Reason-Act-Observe loop:
      - REASON: Analyze the question and available context
      - ACT: Generate and run a targeted SPL query
      - OBSERVE: Analyze the result, decide if the answer is found
      - Loop until confident or max iterations reached
    """

    def __init__(self, splunk_host: str, splunk_port: int, splunk_token: str, verify_ssl: bool = False):
        """
        Initialize the DevLens agent.

        Args:
            splunk_host: Splunk server hostname (e.g., "localhost")
            splunk_port: Splunk management port (default: 8089)
            splunk_token: Splunk authentication token or session key
            verify_ssl: Whether to verify SSL certificates
        """
        self.splunk_host = splunk_host
        self.splunk_port = splunk_port
        self.splunk_token = splunk_token
        self.verify_ssl = verify_ssl
        self.base_url = f"https://{splunk_host}:{splunk_port}"

        # Initialize sub-modules
        self.spl_gen = SPLGenerator(hosted_models=SplunkHostedModels(self.base_url, splunk_token))
        self.rca = RootCauseAnalyzer(hosted_models=SplunkHostedModels(self.base_url, splunk_token))
        self.hosted_models = SplunkHostedModels(self.base_url, splunk_token)

        logger.info(f"DevLensAgent initialized against {self.base_url}")

    def investigate(self, question: str, timerange: str = "-1h", index: str = "*") -> dict:
        """
        Main entry point: investigate a developer's observability question.

        Args:
            question: Natural language question (e.g., "Why are my APIs returning 500s?")
            timerange: Splunk time range string (default: last 1 hour)
            index: Splunk index to search (default: all)

        Returns:
            dict with keys:
                - question: the original question
                - answer: natural language root cause analysis
                - confidence: 0.0-1.0 confidence score
                - queries_run: list of SPL queries executed
                - evidence: list of key data points found
                - recommendations: list of suggested next steps
                - iterations: number of agentic loop iterations
        """
        logger.info(f"Starting investigation: '{question}' | timerange={timerange} | index={index}")

        investigation = {
            "question": question,
            "answer": "",
            "confidence": 0.0,
            "queries_run": [],
            "evidence": [],
            "recommendations": [],
            "iterations": 0,
            "status": "in_progress",
        }

        # Build initial context for the agent
        context = {
            "question": question,
            "timerange": timerange,
            "index": index,
            "findings": [],
            "iteration": 0,
        }

        for iteration in range(1, MAX_ITERATIONS + 1):
            context["iteration"] = iteration
            logger.info(f"Agent iteration {iteration}/{MAX_ITERATIONS}")

            # --- PLAN step: decide what SPL to run ---
            plan = self._plan(context)
            logger.info(f"Plan: {plan.get('rationale', 'N/A')[:120]}")

            if plan.get("investigation_complete"):
                logger.info("Agent determined investigation is complete")
                break

            spl_query = plan.get("spl_query", "")
            if not spl_query:
                logger.warning("No SPL query generated; halting loop")
                break

            # --- ACT step: execute the SPL query ---
            query_result = self._run_search(spl_query, timerange, index)
            investigation["queries_run"].append({"spl": spl_query, "rows": len(query_result.get("results", []))})

            if query_result.get("error"):
                logger.error(f"Search error: {query_result['error']}")
                # Try to repair the query on error
                context["last_error"] = query_result["error"]
                context["findings"].append({"type": "error", "query": spl_query, "error": query_result["error"]})
                continue

            # --- OBSERVE step: analyze results ---
            observation = self._observe(query_result, context)
            context["findings"].append({
                "type": "observation",
                "query": spl_query,
                "summary": observation.get("summary", ""),
                "key_values": observation.get("key_values", {}),
                "anomaly_detected": observation.get("anomaly_detected", False),
            })
            investigation["evidence"].extend(observation.get("evidence", []))
            investigation["iterations"] = iteration

            # Check if the agent is confident enough to answer
            if observation.get("confidence", 0.0) >= 0.80:
                logger.info(f"Sufficient confidence ({observation['confidence']:.2f}) reached")
                break

        # --- SYNTHESIZE final answer ---
        final = self.rca.synthesize(
            question=question,
            findings=context["findings"],
            queries_run=investigation["queries_run"],
        )

        investigation["answer"] = final.get("root_cause", "Unable to determine root cause with available data.")
        investigation["confidence"] = final.get("confidence", 0.0)
        investigation["recommendations"] = final.get("recommendations", [])
        investigation["status"] = "complete"

        logger.info(f"Investigation complete. Confidence: {investigation['confidence']:.2f}")
        return investigation

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _plan(self, context: dict) -> dict:
        """
        Ask the hosted model what SPL query to run next given current context.
        Returns a dict with 'spl_query', 'rationale', 'investigation_complete'.
        """
        system_prompt = """You are an expert Splunk observability engineer helping developers debug issues.
Given the developer's question and any prior investigation findings, decide what SPL (Splunk Query Language) query to run next.

Rules:
- Generate focused, efficient SPL queries
- Use the `index`, `sourcetype`, and time range context provided
- If prior queries revealed the answer, set investigation_complete=true
- Prefer queries that surface error rates, latency percentiles, or anomalous counts
- Always include `| stats` or `| timechart` to aggregate results meaningfully

Respond ONLY with a valid JSON object with keys:
  - spl_query: string (the SPL to run, or "" if done)
  - rationale: string (brief explanation of why this query)
  - investigation_complete: boolean
"""

        user_message = json.dumps({
            "developer_question": context["question"],
            "timerange": context["timerange"],
            "index": context["index"],
            "iteration": context["iteration"],
            "prior_findings": context.get("findings", [])[-3:],  # Last 3 findings for context window
            "last_error": context.get("last_error", None),
        }, indent=2)

        try:
            response_text = self.hosted_models.chat(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=512,
            )
            plan = json.loads(response_text)
            return plan
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Plan generation failed: {e}")
            # Fallback: generate a basic error-rate SPL
            return {
                "spl_query": self.spl_gen.generate_fallback_spl(context["question"], context["timerange"]),
                "rationale": "Fallback query after plan generation failure",
                "investigation_complete": False,
            }

    def _run_search(self, spl: str, timerange: str, index: str) -> dict:
        """
        Execute a synchronous Splunk search via REST API.
        Returns dict with 'results' list and optional 'error'.
        """
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        headers = {
            "Authorization": f"Splunk {self.splunk_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Prepend index restriction if not already in query
        full_spl = spl
        if index != "*" and f"index={index}" not in spl:
            full_spl = f"index={index} {spl}"

        search_body = {
            "search": f"search {full_spl}",
            "earliest_time": timerange,
            "latest_time": "now",
            "output_mode": "json",
            "exec_mode": "oneshot",  # Synchronous; times out in 30s
            "count": 100,
        }

        try:
            resp = requests.post(
                f"{self.base_url}/services/search/jobs",
                headers=headers,
                data=search_body,
                verify=self.verify_ssl,
                timeout=45,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            logger.info(f"Search returned {len(results)} rows")
            return {"results": results}
        except requests.RequestException as e:
            logger.error(f"Splunk REST search error: {e}")
            return {"results": [], "error": str(e)}

    def _observe(self, query_result: dict, context: dict) -> dict:
        """
        Analyze search results with the hosted model and extract key observations.
        """
        results = query_result.get("results", [])

        system_prompt = """You are an expert in application observability and performance analysis.
Analyze these Splunk search results in the context of a developer's question.

Extract:
- A concise summary of what the data shows
- Key numeric values (error rates, latencies, counts)
- Whether any anomaly is detected
- Your confidence (0.0-1.0) that this answers the question
- Specific evidence (facts from the data)

Respond ONLY with valid JSON with keys:
  - summary: string
  - key_values: object (key metric name -> value)
  - anomaly_detected: boolean
  - confidence: float 0.0-1.0
  - evidence: list of strings (specific data facts)
"""

        user_message = json.dumps({
            "developer_question": context["question"],
            "search_results": results[:20],  # Cap at 20 rows for token limit
            "row_count": len(results),
            "iteration": context["iteration"],
        }, indent=2)

        try:
            response_text = self.hosted_models.chat(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=600,
            )
            observation = json.loads(response_text)
            return observation
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Observation analysis failed: {e}")
            return {
                "summary": f"Retrieved {len(results)} records",
                "key_values": {},
                "anomaly_detected": len(results) > 0,
                "confidence": 0.3,
                "evidence": [f"Query returned {len(results)} rows"],
            }


# ---------------------------------------------------------------------------
# Custom Search Command interface (called by Splunk when used as a CSC)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # When invoked as a Splunk Custom Search Command:
    # | devlensagent question="Why are my APIs slow?"
    import splunk.Intersplunk as si

    try:
        keywords, options = si.getKeywordsAndOptions()
        question = options.get("question", " ".join(keywords) if keywords else "What is happening with my application?")
        timerange = options.get("timerange", "-1h")
        index = options.get("index", "*")

        # Read Splunk session info from stdin
        results, dummies, settings = si.getOrganizedResults()

        # Get auth token from session
        session_key = settings.get("sessionKey", "")
        splunk_uri = settings.get("splunkd_uri", "https://localhost:8089")
        host, port = "localhost", 8089
        if ":" in splunk_uri.split("//")[-1]:
            parts = splunk_uri.split("//")[-1].split(":")
            host = parts[0]
            port = int(parts[1].split("/")[0])

        agent = DevLensAgent(
            splunk_host=host,
            splunk_port=port,
            splunk_token=session_key,
        )

        result = agent.investigate(question=question, timerange=timerange, index=index)

        # Output as Splunk events
        output_events = [{
            "devlens_question": result["question"],
            "devlens_answer": result["answer"],
            "devlens_confidence": str(result["confidence"]),
            "devlens_iterations": str(result["iterations"]),
            "devlens_queries_run": str(len(result["queries_run"])),
            "devlens_recommendations": " | ".join(result["recommendations"][:3]),
            "devlens_status": result["status"],
        }]

        si.outputResults(output_events)

    except Exception as e:
        si.generateErrorResults(f"DevLens Agent Error: {str(e)}")
