# DevLens — Agentic Observability for Developers

> Ask questions about your application in plain English. DevLens investigates your Splunk data autonomously and returns a root cause analysis.

[![Splunk App](https://img.shields.io/badge/Splunk-App-65A637?logo=splunk)](https://splunkbase.splunk.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Hackathon: Splunk Agentic Ops 2026](https://img.shields.io/badge/Hackathon-Splunk%20Agentic%20Ops%202026-orange)](https://splunk.devpost.com/)

**Track:** Observability + Platform & Developer Experience  
**Splunk Technologies Used:**
- 🤖 [Splunk Hosted Models](https://docs.splunk.com/Documentation/SplunkCloud/latest/Admin/HostedModels) (Cisco Foundation AI)
- 🔌 [Splunk MCP Server](https://splunkbase.splunk.com/) — 5 registered MCP tools
- 🐍 [Splunk SDK for Python](https://dev.splunk.com/enterprise/docs/devtools/python/sdk-python/) (`splunklib`)
- 📊 Splunk REST API for agentic search execution

---

## 🎯 What It Does

Developers often don't know SPL (Splunk Query Language), and SREs are a bottleneck. DevLens removes that friction with an **agentic investigation loop** that:

1. **Understands** your plain-English question
2. **Plans** a multi-step investigation using AI
3. **Generates and runs** targeted SPL queries against your Splunk instance
4. **Analyzes** results using **Splunk Hosted Models** (Cisco Foundation AI)
5. **Loops** if it needs more information (up to 5 iterations)
6. **Returns** a root cause analysis with evidence, recommendations, and a monitoring query

**Example questions:**
```
"Why are my APIs returning 500s?"
"Did my last deployment cause a latency regression?"
"Which service is affecting the most users right now?"
"What's causing the slow checkout experience?"
"Show me resource saturation on production hosts"
```

---

## 🏗 Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full architecture diagram.

```
Developer Question (natural language)
         │
         ▼
DevLens Chat UI (Splunk Dashboard)
         │  HTTP REST
         ▼
DevLens Agent (Python / splunklib)
  ┌──────────────────────────────┐
  │  Plan → SPL → Execute →      │
  │  Observe → Iterate → Report  │
  └──────────────────────────────┘
         │                │
    Splunk MCP        Splunk Hosted
    Server tools      Models API
    (tools.conf)      (Cisco Foundation AI)
         │
    Splunk REST API
    (search jobs)
         │
    Your Splunk Data
```

---

## 🚀 Quick Start

### Prerequisites

- Splunk Enterprise 9.x+ (or Splunk Cloud)
- Developer License (get one at [dev.splunk.com](https://dev.splunk.com/))
- Splunk MCP Server installed from [Splunkbase](https://splunkbase.splunk.com/)
- Python 3.9+

### 1. Install the App

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/devlens-splunk
cd devlens-splunk

# Package the Splunk app
tar -czf devlens.tar.gz devlens/

# Install via Splunk Web:
# Apps > Install app from file > upload devlens.tar.gz
# Or copy the devlens/ folder to $SPLUNK_HOME/etc/apps/
```

### 2. Generate Demo Data

```bash
# Install dependencies
pip install -r requirements.txt

# Generate synthetic observability data
python devlens/generate_demo_data.py --output-dir ./demo_data --hours 6

# Load into Splunk:
# Settings > Data Inputs > Files & Directories > Add New
# Point to the generated CSV files in ./demo_data/
```

### 3. Configure Hosted Models

1. In Splunk Web: **Settings > AI Services > Hosted Models**
2. Enable the **Cisco Foundation AI** model
3. Accept the license terms

Or, for Splunk Cloud, Hosted Models are enabled by default.

### 4. Configure MCP Server

1. Install the [Splunk MCP Server](https://splunkbase.splunk.com/) app
2. DevLens tools are automatically registered via `default/tools.conf`
3. Connect your AI assistant (Claude, GPT, etc.) to the Splunk MCP endpoint

### 5. Open DevLens

1. Navigate to **Apps > DevLens AI** in Splunk Web
2. The chat dashboard will open
3. Try: *"Why are my APIs returning 500s?"*

---

## 📁 Project Structure

```
devlens/
├── app.conf                              # Splunk app metadata
├── generate_demo_data.py                 # Demo data generator
├── requirements.txt                      # Python dependencies
│
├── bin/
│   ├── agent.py                          # 🧠 Core AI agent (agentic loop)
│   ├── spl_generator.py                  # NL → SPL translation
│   ├── rca.py                            # Root cause analysis synthesizer
│   ├── hosted_models.py                  # Splunk Hosted Models REST client
│   └── devlens_handler.py                # Splunk Custom REST handler
│
├── default/
│   ├── tools.conf                        # 🔌 MCP Server tool definitions (5 tools)
│   ├── tool_input_payload_signatures.json # MCP tool input schemas
│   ├── savedsearches.conf                # Pre-built observability searches
│   ├── macros.conf                       # Reusable SPL macros
│   └── data/ui/
│       ├── nav/default.xml               # App navigation
│       └── views/devlens.xml             # Main Splunk dashboard
│
├── appserver/static/
│   ├── js/devlens_chat.js                # Chat UI frontend
│   └── css/devlens.css                   # Dark terminal design system
│
├── ARCHITECTURE.md                       # Architecture documentation
└── architecture.png                      # Architecture diagram
```

---

## 🔌 MCP Tools

DevLens registers **5 MCP tools** via `tools.conf`, making your Splunk observability data accessible to any MCP-compatible AI assistant:

| Tool | Description |
|------|-------------|
| `devlens_investigate` | Full agentic investigation from natural language |
| `devlens_spl_query` | Generate SPL from natural language description |
| `devlens_health_check` | Get service health summary across all indexes |
| `devlens_deployment_impact` | Analyze before/after metrics for a deployment |
| `devlens_anomaly_detect` | Run Cisco Deep Time Series anomaly detection |

---

## 🤖 Splunk Hosted Models Integration

DevLens uses two Splunk Hosted Models:

| Model | Used For |
|-------|----------|
| **Cisco Foundation AI** | Investigation planning, SPL generation, RCA synthesis |
| **Cisco Deep Time Series** (beta) | Metric anomaly detection with `devlens_anomaly_detect` |

Both models are accessed via the Splunk REST API at `/services/ml/hosted-models/<model>/predict`. DevLens falls back to rule-based analysis if the API is unavailable, ensuring demo reliability.

---

## 📊 Pre-built Saved Searches

DevLens ships with 9 production-ready observability searches:

- **HTTP Error Rate by Service** (scheduled, every 5 min)
- **Top Failing Endpoints**
- **Error Spike Detection** (3-sigma statistical threshold)
- **Latency Percentiles by Service**
- **Latency Regression Detection**
- **Recent Deployment Events**
- **Deployment Impact Analysis**
- **Service Health Dashboard**
- **Resource Saturation Alert** (scheduled, every 5 min)

---

## 🧪 Running the Agent Standalone

```python
from devlens.bin.agent import DevLensAgent

agent = DevLensAgent(
    splunk_host="localhost",
    splunk_port=8089,
    splunk_token="your-splunk-token",
)

result = agent.investigate(
    question="Why are my APIs returning 500s?",
    timerange="-1h",
    index="main",
)

print(result["answer"])
print(f"Confidence: {result['confidence']:.0%}")
for rec in result["recommendations"]:
    print(f"  → {rec}")
```

---

## 🎥 Demo Video

[▶ Watch on YouTube](https://youtube.com/LINK_HERE) — 3 minutes

The demo shows:
1. Starting with a vague developer complaint ("something is slow")
2. DevLens running 2 agentic iterations, generating and executing SPL queries
3. The agent correlating the slowdown with a deployment event
4. A full root cause analysis with concrete recommendations

---

## 🏆 Hackathon Submission

**Event:** [Splunk Agentic Ops Hackathon 2026](https://splunk.devpost.com/)  
**Tracks:** Observability | Platform & Developer Experience  
**Prizes Targeting:** Grand Prize + Best of Observability + Best Use of Splunk MCP Server + Best Use of Splunk Hosted Models

---

## 📄 License

MIT © 2026 DevLens Team. See [LICENSE](LICENSE).
