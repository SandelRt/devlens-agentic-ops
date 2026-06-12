#!/usr/bin/env python3
"""
DevLens — Root Cause Analyzer

Synthesizes findings from multiple Splunk search iterations into a final
root cause analysis (RCA) report for the developer.

The RCA:
1. Identifies the primary root cause from collected evidence
2. Assigns a confidence score
3. Provides concrete, actionable recommendations
4. Cites specific data from the investigation

Uses Splunk Hosted Models for synthesis; falls back to rule-based logic
if the API is unavailable.
"""

import json
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from hosted_models import SplunkHostedModels

logger = logging.getLogger("devlens.rca")


# -----------------------------------------------------------------------
# Root cause pattern library for rule-based fallback
# -----------------------------------------------------------------------
RCA_PATTERNS = {
    "error_spike": {
        "triggers": ["error_rate > 5", "status >= 500", "count > 100 errors"],
        "root_cause_template": "Elevated error rate detected: {metric}. This often indicates a code bug in a recent deployment, downstream service failure, or infrastructure issue.",
        "recommendations": [
            "Check recent deployments for code changes affecting the failing endpoints",
            "Review downstream service health and dependencies",
            "Check application logs for stack traces near the error spike",
            "Consider rolling back the last deployment if error rate > 10%",
        ],
    },
    "latency_spike": {
        "triggers": ["p99_ms > 2000", "avg_ms > 500", "slow"],
        "root_cause_template": "Latency spike detected: {metric}. Common causes include database query degradation, memory pressure, connection pool exhaustion, or a traffic surge.",
        "recommendations": [
            "Check database query performance and index utilization",
            "Review memory and CPU utilization on affected hosts",
            "Check connection pool metrics for database and external services",
            "Analyze whether throughput increased simultaneously with latency",
        ],
    },
    "deployment_regression": {
        "triggers": ["deploy", "version", "release"],
        "root_cause_template": "Performance regression correlated with recent deployment version {metric}. Error rate or latency degraded after the deployment.",
        "recommendations": [
            "Review the diff for the deployment version showing the regression",
            "Run canary analysis comparing the new version to the previous baseline",
            "Consider rolling back to the previous stable version",
            "Run load tests in staging before re-deploying",
        ],
    },
    "resource_saturation": {
        "triggers": ["cpu > 80", "memory > 90", "disk_wait"],
        "root_cause_template": "Resource saturation detected: {metric}. The service is running out of compute resources, causing performance degradation.",
        "recommendations": [
            "Scale up the affected service (increase replicas or instance size)",
            "Check for memory leaks or CPU-intensive background jobs",
            "Review garbage collection metrics if using a JVM-based service",
            "Set resource alerts to trigger before saturation is reached",
        ],
    },
    "unknown": {
        "triggers": [],
        "root_cause_template": "Investigation complete. Evidence gathered: {metric}. Root cause is unclear from available data.",
        "recommendations": [
            "Enable more detailed logging on affected services",
            "Add distributed tracing (e.g., OpenTelemetry) to correlate requests across services",
            "Review Splunk indexes for additional relevant data sources",
            "Consult with the service team about recent changes",
        ],
    },
}


class RootCauseAnalyzer:
    """
    Synthesizes multi-step investigation findings into a final RCA report.
    """

    def __init__(self, hosted_models: Optional["SplunkHostedModels"] = None):
        self.hosted_models = hosted_models

    def synthesize(self, question: str, findings: list[dict], queries_run: list[dict]) -> dict:
        """
        Produce a final root cause analysis from investigation findings.

        Args:
            question: Original developer question
            findings: List of observation dicts from agent.py
            queries_run: List of SPL queries that were executed

        Returns:
            dict with:
                - root_cause: Natural language RCA explanation
                - confidence: float 0.0-1.0
                - recommendations: list of actionable steps
                - evidence_summary: structured evidence citations
                - spl_to_monitor: SPL query the developer can save as an alert
        """
        if not findings:
            return self._empty_result(question)

        # Try LLM-based synthesis first
        if self.hosted_models:
            try:
                return self._synthesize_with_llm(question, findings, queries_run)
            except Exception as e:
                logger.error(f"LLM synthesis failed: {e}; falling back to rule-based RCA")

        # Rule-based fallback
        return self._synthesize_rule_based(question, findings, queries_run)

    def _synthesize_with_llm(self, question: str, findings: list[dict], queries_run: list[dict]) -> dict:
        """Use Splunk Hosted Models to synthesize a coherent RCA."""
        system_prompt = """You are an expert Site Reliability Engineer (SRE) performing root cause analysis.

Given a developer's question and a list of investigation findings from Splunk queries, produce a comprehensive root cause analysis.

Your analysis must:
1. Clearly state the primary root cause in 2-3 sentences
2. Reference specific data points from the findings as evidence
3. Provide 3-5 concrete, actionable recommendations
4. Assign a confidence score (0.0-1.0) based on evidence quality
5. Suggest a monitoring SPL query the team can use as an ongoing alert

Respond ONLY with valid JSON:
{
  "root_cause": "string - 2-3 sentence explanation",
  "confidence": float,
  "recommendations": ["action 1", "action 2", ...],
  "evidence_summary": [{"claim": "...", "data": "..."}],
  "spl_to_monitor": "SPL query string for ongoing monitoring"
}
"""

        # Compress findings for LLM (keep most informative ones)
        evidence_findings = [
            f for f in findings
            if f.get("type") == "observation" and f.get("summary")
        ][-5:]  # Last 5 observations

        user_message = json.dumps({
            "developer_question": question,
            "investigation_findings": evidence_findings,
            "queries_executed_count": len(queries_run),
            "queries": [q.get("spl", "")[:100] for q in queries_run],
        }, indent=2)

        response_text = self.hosted_models.chat(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=800,
            temperature=0.2,
        )

        result = json.loads(response_text)

        # Ensure required fields are present
        result.setdefault("root_cause", "Root cause determined from investigation data.")
        result.setdefault("confidence", 0.7)
        result.setdefault("recommendations", ["Review the investigation findings in the DevLens dashboard"])
        result.setdefault("evidence_summary", [])
        result.setdefault("spl_to_monitor", "index=* status>=500 | stats count by service | where count > 10")

        logger.info(f"LLM RCA complete. Confidence: {result['confidence']:.2f}")
        return result

    def _synthesize_rule_based(self, question: str, findings: list[dict], queries_run: list[dict]) -> dict:
        """Rule-based RCA synthesis when LLM is unavailable."""
        # Aggregate key evidence from findings
        all_evidence = []
        anomalies_detected = 0
        confidence_sum = 0.0

        for finding in findings:
            if finding.get("type") == "observation":
                all_evidence.extend(finding.get("evidence", []))
                if finding.get("anomaly_detected"):
                    anomalies_detected += 1
                confidence_sum += finding.get("confidence", 0.0)

        avg_confidence = confidence_sum / max(len(findings), 1)

        # Detect pattern from evidence text
        evidence_text = " ".join(all_evidence).lower()
        question_lower = question.lower()
        combined_text = evidence_text + " " + question_lower

        pattern_key = "unknown"
        matched_metric = ""

        if any(kw in combined_text for kw in ["error", "500", "fail", "exception"]):
            pattern_key = "error_spike"
            matched_metric = "error rate > threshold"
        elif any(kw in combined_text for kw in ["slow", "latency", "timeout", "response_time"]):
            pattern_key = "latency_spike"
            matched_metric = "p99 latency > 2000ms"
        elif any(kw in combined_text for kw in ["deploy", "version", "release"]):
            pattern_key = "deployment_regression"
            matched_metric = "latest version"
        elif any(kw in combined_text for kw in ["cpu", "memory", "resource", "saturation"]):
            pattern_key = "resource_saturation"
            matched_metric = "resource utilization > threshold"

        pattern = RCA_PATTERNS[pattern_key]
        root_cause = pattern["root_cause_template"].format(metric=matched_metric or "observed data")

        # Include evidence in the answer
        if all_evidence:
            root_cause += f" Key observations: {'; '.join(all_evidence[:3])}."

        return {
            "root_cause": root_cause,
            "confidence": min(0.85, avg_confidence + (0.1 * anomalies_detected)),
            "recommendations": pattern["recommendations"],
            "evidence_summary": [{"claim": e, "data": "From Splunk search"} for e in all_evidence[:5]],
            "spl_to_monitor": self._suggest_monitor_spl(question),
        }

    def _empty_result(self, question: str) -> dict:
        """Return when no investigation data was collected."""
        return {
            "root_cause": "No data found in the specified time range and index. The system may not have data for this query, or the time range may be too narrow.",
            "confidence": 0.0,
            "recommendations": [
                "Verify that data is being ingested into Splunk for the relevant indexes",
                "Try broadening the time range (e.g., -6h or -24h)",
                "Check that the correct index is selected in DevLens settings",
                "Confirm the service names in your question match the data in Splunk",
            ],
            "evidence_summary": [],
            "spl_to_monitor": f"| stats count by service | sort -count | head 20",
        }

    def _suggest_monitor_spl(self, question: str) -> str:
        """Suggest an SPL query the developer can save as a Splunk alert."""
        q = question.lower()
        if any(kw in q for kw in ["error", "500", "fail"]):
            return 'status>=500 | stats count as errors by service | where errors > 10 | sort -errors'
        elif any(kw in q for kw in ["slow", "latency"]):
            return '| stats p99(response_time_ms) as p99_ms by service | where p99_ms > 2000 | sort -p99_ms'
        else:
            return '| stats count by service, status | sort -count | head 20'
