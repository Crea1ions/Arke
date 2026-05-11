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
from urllib.parse import quote_plus

import httpx


class GitHubMCP:
    """Serveur MCP pour GitHub API"""
    
    def __init__(self, token: str = None):
        self.client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        else:
            self.headers["User-Agent"] = "ArkeBot/1.0"
    
    async def get_repo(self, owner: str, repo: str) -> Dict:
        """Informations détaillées sur un dépôt"""
        url = f"https://api.github.com/repos/{owner}/{repo}"
        
        try:
            response = await self.client.get(url, headers=self.headers)
            
            if response.status_code == 200:
                data = response.json()
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
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "message": response.json().get("message", "")
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def search_repos(self, query: str, max_results: int = 5, sort: str = "stars") -> List[Dict]:
        """Recherche des dépôts GitHub"""
        url = f"https://api.github.com/search/repositories?q={quote_plus(query)}&sort={sort}&per_page={max_results}"
        
        try:
            response = await self.client.get(url, headers=self.headers)
            
            if response.status_code == 200:
                data = response.json()
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
                return [{"error": f"HTTP {response.status_code}"}]
        except Exception as e:
            return [{"error": str(e)}]
    
    async def get_readme(self, owner: str, repo: str, branch: str = "HEAD") -> Dict:
        """Récupère le contenu du README d'un dépôt"""
        url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        headers = dict(self.headers)
        headers["Accept"] = "application/vnd.github.v3.raw"
        
        try:
            response = await self.client.get(url, headers=headers)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "content": response.text[:10000],
                    "length": len(response.text),
                    "truncated": len(response.text) > 10000
                }
            else:
                return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_user(self, username: str) -> Dict:
        """Informations sur un utilisateur GitHub"""
        url = f"https://api.github.com/users/{username}"
        
        try:
            response = await self.client.get(url, headers=self.headers)
            
            if response.status_code == 200:
                data = response.json()
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
                return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def handle_tool(self, tool_name: str, args: Dict) -> Dict:
        if tool_name == "github_repo":
            return await self.get_repo(args.get("owner", ""), args.get("repo", ""))
        elif tool_name == "github_search":
            return await self.search_repos(
                args.get("query", ""),
                args.get("max_results", 5),
                args.get("sort", "stars")
            )
        elif tool_name == "github_readme":
            return await self.get_readme(
                args.get("owner", ""),
                args.get("repo", ""),
                args.get("branch", "HEAD")
            )
        elif tool_name == "github_user":
            return await self.get_user(args.get("username", ""))
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
