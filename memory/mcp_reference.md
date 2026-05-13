# MCP Capability Reference

Capability reference for external services available to Arke.
Consult this file only when local information is insufficient or when fresh external data is required.

## Access Rule

- This file is documentation, not a mandatory execution plan.
- Prefer the most relevant and reliable source for the task.
- Local resources often win on cost, determinism, and speed.
- External MCP tools are useful when the task requires fresh or remote data.

## Servers

### web_search
- Use for web discovery when local data is insufficient.
- Tools:
  - web_search(query, max_results)
  - fetch_page(url, max_length)

### calculator
- Use for deterministic math and conversions.
- Tools:
  - calculate(expression)
  - convert_units(value, from_unit, to_unit)
  - random_number(min, max, integer)
  - statistics(numbers, operation)

### rss_reader
- Use for RSS and Atom feeds.
- Tools:
  - read_rss(url, limit)
  - discover_rss(url)
  - fetch_full_content(url)

### github
- Use for GitHub repository and user information.
- Tools:
  - github_repo(owner, repo)
  - github_search(query, max_results, sort)
  - github_readme(owner, repo, branch)
  - github_user(username)

### freeweb
- Use as a fallback external search source.
- Tools:
  - web_search(query, max_results)

## Invocation Notes

- Preferred format:
  - [OUTIL: mcp]
  - [ARGS: {"_server": "SERVER_NAME", "tool_name": "TOOL_NAME", "tool_args": {...}}]
- Use MCP only when it materially improves the chance of success.
- Do not expose raw tool calls to the user in normal mode.
