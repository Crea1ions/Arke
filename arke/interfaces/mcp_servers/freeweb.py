#!/usr/bin/env python3
"""
MCP Server : FreWeb — Recherche web multi-source
News (DuckDuckGo News) + fetch de page web — Sans clé API
"""

import json
import sys
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

import httpx
from bs4 import BeautifulSoup


class FreWebMCP:
    """Serveur MCP pour recherche d'actualités + fetch de pages"""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=20.0, follow_redirects=True)
        self._executor = ThreadPoolExecutor(max_workers=2)

    def _ddgs_news(self, query: str, max_results: int) -> List[Dict]:
        """Recherche d'actualités via DuckDuckGo News (synchrone)"""
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("body", ""),
                    "source": r.get("source", ""),
                    "date": r.get("date", ""),
                    "type": "news"
                })
        return results

    async def web_search(self, query: str, max_results: int = 5) -> Dict:
        """Recherche d'actualités récentes via DuckDuckGo News"""
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                self._executor, self._ddgs_news, query, max_results
            )
            return {
                "success": True,
                "results": results,
                "source": "duckduckgo_news",
                "count": len(results)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def fetch_page(self, url: str, max_length: int = 8000) -> Dict:
        """Récupère et extrait le contenu textuel d'une page web"""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; ArkeBot/1.0)"}
            response = await self.client.get(url, headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")
            for el in soup(["script", "style", "nav", "footer", "header"]):
                el.decompose()
            article = soup.find("article") or soup.find("main") or soup.find("body")
            text = article.get_text(" ", strip=True) if article else soup.get_text(" ", strip=True)
            return {
                "success": True,
                "url": str(response.url),
                "title": soup.title.string if soup.title else "",
                "content": text[:max_length],
                "content_length": len(text)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def handle_tool(self, tool_name: str, args: Dict) -> Dict:
        if tool_name == "web_search":
            return await self.web_search(args.get("query", ""), args.get("max_results", 5))
        elif tool_name == "fetch_page":
            return await self.fetch_page(args.get("url", ""), args.get("max_length", 8000))
        else:
            return {"error": f"Outil inconnu: {tool_name}"}

    def list_tools(self) -> List[Dict]:
        return [
            {
                "name": "web_search",
                "description": "Recherche d'actualités récentes via DuckDuckGo News (multi-source: Yahoo, Bing News, etc.)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Requête de recherche"},
                        "max_results": {"type": "integer", "description": "Nombre de résultats (défaut: 5)"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "fetch_page",
                "description": "Récupère et extrait le contenu textuel d'une page web à partir de son URL",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL de la page à lire"},
                        "max_length": {"type": "integer", "description": "Longueur max du contenu retourné (défaut: 8000)"}
                    },
                    "required": ["url"]
                }
            }
        ]


async def run_stdio():
    server = FreWebMCP()

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            method = req.get("method")
            params = req.get("params", {})
            req_id = req.get("id")

            if method == "tools/list":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": server.list_tools()}
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                result = await server.handle_tool(tool_name, arguments)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}]
                    }
                }
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown method: {method}"}
                }

            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        except json.JSONDecodeError:
            continue
        except Exception as e:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(run_stdio())
