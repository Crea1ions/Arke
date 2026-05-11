#!/usr/bin/env python3
"""
MCP Server : RSS Reader
Lecture de flux RSS/Atom - Sans clé API
"""

import json
import sys
import asyncio
from typing import List, Dict
from urllib.parse import urljoin

import httpx
import feedparser
from bs4 import BeautifulSoup


class RSSReaderMCP:
    """Serveur MCP pour la lecture de flux RSS/Atom"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
    
    async def read_feed(self, url: str, limit: int = 10) -> Dict:
        """Lit un flux RSS/Atom et retourne les entrées"""
        try:
            feed = feedparser.parse(url)
            
            if feed.bozo and not feed.entries:
                return {"success": False, "error": str(feed.bozo_exception)}
            
            entries = []
            for entry in feed.entries[:limit]:
                entries.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", "")[:500],
                    "author": entry.get("author", ""),
                    "id": entry.get("id", "")
                })
            
            return {
                "success": True,
                "feed_title": feed.feed.get("title", ""),
                "feed_link": feed.feed.get("link", ""),
                "total_entries": len(feed.entries),
                "entries": entries
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def discover_feeds(self, url: str) -> List[Dict]:
        """Découvre les flux RSS/Atom à partir d'une page web"""
        try:
            response = await self.client.get(url)
            soup = BeautifulSoup(response.text, 'html.parser')
            feeds = []
            
            for link in soup.find_all('link', type=['application/rss+xml', 'application/atom+xml']):
                href = link.get('href')
                if href:
                    full_url = urljoin(url, href)
                    feeds.append({
                        "url": full_url,
                        "title": link.get('title', ''),
                        "type": link.get('type', '')
                    })
            
            return feeds
        except Exception as e:
            return [{"error": str(e)}]
    
    async def fetch_full_content(self, url: str) -> Dict:
        """Récupère le contenu complet d'un article"""
        try:
            headers = {"User-Agent": "ArkeBot/1.0"}
            response = await self.client.get(url, headers=headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()
            
            article = soup.find('article') or soup.find('main') or soup.find('body')
            
            if article:
                text = article.get_text()
            else:
                text = soup.get_text()
            
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            return {
                "success": True,
                "url": url,
                "title": soup.title.string if soup.title else "",
                "content": text[:10000],
                "content_length": len(text)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def handle_tool(self, tool_name: str, args: Dict) -> Dict:
        if tool_name == "read_rss":
            return await self.read_feed(args.get("url", ""), args.get("limit", 10))
        elif tool_name == "discover_rss":
            return await self.discover_feeds(args.get("url", ""))
        elif tool_name == "fetch_full_content":
            return await self.fetch_full_content(args.get("url", ""))
        else:
            return {"error": f"Outil inconnu: {tool_name}"}
    
    def list_tools(self) -> List[Dict]:
        return [
            {
                "name": "read_rss",
                "description": "Lit un flux RSS ou Atom et retourne les entrées",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL du flux RSS/Atom"},
                        "limit": {"type": "integer", "description": "Nombre max d'entrées (défaut: 10)"}
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "discover_rss",
                "description": "Découvre les flux RSS/Atom disponibles sur une page web",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL de la page web"}
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "fetch_full_content",
                "description": "Récupère le contenu complet d'un article (au-delà du résumé)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL de l'article"}
                    },
                    "required": ["url"]
                }
            }
        ]


async def run_stdio():
    """Exécute le serveur via stdio (mode MCP)"""
    server = RSSReaderMCP()
    
    for line in sys.stdin:
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
        print("MCP RSS Reader Server")
        print(f"Outils: {[t['name'] for t in RSSReaderMCP().list_tools()]}")
        print("Utilisez --stdio pour le protocole MCP")


if __name__ == "__main__":
    main()
