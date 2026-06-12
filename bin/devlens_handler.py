#!/usr/bin/env python3
"""
DevLens — REST API Handler (Splunk Custom REST Handler)

Exposes the DevLens agent as a Splunk REST endpoint:
  POST /services/devlens/investigate

The Splunk dashboard calls this endpoint via JavaScript fetch() to trigger
the agentic investigation and get a JSON response back.

Register in restmap.conf:
  [admin_external:devlens_investigate]
  handlertype=python
  handlerfile=devlens_handler.py
  handleractions=edit

Reference: https://dev.splunk.com/enterprise/docs/developapps/customizedsplunk/customresthandlers/
"""

import sys
import os
import json
import logging

sys.path.insert(0, os.path.dirname(__file__))

import splunk.rest as rest
import splunk.admin as admin
from agent import DevLensAgent

logger = logging.getLogger("devlens.handler")


class DevLensInvestigateHandler(admin.MConfigHandler):
    """
    Custom REST handler that wraps the DevLens agentic investigation.

    POST /services/devlens/investigate
    Body params:
      - question: str (required) - developer's natural language question
      - timerange: str (optional, default: "-1h")
      - index: str (optional, default: "*")
    """

    def setup(self):
        if self.requestedAction == admin.ACTION_EDIT:
            for arg in ["question", "timerange", "index"]:
                self.supportedArgs.addOptArg(arg)

    def handleEdit(self, confInfo):
        """Handle POST requests — run the investigation."""
        question = self.callerArgs.data.get("question", [""])[0].strip()
        timerange = self.callerArgs.data.get("timerange", ["-1h"])[0]
        index = self.callerArgs.data.get("index", ["*"])[0]

        if not question:
            self.handleError(400, "question parameter is required")
            return

        try:
            # Get Splunk connection details from the current session
            session_key = self.getSessionKey()
            splunk_host = "localhost"
            splunk_port = 8089

            agent = DevLensAgent(
                splunk_host=splunk_host,
                splunk_port=splunk_port,
                splunk_token=session_key,
            )

            result = agent.investigate(
                question=question,
                timerange=timerange,
                index=index,
            )

            confInfo["result"]["status"] = "ok"
            confInfo["result"]["data"] = json.dumps(result)
            logger.info(f"Investigation complete for: '{question[:60]}'")

        except Exception as e:
            logger.exception(f"Investigation failed: {e}")
            confInfo["result"]["status"] = "error"
            confInfo["result"]["data"] = json.dumps({
                "error": str(e),
                "question": question,
                "status": "error",
            })


if __name__ == "__main__":
    admin.init(DevLensInvestigateHandler, admin.CONTEXT_NONE)
