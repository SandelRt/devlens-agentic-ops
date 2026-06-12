#!/usr/bin/env python3
"""
DevLens — Splunk Hosted Models Client

Provides a clean interface to Splunk's hosted AI models (GA Feb 2026).
Supports:
  - Cisco Foundation AI (general reasoning)
  - Cisco Deep Time Series Model (beta, for metric anomaly detection)
  - OSS LLMs: 20B and 120B parameter models

Reference: https://docs.splunk.com/Documentation/SplunkCloud/latest/Admin/HostedModels
"""

import json
import logging
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("devlens.hosted_models")


# Available Splunk Hosted Model names (as of 2026)
MODEL_CISCO_FOUNDATION = "cisco-foundation-ai"        # General reasoning, security-aware
MODEL_CISCO_TIMESERIES = "cisco-deep-time-series"     # Time-series anomaly detection (beta)
MODEL_OSS_20B = "oss-llm-20b"                         # Open-source 20B param model
MODEL_OSS_120B = "oss-llm-120b"                       # Open-source 120B param model (best quality)

# Default model to use
DEFAULT_MODEL = MODEL_CISCO_FOUNDATION


class SplunkHostedModels:
    """
    Client for Splunk's built-in hosted AI models.

    Uses the Splunk REST API endpoint at /services/ml/hosted-models/<model>/predict
    to send chat-style prompts and receive completions from hosted models.
    """

    def __init__(self, base_url: str, token: str, verify_ssl: bool = False):
        """
        Args:
            base_url: Splunk base URL, e.g. "https://localhost:8089"
            token: Splunk auth token (session key or API token)
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Splunk {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def chat(
        self,
        user_message: str,
        system_prompt: str = "",
        model: str = DEFAULT_MODEL,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        """
        Send a chat-style prompt to a Splunk Hosted Model.

        Args:
            user_message: The user's input message
            system_prompt: Optional system context for the model
            model: Model identifier (use MODULE constants above)
            max_tokens: Maximum tokens in the response
            temperature: Sampling temperature (lower = more deterministic)

        Returns:
            String response from the model.

        Raises:
            RuntimeError: If the API call fails after retries
        """
        endpoint = f"{self.base_url}/services/ml/hosted-models/{model}/predict"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        logger.debug(f"Calling hosted model '{model}' | max_tokens={max_tokens}")

        try:
            resp = self.session.post(
                endpoint,
                json=payload,
                verify=self.verify_ssl,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            # Parse response — Splunk follows OpenAI-compatible response format
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                # Fallback: some versions return in 'predictions' field
                content = data.get("predictions", [""])[0]

            logger.debug(f"Hosted model responded: {len(content)} chars")
            return content.strip()

        except requests.HTTPError as e:
            status = e.response.status_code if e.response else "unknown"
            logger.error(f"Hosted model API error (HTTP {status}): {e}")
            # Fallback to mock response for demo if API unavailable
            if status == 404:
                logger.warning("Hosted model endpoint not found. Using rule-based fallback.")
                return self._rule_based_fallback(user_message, system_prompt)
            raise RuntimeError(f"Hosted model request failed: {e}") from e

        except requests.RequestException as e:
            logger.error(f"Network error calling hosted model: {e}")
            logger.warning("Falling back to rule-based analysis")
            return self._rule_based_fallback(user_message, system_prompt)

    def detect_anomaly(self, time_series_data: list[dict], metric_name: str) -> dict:
        """
        Use the Cisco Deep Time Series model to detect anomalies in metric data.

        Args:
            time_series_data: List of {timestamp, value} dicts
            metric_name: Name of the metric being analyzed

        Returns:
            dict with 'is_anomalous', 'anomaly_score', 'explanation'
        """
        if not time_series_data:
            return {"is_anomalous": False, "anomaly_score": 0.0, "explanation": "No data provided"}

        endpoint = f"{self.base_url}/services/ml/hosted-models/{MODEL_CISCO_TIMESERIES}/predict"

        payload = {
            "metric_name": metric_name,
            "time_series": time_series_data,
            "detection_sensitivity": "medium",
        }

        try:
            resp = self.session.post(
                endpoint,
                json=payload,
                verify=self.verify_ssl,
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            return {
                "is_anomalous": result.get("is_anomalous", False),
                "anomaly_score": result.get("anomaly_score", 0.0),
                "explanation": result.get("explanation", ""),
            }
        except Exception as e:
            logger.error(f"Time series anomaly detection failed: {e}")
            # Simple heuristic fallback
            values = [d.get("value", 0) for d in time_series_data]
            if values:
                mean = sum(values) / len(values)
                latest = values[-1]
                deviation = abs(latest - mean) / (mean + 1e-9)
                is_anomalous = deviation > 0.5
                return {
                    "is_anomalous": is_anomalous,
                    "anomaly_score": min(1.0, deviation),
                    "explanation": f"Latest value ({latest:.2f}) deviates {deviation*100:.0f}% from mean ({mean:.2f})",
                }
            return {"is_anomalous": False, "anomaly_score": 0.0, "explanation": "Insufficient data"}

    def _rule_based_fallback(self, user_message: str, system_prompt: str) -> str:
        """
        Rule-based fallback when the hosted model API is unavailable.
        Returns a plausible JSON response based on keyword detection.
        """
        msg_lower = user_message.lower()

        # Detect what kind of response is expected from system_prompt
        if "spl_query" in system_prompt and "investigation_complete" in system_prompt:
            # Plan step — generate a basic SPL
            if "error" in msg_lower or "500" in msg_lower or "fail" in msg_lower:
                spl = 'status>=500 | stats count by status, uri_path | sort -count'
            elif "slow" in msg_lower or "latency" in msg_lower or "timeout" in msg_lower:
                spl = '| stats avg(response_time_ms) as avg_ms, p99(response_time_ms) as p99_ms by service | sort -p99_ms'
            elif "deploy" in msg_lower:
                spl = 'sourcetype=deployment | stats count by version, status | sort -_time'
            else:
                spl = '| stats count by status, service | sort -count'

            return json.dumps({
                "spl_query": spl,
                "rationale": "Rule-based fallback query (hosted model unavailable)",
                "investigation_complete": False,
            })

        elif "summary" in system_prompt and "confidence" in system_prompt:
            # Observe step — return a basic observation
            return json.dumps({
                "summary": "Data retrieved and analyzed (rule-based fallback mode)",
                "key_values": {},
                "anomaly_detected": False,
                "confidence": 0.5,
                "evidence": ["Hosted model unavailable; using rule-based analysis"],
            })

        else:
            return json.dumps({
                "root_cause": "Analysis performed using rule-based fallback (hosted model unavailable). Please check Splunk Hosted Models configuration.",
                "confidence": 0.4,
                "recommendations": [
                    "Verify Splunk Hosted Models are enabled in your Splunk instance",
                    "Check the /services/ml/hosted-models endpoint availability",
                    "Review DevLens logs for connection errors",
                ],
            })
