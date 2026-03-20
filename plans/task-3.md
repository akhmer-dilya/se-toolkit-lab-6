# Task 3: The System Agent — Implementation Plan

## Overview

Extend the agent from Task 2 with a new tool `query_api` that can make HTTP requests to the deployed backend API. This allows the agent to answer questions about the live system state (database contents, API responses) in addition to static documentation.

## New Tool: `query_api`

**Purpose:** Make HTTP requests to the backend LMS API.

**Parameters:**
- `method` (string, required): HTTP method (GET, POST, PUT, DELETE)
- `path` (string, required): API path (e.g., `/items/`, `/analytics/scores?lab=lab-01`)
- `body` (string, optional): JSON request body for POST/PUT requests

**Returns:** JSON string with structure:
```json
{
  "status_code": 200,
  "body": {...}
}
```

**Authentication:**
- Use `LMS_API_KEY` from environment (read from `.env.docker.secret`)
- Send as `Authorization: Bearer <LMS_API_KEY>` header

**Security:**
- Only allow HTTP methods: GET, POST, PUT, DELETE
- Validate path starts with `/`
- Block paths with `..` (path traversal)
- Timeout: 30 seconds per request

**Schema:**
```json
{
  "name": "query_api",
  "description": "Make HTTP requests to the backend LMS API. Use this to query live data.",
  "parameters": {
    "type": "object",
    "properties": {
      "method": {"type": "string", "description": "HTTP method (GET, POST, PUT, DELETE)"},
      "path": {"type": "string", "description": "API path (e.g., '/items/')"},
      "body": {"type": "string", "description": "JSON request body (optional)"}
    },
    "required": ["method", "path"]
  }
}
```

## Environment Variables

The agent reads configuration from environment variables:

| Variable | Purpose | Source |
|----------|---------|--------|
| `LLM_API_KEY` | LLM provider API key | `.env.agent.secret` |
| `LLM_API_BASE` | LLM API endpoint URL | `.env.agent.secret` |
| `LLM_MODEL` | Model name | `.env.agent.secret` |
| `LMS_API_KEY` | Backend API key for query_api | `.env.docker.secret` |
| `AGENT_API_BASE_URL` | Backend API base URL (optional) | Environment, defaults to `http://localhost:42002` |

**Important:** The autochecker injects its own values at runtime. Never hardcode these values.

## System Prompt Update

Update the system prompt to explain when to use each tool:

1. **`list_files`** — Discover what files exist in a directory
2. **`read_file`** — Read documentation or source code files
3. **`query_api`** — Query live system data (database, analytics)

Example guidance:
- "For questions about API endpoints, ports, frameworks → use `read_file` on docs or source"
- "For questions about current data (how many items, scores) → use `query_api`"
- "For questions about processes, workflows → use `read_file` on wiki"

## Agentic Loop

No changes to the loop structure — just add `query_api` to the available tools:

```
1. Send question + system prompt + all tool schemas to LLM
2. Parse tool calls from response
3. If tool calls found:
   - Execute each tool (read_file, list_files, or query_api)
   - Append results to messages
   - Continue loop
4. If no tool calls: return final answer
5. Max 10 iterations
```

## Output Format

Same as Task 2, but `source` is now optional (system questions may not have wiki source):

```json
{
  "answer": "There are 120 items in the database.",
  "source": "",  // Optional for system questions
  "tool_calls": [
    {"tool": "query_api", "args": {"method": "GET", "path": "/items/"}, "result": "..."}
  ]
}
```

## Files to Update

- `plans/task-3.md` — this plan
- `agent.py` — add `query_api` tool and update system prompt
- `.env.docker.secret` — ensure `LMS_API_KEY` is set
- `AGENT.md` — document the new tool
- `tests/test_agent.py` — add tests for `query_api`

## Testing Strategy

1. **Unit test `query_api` tool:**
   - Test GET request to `/items/`
   - Test authentication header
   - Test error handling (invalid path, timeout)

2. **Integration test:**
   - Ask "How many items are in the database?"
   - Verify `query_api` in tool_calls
   - Verify answer contains the count

3. **Security test:**
   - Test path traversal is blocked
   - Test invalid methods are rejected

## Benchmark Evaluation

Run the provided benchmark to evaluate:

```bash
uv run run_eval.py
```

Iterate on system prompt and tool descriptions until benchmark passes.
