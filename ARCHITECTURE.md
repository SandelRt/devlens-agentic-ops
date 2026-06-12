# DevLens Architecture

DevLens is built as a native Splunk Enterprise app, leveraging the Python SDK, Splunk REST API, and Splunk's AI capabilities. It does not require any external hosting or infrastructure beyond the Splunk instance itself.

## High-Level Data Flow

1. **User Input:** A developer asks a natural language question in the DevLens Splunk Dashboard.
2. **REST API:** The UI sends an async request to the custom Splunk REST endpoint (`/services/devlens/investigate`).
3. **Agent Loop:** The `DevLensAgent` (Python) starts its Reason-Act-Observe loop:
    * **Plan:** Asks the Cisco Foundation AI (via Splunk Hosted Models) what SPL to run next based on context.
    * **Translate:** The `SPLGenerator` translates the planned intent into valid SPL, using curated templates or the LLM.
    * **Execute:** The SPL is executed against Splunk indexes via the REST API (`exec_mode=oneshot`).
    * **Observe:** The LLM analyzes the search results to extract key facts and determine confidence.
4. **Synthesis:** Once confidence is high enough (or max iterations reached), the `RootCauseAnalyzer` synthesizes the findings into a developer-friendly report.
5. **UI Rendering:** The report (with evidence, recommendations, and the queries run) is returned to the UI and rendered.

## Component Map

### Frontend (Splunk Simple XML & JS)
* **`default/data/ui/views/devlens.xml`**: The main dashboard. Embeds the chat interface and provides secondary contextual panels (Error Rates, Latency, Deployments).
* **`appserver/static/js/devlens_chat.js`**: Handles the chat UI state, simulates the agentic "thinking" steps visually, and fetches the REST API.
* **`appserver/static/css/devlens.css`**: Provides a dark, developer-native aesthetic that overrides standard Splunk styles.

### Backend (Python)
* **`bin/devlens_handler.py`**: The Splunk custom REST handler. Acts as the bridge between the JS UI and the Python agent.
* **`bin/agent.py`**: The core loop (`investigate()`). Manages context, history, and iteration limits.
* **`bin/hosted_models.py`**: A wrapper client around Splunk's `/services/ml/hosted-models/*/predict` endpoints. Handles LLM communication and provides rule-based fallbacks if the API is unreachable.
* **`bin/spl_generator.py`**: Converts intent to SPL. Contains a curated library of high-performance observability queries.
* **`bin/rca.py`**: The root cause synthesizer. Aggregates iterations into a final report.

### Splunk Knowledge Objects
* **`default/tools.conf`**: Registers 5 MCP Server tools, making DevLens capabilities accessible to external AI agents.
* **`default/tool_input_payload_signatures.json`**: Provides JSON schemas for the MCP tools.
* **`default/savedsearches.conf`**: 9 pre-built queries for monitoring general application health, which the agent can also leverage.
* **`default/macros.conf`**: Reusable SPL snippets to keep queries DRY.

## Security & Auth
* DevLens runs under the permissions of the authenticated user. The Splunk session token is passed from the UI to the REST handler, and then to the Python agent, ensuring the agent can only query data the user is authorized to see.

## External Integrations
* **Splunk MCP Server**: By providing a `tools.conf`, DevLens automatically exposes its functions to any MCP-compliant client (like Anthropic Claude or external developer tools) installed alongside it.
