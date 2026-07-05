# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re
import json
import logging
from typing import Any

from google.adk import Agent, Workflow
from google.adk.apps import App
from google.adk.tools import AgentTool, McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.workflow import START, node
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.genai import types
from mcp import StdioServerParameters

from app.config import config

logger = logging.getLogger(__name__)

# Initialize model
model_wrapper = Gemini(
    model=config.model,
    retry_options=types.HttpRetryOptions(attempts=3),
)

# Define custom MCP Toolset running as a background python process
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="python",
            args=["-m", "app.mcp_server"],
        )
    )
)

# Specialized sub-agents
recipe_planner = Agent(
    name="recipe_planner",
    model=model_wrapper,
    instruction="""You are a professional chef and recipe developer.
Your goal is to suggest delicious, customized recipes based on the user's requested ingredients and dietary restrictions.
Use the MCP tools at your disposal to search the recipe database and check allergy restrictions.
Provide a clear title, ingredient lists, prep time, cook time, and step-by-step cooking instructions.
Verify that none of the suggested ingredients violate the dietary restrictions.
""",
    tools=[mcp_toolset],
)

shopping_list_builder = Agent(
    name="shopping_list_builder",
    model=model_wrapper,
    instruction="""You are an expert grocery shopper and pantry organizer.
Your goal is to take a set of recipes and generate a consolidated, organized shopping list.
Group the ingredients by grocery store sections (e.g., Produce, Pantry, Meat, Dairy).
Combine identical ingredients (e.g., if two recipes need garlic, consolidate them).
""",
)

# Orchestrator agent coordinating sub-agents via AgentTool
recipe_orchestrator = Agent(
    name="recipe_orchestrator",
    model=model_wrapper,
    instruction="""You are the Recipe Concierge Orchestrator.
Your goal is to design a customized recipe and a consolidated shopping list for the user.
You coordinate two specialized sub-agents:
1. recipe_planner: Use this tool to generate the customized recipes.
2. shopping_list_builder: Use this tool to compile the structured shopping list for the generated recipes.

You also have direct access to the MCP tools (get_fridge_inventory, search_recipe_database, check_allergy_restrictions).
Always perform your planning in two steps:
1. Call `recipe_planner` with the user ingredients and dietary preferences to design the recipes.
2. Call `shopping_list_builder` with the recipe output to build the structured shopping list.
3. Present both the recipes and the shopping list in a beautifully formatted final response.
""",
    tools=[
        AgentTool(agent=recipe_planner, skip_summarization=False),
        AgentTool(agent=shopping_list_builder, skip_summarization=False),
        mcp_toolset,
    ],
)

@node
async def security_checkpoint(ctx: Any, node_input: Any = None) -> Any:
    """Checks for prompt injection, scrubs PII, logs structured JSON audit data, and applies food safety checks."""
    query_text = ""
    if isinstance(node_input, types.Content):
        query_text = "".join(part.text for part in node_input.parts if part.text)
    elif isinstance(node_input, str):
        query_text = node_input
    else:
        query_text = str(node_input)

    # Save original query to state if not set
    if "user_query" not in ctx.state:
        ctx.state["user_query"] = query_text

    lower_query = query_text.lower()

    # 1. Prompt injection check
    injection_keywords = ["ignore previous", "system prompt", "bypass safety", "override instruction"]
    is_injection = any(kw in lower_query for kw in injection_keywords)

    if is_injection:
        audit_log = {
            "event": "security_checkpoint_evaluation",
            "decision": "blocked",
            "reason": "prompt_injection_detected",
            "severity": "CRITICAL",
            "query_length": len(query_text)
        }
        logger.warning(json.dumps(audit_log))
        ctx.state["security_log"] = "Injection detected"
        ctx.route = "blocked"
        return "Access Blocked: Prompt injection keywords detected."

    # 2. Domain-specific rule: toxic non-food chemical check
    chemical_keywords = ["bleach", "detergent", "poison", "arsenic", "gasoline", "cyanide"]
    has_chemical = any(chem in lower_query for chem in chemical_keywords)
    if has_chemical:
        audit_log = {
            "event": "security_checkpoint_evaluation",
            "decision": "blocked",
            "reason": "non_food_hazardous_substance",
            "severity": "CRITICAL",
            "query_length": len(query_text)
        }
        logger.warning(json.dumps(audit_log))
        ctx.state["security_log"] = "Toxic substance detected"
        ctx.route = "blocked"
        return "Access Blocked: Hazardous non-food substances detected."

    # 3. PII scrubbing
    scrubbed_query = query_text
    email_scrubbed = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[EMAIL_REDACTED]', scrubbed_query)
    pii_detected = email_scrubbed != scrubbed_query
    scrubbed_query = email_scrubbed
    
    phone_scrubbed = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE_REDACTED]', scrubbed_query)
    pii_detected = pii_detected or (phone_scrubbed != scrubbed_query)
    scrubbed_query = phone_scrubbed

    # 4. Success log
    audit_log = {
        "event": "security_checkpoint_evaluation",
        "decision": "passed",
        "severity": "INFO",
        "pii_redacted": pii_detected,
        "query_length": len(query_text)
    }
    logger.info(json.dumps(audit_log))

    ctx.state["clean_query"] = scrubbed_query
    ctx.route = "passed"
    return scrubbed_query

# Workflow node: Security Blocked
@node
async def security_blocked(ctx: Any, node_input: Any = None) -> Any:
    """Terminal node for security violations."""
    return f"Request blocked due to security validation failure: {node_input}"

# Workflow node: Orchestration wrapper
@node(rerun_on_resume=True)
async def run_orchestrator(ctx: Any, node_input: Any = None) -> Any:
    """Dispatches requests to the recipe orchestrator agent, incorporating any user feedback."""
    query = ctx.state.get("clean_query", "")
    feedback = ctx.state.get("human_feedback", "")

    prompt = query
    if feedback:
        prompt = f"User feedback/revision request: {feedback}\nOriginal user request: {query}"
        # Clear feedback from state so we don't apply it again repeatedly
        ctx.state["human_feedback"] = ""

    result = await ctx.run_node(recipe_orchestrator, prompt)
    return result

# Workflow node: Human Review (HITL)
@node(rerun_on_resume=True)
async def human_review(ctx: Any, node_input: Any = None) -> Any:
    """Interrupts to ask the user for approval. Routes to approved or loops back for revisions."""
    if not ctx.state.get("review_requested", False):
        # Store the plan to be reviewed and set flag
        ctx.state["proposed_plan"] = node_input
        ctx.state["review_requested"] = True
        msg = f"Please review the proposed plan:\n\n{node_input}\n\nDo you approve? (Yes / or type modifications)"
        return RequestInput(message=msg)

    # Resume turn: node_input contains the user's feedback/reply
    ctx.state["review_requested"] = False

    user_response = ""
    if isinstance(node_input, types.Content):
        user_response = "".join(part.text for part in node_input.parts if part.text)
    elif isinstance(node_input, str):
        user_response = node_input

    user_response = user_response.strip()
    if user_response.lower() in ["yes", "approve", "y", "approved", "looks good"]:
        ctx.route = "approved"
        return "Plan approved!"
    else:
        ctx.state["human_feedback"] = user_response
        ctx.route = "revision"
        return f"Revision requested: {user_response}"

# Workflow node: Final Output
@node
async def final_output(ctx: Any, node_input: Any = None) -> Any:
    """Terminal node confirming the recipe plan."""
    plan = ctx.state.get("proposed_plan", "")
    return f"Confirmed! Your dinner plan is finalized:\n\n{plan}"

# Define the workflow graph
recipe_workflow = Workflow(
    name="recipe_workflow",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {"passed": run_orchestrator, "blocked": security_blocked}),
        (run_orchestrator, human_review),
        (human_review, {"approved": final_output, "revision": run_orchestrator}),
    ]
)

# Export app and root_agent for the runner
root_agent = recipe_workflow

app = App(
    root_agent=root_agent,
    name="app",
)
