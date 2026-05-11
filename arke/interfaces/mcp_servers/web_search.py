#!/usr/bin/env python3
"""
MCP Server : Web Search
Utilise ddgs (DuckDuckGo) pour de vraies recherches web
"""

import json
import sys
import asyncio
import urllib.parse
from typing import Dict, List


class WebSearchMCP:

    def _ddgs_search(self, query: str, max_results: int = 5) -> List[Dict]:
        """Recherche via ddgs (DuckDuckGo)."""
        try:
            from ddgs import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")[:500],
                        "source": "duckduckgo"
                    })
            return results
        except Exception:
            return []

    async def search(self, query: str, max_results: int = 5) -> List[Dict]:
        """Recherche web via DuckDuckGo."""
        # ddgs est synchrone — exécuter dans un thread pour ne pas bloquer
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, self._ddgs_search, query, max_results)

        if results:
            return results[:max_results]

        # Fallback: lien direct DuckDuckGo si ddgs échoue
        return [{
            "title": f"Recherche DuckDuckGo pour '{query}'",
            "url": f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
            "snippet": f"Cliquez pour voir les résultats de recherche pour {query}",
            "source": "fallback-ddg"
        }]

    async def fetch_page(self, url: str, max_length: int = 5000) -> Dict:
        """Récupère une page web."""
        import httpx
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ArkeBot/1.0)"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=headers, follow_redirects=True)

                if "text/html" in response.headers.get("content-type", ""):
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(response.text, 'html.parser')
                        for element in soup(["script", "style", "nav", "footer"]):
                            element.decompose()
                        text = ' '.join(
                            line.strip()
                            for line in soup.get_text().splitlines()
                            if line.strip()
                        )
                        return {
                            "success": True,
                            "url": str(response.url),
                            "title": soup.title.string if soup.title else "",
                            "content": text[:max_length],
                            "content_type": "text/html"
                        }
                    except ImportError:
                        pass

                return {
                    "success": True,
                    "url": str(response.url),
                    "content": response.text[:max_length],
                    "content_type": response.headers.get("content-type", "unknown")
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def handle_tool(self, tool_name: str, args: Dict) -> Dict:
        if tool_name == "web_search":
            return await self.search(args.get("query", ""), args.get("max_results", 5))
        elif tool_name == "fetch_page":
            return await self.fetch_page(args.get("url", ""), args.get("max_length", 5000))
        else:
            return {"error": f"Outil inconnu: {tool_name}"}

    def list_tools(self) -> List[Dict]:
        return [
            {
                "name": "web_search",
                "description": "Recherche web via DuckDuckGo",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "fetch_page",
                "description": "Récupère le contenu d'une page web",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_length": {"type": "integer", "default": 5000}
                    },
                    "required": ["url"]
                }
            }
        ]


async def run_stdio():
    server = WebSearchMCP()

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            method = req.get("method")
            params = req.get("params", {})
            req_id = req.get("id")

            if method == "tools/list":
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": server.list_tools()}}
            elif method == "tools/call":
                result = await server.handle_tool(params.get("name"), params.get("arguments", {}))
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}]}
                }
            else:
                resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

            print(json.dumps(resp, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}), flush=True)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()

    if args.stdio:
        asyncio.run(run_stdio())
    else:
        print("MCP Web Search Server — DuckDuckGo (ddgs)")
        print(f"Outils: {[t['name'] for t in WebSearchMCP().list_tools()]}")


if __name__ == "__main__":
    main()
