#!/usr/bin/env python3
"""
DevLens — Synthetic Observability Data Generator

Generates realistic application observability data for the DevLens demo:
  - HTTP access logs with error spikes and latency anomalies
  - Deployment events correlated with regressions
  - Infrastructure metrics (CPU, memory)
  - Database query logs

Output: CSV files that can be loaded into Splunk via Data Inputs > Files

Usage:
  python generate_demo_data.py [--output-dir ./data] [--days 2]

The generated data includes a realistic scenario:
  - v2.4.1 deployment to payment-svc at ~2 hours ago
  - Post-deployment latency spike from 320ms → 2,840ms p99
  - Redis connection pool exhaustion on inventory-api
  - 3× normal error rate on payment-svc endpoints
"""

import csv
import json
import math
import random
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

random.seed(42)  # Reproducible data

# ---------------------------------------------------------------------------
# Services and endpoints
# ---------------------------------------------------------------------------
SERVICES = {
    "checkout-api": {
        "endpoints": ["/cart/add", "/cart/calculate", "/cart/view", "/checkout/start", "/checkout/finalize"],
        "base_rps": 45,
        "base_latency_ms": 95,
        "base_error_rate": 0.002,
    },
    "payment-svc": {
        "endpoints": ["/payment/initiate", "/payment/confirm", "/payment/refund", "/payment/status"],
        "base_rps": 22,
        "base_latency_ms": 240,
        "base_error_rate": 0.003,
    },
    "user-auth": {
        "endpoints": ["/auth/login", "/auth/logout", "/auth/refresh", "/auth/verify"],
        "base_rps": 80,
        "base_latency_ms": 45,
        "base_error_rate": 0.001,
    },
    "inventory-api": {
        "endpoints": ["/api/stock/check", "/api/stock/reserve", "/api/products/list", "/api/products/detail"],
        "base_rps": 120,
        "base_latency_ms": 35,
        "base_error_rate": 0.002,
    },
    "search-svc": {
        "endpoints": ["/search", "/search/suggest", "/search/facets", "/search/products"],
        "base_rps": 200,
        "base_latency_ms": 180,
        "base_error_rate": 0.001,
    },
}

VERSIONS = {
    "checkout-api": "v2.3.4",
    "payment-svc": "v2.4.1",  # This one regressed
    "user-auth": "v1.8.0",
    "inventory-api": "v3.1.2",
    "search-svc": "v4.0.5",
}

PREV_VERSIONS = {
    "payment-svc": "v2.4.0",
}

USERS = [f"user_{i:06d}" for i in range(1, 10001)]
HOSTS = {svc: [f"{svc.replace('-','_')}_pod_{i}" for i in range(1, 4)] for svc in SERVICES}


# ---------------------------------------------------------------------------
# Anomaly windows (2 hours back from "now")
# ---------------------------------------------------------------------------
def now():
    return datetime.now(timezone.utc)

def get_anomaly_config(base_time: datetime):
    """Define when anomalies start relative to NOW."""
    return {
        "payment_deploy_time": base_time - timedelta(hours=2),  # Deployment happened 2h ago
        "inventory_redis_start": base_time - timedelta(minutes=23),  # Redis issue 23 min ago
        "redis_recovery_time": None,  # Still ongoing
    }


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------
def generate_access_logs(base_time: datetime, hours: int = 6, interval_seconds: int = 1) -> list[dict]:
    """Generate realistic HTTP access log entries."""
    rows = []
    anomalies = get_anomaly_config(base_time)
    deploy_time = anomalies["payment_deploy_time"]
    redis_start = anomalies["inventory_redis_start"]

    start_time = base_time - timedelta(hours=hours)
    t = start_time

    while t < base_time:
        for service, config in SERVICES.items():
            rps = config["base_rps"]

            # Scale requests by time of day
            hour_of_day = t.hour
            traffic_multiplier = 0.3 + 0.7 * math.sin(math.pi * (hour_of_day - 6) / 12) if 6 <= hour_of_day <= 22 else 0.15
            actual_requests = max(1, int(rps * traffic_multiplier * interval_seconds))

            # Spike traffic during a campaign (1h ago)
            if t > base_time - timedelta(hours=1):
                actual_requests = int(actual_requests * 4) if service == "inventory-api" else actual_requests

            for _ in range(actual_requests):
                endpoint = random.choice(config["endpoints"])
                latency = max(1, random.lognormvariate(math.log(config["base_latency_ms"]), 0.4))
                status = 200
                error_msg = None

                # Payment-svc regression after deployment
                if service == "payment-svc" and t > deploy_time:
                    latency *= random.uniform(3.5, 9.0)  # 9× slowdown
                    if random.random() < 0.12:  # 12% error rate post-deploy (was 0.3%)
                        status = 500
                        error_msg = "TaxCalculationException: negative tax value in locale en_UK"

                # Inventory-api Redis exhaustion
                elif service == "inventory-api" and t > redis_start and endpoint == "/api/stock/check":
                    if random.random() < 0.127:  # 12.7% error rate
                        status = 500
                        error_msg = "redis.exceptions.ConnectionError: max connections exceeded (pool_size=10)"
                    else:
                        latency *= random.uniform(1.2, 2.5)

                # Normal random errors
                elif random.random() < config["base_error_rate"]:
                    status = random.choice([400, 404, 422, 500])
                    error_msg = random.choice([
                        "ValidationError: required field missing",
                        "TimeoutError: upstream service timeout",
                        "DatabaseError: query timeout",
                        None,
                    ])

                rows.append({
                    "_time": t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(0, 999):03d}Z",
                    "service": service,
                    "version": VERSIONS[service],
                    "host": random.choice(HOSTS[service]),
                    "method": random.choice(["GET", "GET", "GET", "POST", "POST"]),
                    "uri_path": endpoint,
                    "status": status,
                    "response_time_ms": round(latency, 2),
                    "user_id": random.choice(USERS) if random.random() > 0.1 else "",
                    "bytes_sent": random.randint(200, 50000),
                    "error_message": error_msg or "",
                    "sourcetype": "access_combined",
                    "index": "main",
                })

        t += timedelta(seconds=interval_seconds)

    return rows


def generate_deployment_events(base_time: datetime) -> list[dict]:
    """Generate deployment event records."""
    anomalies = get_anomaly_config(base_time)
    events = [
        {
            "_time": (anomalies["payment_deploy_time"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "service": "payment-svc",
            "version": "v2.4.1",
            "previous_version": "v2.4.0",
            "status": "success",
            "deployed_by": "ci-cd-bot",
            "environment": "production",
            "deployment_id": "deploy-20260611-1423",
            "sourcetype": "deployment",
            "index": "main",
        },
        {
            "_time": (base_time - timedelta(hours=5, minutes=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "service": "inventory-api",
            "version": "v3.1.2",
            "previous_version": "v3.1.1",
            "status": "success",
            "deployed_by": "jane.smith",
            "environment": "production",
            "deployment_id": "deploy-20260611-1308",
            "sourcetype": "deployment",
            "index": "main",
        },
        {
            "_time": (base_time - timedelta(hours=3, minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "service": "search-svc",
            "version": "v4.0.5",
            "previous_version": "v4.0.4",
            "status": "success",
            "deployed_by": "alex.chen",
            "environment": "production",
            "deployment_id": "deploy-20260611-1515",
            "sourcetype": "deployment",
            "index": "main",
        },
    ]
    return events


def generate_infrastructure_metrics(base_time: datetime, hours: int = 6) -> list[dict]:
    """Generate host resource utilization metrics."""
    rows = []
    start_time = base_time - timedelta(hours=hours)
    t = start_time

    while t < base_time:
        for service, hosts in HOSTS.items():
            for host in hosts:
                cpu = random.gauss(35, 8)
                memory = random.gauss(62, 6)
                disk_io_wait = random.gauss(5, 2)

                # Payment-svc hosts show increased CPU post-deploy
                if service == "payment-svc" and t > (base_time - timedelta(hours=2)):
                    cpu = random.gauss(78, 10)  # High CPU
                    memory = random.gauss(88, 5)

                # Inventory-api hosts show Redis connection issues
                if service == "inventory-api" and t > (base_time - timedelta(minutes=23)):
                    cpu = random.gauss(91, 5)

                rows.append({
                    "_time": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "host": host,
                    "service": service,
                    "cpu_percent": max(0, min(100, round(cpu, 1))),
                    "memory_percent": max(0, min(100, round(memory, 1))),
                    "disk_io_wait": max(0, round(disk_io_wait, 1)),
                    "network_rx_mb": round(random.gauss(45, 10), 2),
                    "network_tx_mb": round(random.gauss(12, 3), 2),
                    "sourcetype": "metrics",
                    "index": "metrics",
                })

        t += timedelta(minutes=1)

    return rows


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------
def write_csv(rows: list[dict], filepath: str):
    if not rows:
        print(f"  [WARNING] No rows to write for {filepath}")
        return

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    size_kb = os.path.getsize(filepath) / 1024
    print(f"  [OK] {filepath} -- {len(rows):,} rows ({size_kb:.1f} KB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate DevLens demo data for Splunk")
    parser.add_argument("--output-dir", default="./data", help="Output directory for CSV files")
    parser.add_argument("--hours", type=int, default=6, help="Hours of history to generate")
    args = parser.parse_args()

    base_time = now()
    output_dir = args.output_dir

    print("\n[DevLens] Demo Data Generator")
    print(f"   Generating {args.hours}h of synthetic observability data...")
    print(f"   Base time: {base_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"   Output: {os.path.abspath(output_dir)}\n")

    print("[*] Generating HTTP access logs...")
    access_logs = generate_access_logs(base_time, hours=args.hours, interval_seconds=2)
    write_csv(access_logs, f"{output_dir}/access_logs.csv")

    print("[*] Generating deployment events...")
    deployments = generate_deployment_events(base_time)
    write_csv(deployments, f"{output_dir}/deployment_events.csv")

    print("[*] Generating infrastructure metrics...")
    metrics = generate_infrastructure_metrics(base_time, hours=args.hours)
    write_csv(metrics, f"{output_dir}/infrastructure_metrics.csv")

    print(f"\n[OK] Done! Load these files into Splunk via:")
    print(f"   Settings > Data Inputs > Files & Directories")
    print(f"   Or drag-and-drop into Search & Reporting > Add Data\n")

    # Summarize the anomalies we embedded
    anomalies = get_anomaly_config(base_time)
    deploy_ago = (base_time - anomalies["payment_deploy_time"]).seconds // 60
    redis_ago = (base_time - anomalies["inventory_redis_start"]).seconds // 60

    print("Embedded scenarios for demo:")
    print(f"   * payment-svc v2.4.1 deployment regression ({deploy_ago} min ago)")
    print(f"     -> p99 latency: 240ms -> 2,840ms | error rate: 0.3% -> 12%")
    print(f"   * inventory-api Redis pool exhaustion ({redis_ago} min ago)")
    print(f"     -> /api/stock/check error rate: 12.7% | 3,240 users affected")
    print(f"\n   Try asking DevLens: 'Why are my APIs returning 500s?'")
    print(f"   Or: 'Did my last deploy cause a regression?'\n")


if __name__ == "__main__":
    main()
