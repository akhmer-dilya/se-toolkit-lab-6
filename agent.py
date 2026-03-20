#!/usr/bin/env python3
"""Agent CLI — answers questions using an LLM with tools.

Usage:
    uv run agent.py "How do you resolve a merge conflict?"

Output (JSON to stdout):
    {
      "answer": "...",
      "source": "wiki/git-workflow.md#resolving-merge-conflicts",
      "tool_calls": [...]
    }

All debug output goes to stderr.
"""

import json
import os
import re
import sys
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Load environment variables from .env.agent.secret
env_file = Path(__file__).parent / ".env.agent.secret"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

# Also load LMS_API_KEY from .env.docker.secret
docker_env_file = Path(__file__).parent / ".env.docker.secret"
if docker_env_file.exists():
    for line in docker_env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

LLM_API_KEY = os.environ.get("LLM_API_KEY")
LLM_API_BASE = os.environ.get("LLM_API_BASE")
LLM_MODEL = os.environ.get("LLM_MODEL")
LMS_API_KEY = os.environ.get("LMS_API_KEY")

# Backend API base URL (can be overridden by environment)
AGENT_API_BASE_URL = os.environ.get("AGENT_API_BASE_URL", "http://localhost:42002")

# Project root directory
PROJECT_ROOT = Path(__file__).parent.resolve()

# Maximum tool calls per question
MAX_TOOL_CALLS = 10

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def read_file(path: str) -> str:
    """Read a file from the project repository.

    Args:
        path: Relative path from project root.

    Returns:
        File contents as string, or error message.
    """
    # Security: validate path
    if ".." in path:
        return "Error: Path traversal not allowed"

    if path.startswith("/"):
        return "Error: Absolute paths not allowed"

    # Resolve to absolute path
    try:
        full_path = (PROJECT_ROOT / path).resolve()
    except Exception as e:
        return f"Error: Invalid path: {e}"

    # Security: ensure path is within project root
    try:
        full_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return "Error: Path outside project directory"

    # Read file
    try:
        content = full_path.read_text(encoding="utf-8")
        return content
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as e:
        return f"Error: {e}"


def list_files(path: str) -> str:
    """List files and directories at a given path.

    Args:
        path: Relative directory path from project root.

    Returns:
        Newline-separated list of entries, or error message.
    """
    # Security: validate path
    if ".." in path:
        return "Error: Path traversal not allowed"

    if path.startswith("/"):
        return "Error: Absolute paths not allowed"

    # Resolve to absolute path
    try:
        full_path = (PROJECT_ROOT / path).resolve()
    except Exception as e:
        return f"Error: Invalid path: {e}"

    # Security: ensure path is within project root
    try:
        full_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return "Error: Path outside project directory"

    # Check if directory exists
    if not full_path.exists():
        return f"Error: Directory not found: {path}"

    if not full_path.is_dir():
        return f"Error: Not a directory: {path}"

    # List entries
    try:
        entries = [e.name for e in full_path.iterdir()]
        return "\n".join(sorted(entries))
    except Exception as e:
        return f"Error: {e}"


def query_api(method: str, path: str, body: str = None) -> str:
    """Make an HTTP request to the backend LMS API.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API path (e.g., '/items/')
        body: Optional JSON request body for POST/PUT

    Returns:
        JSON string with status_code and body, or error message.
    """
    # Validate method
    allowed_methods = ["GET", "POST", "PUT", "DELETE"]
    method = method.upper()
    if method not in allowed_methods:
        return f"Error: Method must be one of {allowed_methods}"

    # Validate path
    if not path.startswith("/"):
        return "Error: Path must start with /"
    if ".." in path:
        return "Error: Path traversal not allowed"

    # Build URL
    url = f"{AGENT_API_BASE_URL}{path}"

    # Prepare headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LMS_API_KEY}",
    }

    print(f"Querying API: {method} {url}", file=sys.stderr)

    try:
        # Make request
        if method in ["GET", "DELETE"]:
            response = httpx.get(url, headers=headers, timeout=30.0)
        elif method == "POST":
            request_body = json.loads(body) if body else {}
            response = httpx.post(url, headers=headers, json=request_body, timeout=30.0)
        elif method == "PUT":
            request_body = json.loads(body) if body else {}
            response = httpx.put(url, headers=headers, json=request_body, timeout=30.0)

        # Parse response
        result = {
            "status_code": response.status_code,
            "body": response.json() if response.text else None,
        }
        return json.dumps(result)

    except httpx.TimeoutException:
        return "Error: Request timed out after 30 seconds"
    except httpx.HTTPError as e:
        return f"Error: HTTP request failed: {e}"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in body: {e}"
    except Exception as e:
        return f"Error: {e}"


# Tool functions mapping
TOOL_FUNCTIONS = {
    "read_file": read_file,
    "list_files": list_files,
    "query_api": query_api,
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a documentation and system assistant for a software engineering toolkit project.

You have access to three tools. To use them, include this format in your response:

TOOL_CALL: tool_name({"arg": "value"})

Available tools:
1. list_files({"path": "directory"}) - List files in a directory
2. read_file({"path": "file"}) - Read contents of a file
3. query_api({"method": "GET", "path": "/endpoint", "body": "..."}) - Make HTTP requests to the backend API

When to use each tool:
- Use list_files to discover what files exist in a directory
- Use read_file to read documentation, source code, or configuration files
- Use query_api to query live system data (database contents, analytics, API responses)

For example:
- "What files are in the wiki?" → list_files({"path": "wiki"})
- "How do you resolve a merge conflict?" → read_file({"path": "wiki/git-workflow.md"})
- "How many items are in the database?" → query_api({"method": "GET", "path": "/items/"})
- "What is the average score?" → query_api({"method": "GET", "path": "/analytics/scores?lab=lab-01"})

When providing answers:
- Be concise and accurate
- Include the source field with file path when referencing documentation
- For API queries, include the endpoint path as source
- If you cannot find the answer, say so honestly

Important: Only access files within the project directory. Do not attempt to read files outside the project.

After receiving tool results, continue reasoning and either call more tools or provide the final answer."""


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


def execute_tool(tool_name: str, args: dict) -> str:
    """Execute a tool and return the result."""
    print(f"Executing tool: {tool_name}({args})", file=sys.stderr)

    if tool_name not in TOOL_FUNCTIONS:
        return f"Error: Unknown tool: {tool_name}"

    try:
        func = TOOL_FUNCTIONS[tool_name]
        result = func(**args)
        if len(result) > 500:
            print(f"Tool result: {result[:500]}... (truncated)", file=sys.stderr)
        else:
            print(f"Tool result: {result}", file=sys.stderr)
        return result
    except Exception as e:
        return f"Error executing {tool_name}: {e}"


def parse_tool_calls(text: str) -> list:
    """Parse tool calls from LLM response text."""
    tool_calls = []
    # Match TOOL_CALL: tool_name({...})
    pattern = r'TOOL_CALL:\s*(\w+)\((\{[^}]+\})\)'
    matches = re.findall(pattern, text)
    for tool_name, args_str in matches:
        try:
            args = json.loads(args_str)
            tool_calls.append({"tool": tool_name, "args": args})
        except json.JSONDecodeError:
            print(f"Failed to parse args: {args_str}", file=sys.stderr)
    return tool_calls


def run_agent(question: str) -> dict:
    """Run the agentic loop and return the result."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    tool_calls_log = []
    url = f"{LLM_API_BASE}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }

    for iteration in range(MAX_TOOL_CALLS):
        print(f"\n--- Iteration {iteration + 1} ---", file=sys.stderr)

        # Build request
        payload = {
            "model": LLM_MODEL,
            "messages": messages,
        }

        # Send request
        print(f"POST {url}", file=sys.stderr)
        response = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        response.raise_for_status()

        # Parse response
        data = response.json()
        choice = data["choices"][0]
        message = choice["message"]
        content = message.get("content", "")

        print(f"LLM response: {content[:300]}...", file=sys.stderr)

        # Parse tool calls from text
        tool_calls = parse_tool_calls(content)

        if tool_calls:
            # Execute tools
            for tc in tool_calls:
                tool_name = tc["tool"]
                args = tc["args"]

                result = execute_tool(tool_name, args)

                # Log tool call
                tool_calls_log.append({
                    "tool": tool_name,
                    "args": args,
                    "result": result,
                })

                # Append tool result to messages
                messages.append({
                    "role": "user",
                    "content": f"TOOL_RESULT: {tool_name}({args}) = {result}",
                })

            # Continue loop
            continue
        else:
            # No tool calls - final answer
            answer = content
            print(f"Final answer: {answer[:300]}...", file=sys.stderr)

            # Extract source from answer
            source = ""
            wiki_refs = re.findall(r'wiki/[\w\-/]+\.md(?:#[\w\-]+)?', answer)
            if wiki_refs:
                source = wiki_refs[0]
            else:
                file_refs = re.findall(r'[\w\-/]+\.md(?:#[\w\-]+)?', answer)
                if file_refs:
                    source = file_refs[0]

            return {
                "answer": answer,
                "source": source,
                "tool_calls": tool_calls_log,
            }

    # Max iterations reached
    print("Max tool calls reached, returning partial answer", file=sys.stderr)
    return {
        "answer": "Reached maximum tool calls limit.",
        "source": "",
        "tool_calls": tool_calls_log,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # Validate arguments
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py <question>", file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    # Validate environment
    if not LLM_API_KEY:
        print("Error: LLM_API_KEY not set in .env.agent.secret", file=sys.stderr)
        sys.exit(1)
    if not LLM_API_BASE:
        print("Error: LLM_API_BASE not set in .env.agent.secret", file=sys.stderr)
        sys.exit(1)
    if not LLM_MODEL:
        print("Error: LLM_MODEL not set in .env.agent.secret", file=sys.stderr)
        sys.exit(1)

    print(f"Question: {question}", file=sys.stderr)

    try:
        # Run agent
        result = run_agent(question)

        # Output JSON
        print(json.dumps(result))

        print("Done", file=sys.stderr)
        sys.exit(0)

    except httpx.TimeoutException as e:
        print(f"Error: Request timed out: {e}", file=sys.stderr)
        result = {"answer": "Request timed out.", "source": "", "tool_calls": []}
        print(json.dumps(result))
        sys.exit(1)
    except httpx.HTTPError as e:
        print(f"Error: HTTP request failed: {e}", file=sys.stderr)
        result = {"answer": f"API error: {e}", "source": "", "tool_calls": []}
        print(json.dumps(result))
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        result = {"answer": f"Error: {e}", "source": "", "tool_calls": []}
        print(json.dumps(result))
        sys.exit(1)


if __name__ == "__main__":
    main()
