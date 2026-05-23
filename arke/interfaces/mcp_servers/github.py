#!/usr/bin/env python3
"""
MCP Server : GitHub API
Recherche, dépôts, README - Sans clé (rate limit 60/h)
"""

import json
import sys
import asyncio
import os
from typing import List, Dict
from urllib.parse import quote_plus, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import httpx
except Exception:  # noqa: BLE001
    httpx = None


class GitHubMCP:
    """Serveur MCP pour GitHub API"""
    
    def __init__(self, token: str = None):
        self.client = None
        if httpx is not None:
            self.client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        else:
            self.headers["User-Agent"] = "ArkeBot/1.0"

    @staticmethod
    def _stdlib_request(url: str, headers: Dict[str, str], timeout: float) -> tuple[int, str]:
        req = Request(url, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310
                body = resp.read().decode("utf-8", errors="replace")
                return int(resp.getcode() or 200), body
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return int(exc.code), body
        except URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc

    async def _request(self, url: str, headers: Dict[str, str] | None = None) -> tuple[int, str]:
        merged_headers = dict(self.headers)
        if headers:
            merged_headers.update(headers)

        if self.client is not None:
            response = await self.client.get(url, headers=merged_headers)
            return response.status_code, response.text

        return await asyncio.to_thread(self._stdlib_request, url, merged_headers, 15.0)

    @staticmethod
    def _extract_owner_repo(value: str) -> tuple[str, str]:
        raw = (value or "").strip().strip('"').strip("'")
        if not raw:
            return "", ""

        parsed = urlparse(raw)
        candidate = parsed.path if parsed.scheme or parsed.netloc else raw
        parts = [p for p in candidate.strip("/").split("/") if p]
        if len(parts) >= 2:
            return parts[0], parts[1]
        return "", ""

    @staticmethod
    def _extract_username(value: str) -> str:
        raw = (value or "").strip().strip('"').strip("'")
        if not raw:
            return ""

        parsed = urlparse(raw)
        candidate = parsed.path if parsed.scheme or parsed.netloc else raw
        parts = [p for p in candidate.strip("/").split("/") if p]
        if parts:
            return parts[0]
        return ""
    
    async def get_repo(self, owner: str, repo: str) -> Dict:
        """Informations détaillées sur un dépôt"""
        url = f"https://api.github.com/repos/{owner}/{repo}"
        
        try:
            status_code, body = await self._request(url)
            if status_code == 200:
                data = json.loads(body)
                return {
                    "success": True,
                    "name": data.get("full_name"),
                    "description": data.get("description"),
                    "stars": data.get("stargazers_count"),
                    "forks": data.get("forks_count"),
                    "watchers": data.get("watchers_count"),
                    "open_issues": data.get("open_issues_count"),
                    "language": data.get("language"),
                    "license": data.get("license", {}).get("name"),
                    "created": data.get("created_at"),
                    "updated": data.get("updated_at"),
                    "url": data.get("html_url"),
                    "clone_url": data.get("clone_url")
                }
            else:
                message = ""
                try:
                    message = json.loads(body).get("message", "")
                except Exception:  # noqa: BLE001
                    message = body[:200]
                return {
                    "success": False,
                    "error": f"HTTP {status_code}",
                    "message": message,
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def search_repos(self, query: str, max_results: int = 5, sort: str = "stars") -> List[Dict]:
        """Recherche des dépôts GitHub"""
        url = f"https://api.github.com/search/repositories?q={quote_plus(query)}&sort={sort}&per_page={max_results}"
        
        try:
            status_code, body = await self._request(url)
            if status_code == 200:
                data = json.loads(body)
                return [
                    {
                        "name": item.get("full_name"),
                        "description": item.get("description"),
                        "stars": item.get("stargazers_count"),
                        "forks": item.get("forks_count"),
                        "language": item.get("language"),
                        "url": item.get("html_url"),
                        "updated": item.get("updated_at")
                    }
                    for item in data.get("items", [])
                ]
            else:
                return [{"error": f"HTTP {status_code}"}]
        except Exception as e:
            return [{"error": str(e)}]
    
    async def get_readme(self, owner: str, repo: str, branch: str = "HEAD") -> Dict:
        """Récupère le contenu du README d'un dépôt"""
        url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        headers = dict(self.headers)
        headers["Accept"] = "application/vnd.github.v3.raw"
        
        try:
            status_code, body = await self._request(url, headers=headers)

            if status_code == 200:
                return {
                    "success": True,
                    "content": body[:10000],
                    "length": len(body),
                    "truncated": len(body) > 10000,
                }
            else:
                return {"success": False, "error": f"HTTP {status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_user(self, username: str) -> Dict:
        """Informations sur un utilisateur GitHub"""
        url = f"https://api.github.com/users/{username}"
        
        try:
            status_code, body = await self._request(url)
            if status_code == 200:
                data = json.loads(body)
                return {
                    "success": True,
                    "login": data.get("login"),
                    "name": data.get("name"),
                    "bio": data.get("bio"),
                    "public_repos": data.get("public_repos"),
                    "followers": data.get("followers"),
                    "following": data.get("following"),
                    "blog": data.get("blog"),
                    "url": data.get("html_url")
                }
            else:
                return {"success": False, "error": f"HTTP {status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_user_repos(self, username: str, max_results: int = 5, sort: str = "updated") -> Dict:
        """Liste les depots publics d'un utilisateur GitHub."""
        safe_limit = max(1, min(int(max_results or 5), 30))
        url = (
            f"https://api.github.com/users/{username}/repos"
            f"?type=owner&sort={quote_plus(sort)}&per_page={safe_limit}"
        )

        try:
            status_code, body = await self._request(url)
            if status_code == 200:
                data = json.loads(body)
                repos = [
                    {
                        "name": item.get("name"),
                        "full_name": item.get("full_name"),
                        "description": item.get("description"),
                        "private": item.get("private"),
                        "language": item.get("language"),
                        "stars": item.get("stargazers_count"),
                        "forks": item.get("forks_count"),
                        "url": item.get("html_url"),
                        "updated": item.get("updated_at"),
                    }
                    for item in data
                ]
                return {"success": True, "repositories": repos, "count": len(repos)}
            return {"success": False, "error": f"HTTP {status_code}", "repositories": [], "count": 0}
        except Exception as e:
            return {"success": False, "error": str(e), "repositories": [], "count": 0}
    
    async def handle_tool(self, tool_name: str, args: Dict) -> Dict:
        if tool_name == "github_repo":
            owner = str(args.get("owner", "") or "").strip()
            repo = str(args.get("repo", "") or "").strip()

            # Robust parsing for common LLM argument shapes.
            if "/" in repo and not owner:
                split_owner, split_repo = self._extract_owner_repo(repo)
                owner = owner or split_owner
                repo = split_repo

            if not owner or not repo:
                for key in ("url", "full_name", "repository", "input", "query"):
                    candidate = str(args.get(key, "") or "")
                    if not candidate:
                        continue
                    parsed_owner, parsed_repo = self._extract_owner_repo(candidate)
                    if parsed_owner:
                        owner = owner or parsed_owner
                    if parsed_repo:
                        repo = repo or parsed_repo
                    if owner and repo:
                        break

            if owner and repo:
                return await self.get_repo(owner, repo)

            # If repo is missing, interpret request as user-level repository listing.
            username = owner or self._extract_username(str(args.get("username", "") or ""))
            if not username:
                for key in ("url", "profile", "input", "query"):
                    username = self._extract_username(str(args.get(key, "") or ""))
                    if username:
                        break

            if not username:
                return {
                    "success": False,
                    "error": "invalid_arguments",
                    "message": "github_repo requires owner+repo or a valid GitHub URL/slug.",
                }

            user_info = await self.get_user(username)
            repo_info = await self.get_user_repos(
                username,
                max_results=args.get("max_results", 5),
                sort=str(args.get("sort", "updated") or "updated"),
            )
            return {
                "success": bool(user_info.get("success") or repo_info.get("success")),
                "mode": "user_repos_fallback",
                "user": user_info,
                "repositories": repo_info.get("repositories", []),
                "count": repo_info.get("count", 0),
                "repo_lookup_error": repo_info.get("error"),
            }
        elif tool_name == "github_search":
            return await self.search_repos(
                args.get("query", ""),
                args.get("max_results", 5),
                args.get("sort", "stars")
            )
        elif tool_name == "github_readme":
            owner = str(args.get("owner", "") or "").strip()
            repo = str(args.get("repo", "") or "").strip()

            if "/" in repo and not owner:
                split_owner, split_repo = self._extract_owner_repo(repo)
                owner = owner or split_owner
                repo = split_repo

            if not owner or not repo:
                for key in ("url", "full_name", "repository", "input", "query"):
                    candidate = str(args.get(key, "") or "")
                    if not candidate:
                        continue
                    parsed_owner, parsed_repo = self._extract_owner_repo(candidate)
                    if parsed_owner:
                        owner = owner or parsed_owner
                    if parsed_repo:
                        repo = repo or parsed_repo
                    if owner and repo:
                        break

            if not owner and repo:
                search_results = await self.search_repos(repo, max_results=10, sort="updated")
                exact_matches = []
                for item in search_results:
                    full_name = str(item.get("full_name") or item.get("name") or "")
                    parsed_owner, parsed_repo = self._extract_owner_repo(full_name)
                    if parsed_owner and parsed_repo and parsed_repo.lower() == repo.lower():
                        exact_matches.append((parsed_owner, parsed_repo))

                unique_matches = list(dict.fromkeys(exact_matches))
                if len(unique_matches) == 1:
                    owner, repo = unique_matches[0]
                elif len(unique_matches) > 1:
                    return {
                        "success": False,
                        "error": "ambiguous_repository",
                        "message": f"Multiple repositories match '{repo}'. Provide owner/repo or a full GitHub URL.",
                    }

            if not owner or not repo:
                return {
                    "success": False,
                    "error": "invalid_arguments",
                    "message": "github_readme requires owner+repo, a full GitHub repo URL, or an exact repository name.",
                }

            return await self.get_readme(owner, repo, args.get("branch", "HEAD"))
        elif tool_name == "github_user":
            username = str(args.get("username", "") or "").strip()
            if not username:
                username = self._extract_username(str(args.get("url", "") or ""))
            if not username:
                username = self._extract_username(str(args.get("query", "") or ""))
            return await self.get_user(username)
        else:
            return {"error": f"Outil inconnu: {tool_name}"}
    
    def list_tools(self) -> List[Dict]:
        return [
            {
                "name": "github_repo",
                "description": "Informations détaillées sur un dépôt GitHub",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Propriétaire du dépôt"},
                        "repo": {"type": "string", "description": "Nom du dépôt"}
                    },
                    "required": ["owner", "repo"]
                }
            },
            {
                "name": "github_search",
                "description": "Recherche des dépôts GitHub par mots-clés",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Requête de recherche"},
                        "max_results": {"type": "integer", "description": "Nombre max de résultats (défaut: 5)"},
                        "sort": {"type": "string", "description": "Tri: stars/forks/updated (défaut: stars)"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "github_readme",
                "description": "Récupère le contenu du README d'un dépôt",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Propriétaire du dépôt"},
                        "repo": {"type": "string", "description": "Nom du dépôt"},
                        "branch": {"type": "string", "description": "Branche (défaut: HEAD)"}
                    },
                    "required": ["owner", "repo"]
                }
            },
            {
                "name": "github_user",
                "description": "Informations sur un utilisateur GitHub",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string", "description": "Nom d'utilisateur GitHub"}
                    },
                    "required": ["username"]
                }
            }
        ]


async def run_stdio():
    """Exécute le serveur via stdio (mode MCP)"""
    token = os.environ.get("GITHUB_TOKEN")
    server = GitHubMCP(token=token)
    
    for line in sys.stdin:
        if not line.strip():
            continue
        
        try:
            request = json.loads(line)
            method = request.get("method")
            params = request.get("params", {})
            req_id = request.get("id")
            
            if method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": server.list_tools()}
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                result = await server.handle_tool(tool_name, arguments)
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}]
                    }
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Méthode inconnue: {method}"}
                }
            
            print(json.dumps(response, ensure_ascii=False), flush=True)
        
        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            }
            print(json.dumps(error_response), flush=True)
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(e)}
            }
            print(json.dumps(error_response), flush=True)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()
    
    if args.stdio:
        asyncio.run(run_stdio())
    else:
        print("MCP GitHub Server")
        print(f"Outils: {[t['name'] for t in GitHubMCP().list_tools()]}")
        print("Utilisez --stdio pour le protocole MCP")
        print("Option: GITHUB_TOKEN env pour rate limit élevé")


if __name__ == "__main__":
    main()
