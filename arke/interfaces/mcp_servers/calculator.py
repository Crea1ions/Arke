#!/usr/bin/env python3
"""
MCP Server : Calculator & Unit Conversions
Calculs mathématiques et conversions - Sans API externe
"""

import json
import sys
import asyncio
import math
import random
import re
from typing import Dict, List


class CalculatorMCP:
    """Serveur MCP pour calculs mathématiques et conversions"""
    
    CONVERSIONS = {
        "m_ft": 3.28084, "ft_m": 0.3048,
        "km_miles": 0.621371, "miles_km": 1.60934,
        "cm_in": 0.393701, "in_cm": 2.54,
        "kg_lbs": 2.20462, "lbs_kg": 0.453592,
        "g_oz": 0.035274, "oz_g": 28.3495,
        "c_f": lambda c: (c * 9/5) + 32,
        "f_c": lambda f: (f - 32) * 5/9,
        "c_k": lambda c: c + 273.15,
        "k_c": lambda k: k - 273.15,
        "l_gal": 0.264172, "gal_l": 3.78541,
        "eur_usd": 1.08, "usd_eur": 0.9259,
    }
    
    async def calculate(self, expression: str) -> Dict:
        """Calcule une expression mathématique sécurisée"""
        try:
            expression = expression.replace("^", "**")
            # Handle natural language: "25% of 1000" → "(25/100*1000)"
            expression = re.sub(
                r'(\d+(?:\.\d+)?)\s*%\s*of\s+(\d+(?:\.\d+)?)',
                lambda m: f"({m.group(1)}/100*{m.group(2)})",
                expression, flags=re.IGNORECASE
            )
            # Handle bare percent: "25%" → "(25/100)"
            expression = re.sub(
                r'(\d+(?:\.\d+)?)\s*%(?!\s*of)',
                lambda m: f"({m.group(1)}/100)",
                expression
            )
            
            safe_dict = {
                **{k: v for k, v in math.__dict__.items() if not k.startswith("_")},
                "abs": abs, "round": round, "int": int, "float": float,
                "min": min, "max": max, "sum": sum, "len": len
            }
            
            result = eval(expression, {"__builtins__": {}}, safe_dict)
            
            return {
                "success": True,
                "expression": expression,
                "result": result,
                "type": type(result).__name__
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def convert_units(self, value: float, from_unit: str, to_unit: str) -> Dict:
        """Convertit des unités"""
        key = f"{from_unit}_{to_unit}"
        
        if key in self.CONVERSIONS:
            conversion = self.CONVERSIONS[key]
            result = conversion(value) if callable(conversion) else value * conversion
            return {
                "success": True,
                "from": f"{value} {from_unit}",
                "to": f"{result} {to_unit}",
                "formula": key
            }
        else:
            reverse_key = f"{to_unit}_{from_unit}"
            if reverse_key in self.CONVERSIONS:
                conversion = self.CONVERSIONS[reverse_key]
                result = conversion(value) if callable(conversion) else value * conversion
                return {
                    "success": True,
                    "from": f"{value} {from_unit}",
                    "to": f"{result} {to_unit}",
                    "formula": f"inverse({reverse_key})"
                }
            
            return {
                "success": False,
                "error": f"Conversion inconnue: {from_unit} → {to_unit}",
                "available": ["m/ft", "km/miles", "kg/lbs", "c/f", "c/k", "eur/usd"]
            }
    
    async def random_number(self, min_val: float = 0, max_val: float = 100, integer: bool = False) -> Dict:
        """Génère un nombre aléatoire"""
        if integer:
            result = random.randint(int(min_val), int(max_val))
        else:
            result = random.uniform(min_val, max_val)
        
        return {
            "success": True,
            "value": result,
            "min": min_val,
            "max": max_val,
            "integer": integer
        }
    
    async def statistics(self, numbers: List[float], operation: str) -> Dict:
        """Calculs statistiques sur une liste de nombres"""
        if not numbers:
            return {"success": False, "error": "Liste vide"}
        
        n = len(numbers)
        
        if operation == "mean":
            result = sum(numbers) / n
        elif operation == "median":
            sorted_nums = sorted(numbers)
            mid = n // 2
            result = sorted_nums[mid] if n % 2 else (sorted_nums[mid-1] + sorted_nums[mid]) / 2
        elif operation == "sum":
            result = sum(numbers)
        elif operation == "min":
            result = min(numbers)
        elif operation == "max":
            result = max(numbers)
        elif operation == "variance":
            mean = sum(numbers) / n
            result = sum((x - mean) ** 2 for x in numbers) / n
        elif operation == "stddev":
            mean = sum(numbers) / n
            variance = sum((x - mean) ** 2 for x in numbers) / n
            result = math.sqrt(variance)
        else:
            return {"success": False, "error": f"Opération inconnue: {operation}"}
        
        return {
            "success": True,
            "operation": operation,
            "result": result,
            "count": n
        }
    
    async def handle_tool(self, tool_name: str, args: Dict) -> Dict:
        if tool_name == "calculate":
            return await self.calculate(args.get("expression", ""))
        elif tool_name == "convert_units":
            return await self.convert_units(
                args.get("value", 0),
                args.get("from_unit", ""),
                args.get("to_unit", "")
            )
        elif tool_name == "random_number":
            return await self.random_number(
                args.get("min", 0),
                args.get("max", 100),
                args.get("integer", False)
            )
        elif tool_name == "statistics":
            return await self.statistics(
                args.get("numbers", []),
                args.get("operation", "mean")
            )
        else:
            return {"error": f"Outil inconnu: {tool_name}"}
    
    def list_tools(self) -> List[Dict]:
        return [
            {
                "name": "calculate",
                "description": "Calcule une expression mathématique (+, -, *, /, **, sqrt, sin, cos, log)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "Expression mathématique"}
                    },
                    "required": ["expression"]
                }
            },
            {
                "name": "convert_units",
                "description": "Convertit des unités (longueur, masse, température, volume, monnaie)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "number", "description": "Valeur à convertir"},
                        "from_unit": {"type": "string", "description": "Unité source"},
                        "to_unit": {"type": "string", "description": "Unité cible"}
                    },
                    "required": ["value", "from_unit", "to_unit"]
                }
            },
            {
                "name": "random_number",
                "description": "Génère un nombre aléatoire",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "min": {"type": "number", "description": "Minimum (défaut: 0)"},
                        "max": {"type": "number", "description": "Maximum (défaut: 100)"},
                        "integer": {"type": "boolean", "description": "Entier ? (défaut: false)"}
                    }
                }
            },
            {
                "name": "statistics",
                "description": "Calculs statistiques (mean/median/sum/min/max/variance/stddev)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "numbers": {"type": "array", "items": {"type": "number"}},
                        "operation": {"type": "string"}
                    },
                    "required": ["numbers", "operation"]
                }
            }
        ]


async def run_stdio():
    """Exécute le serveur via stdio (mode MCP)"""
    server = CalculatorMCP()
    
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
        print("MCP Calculator Server")
        print(f"Outils: {[t['name'] for t in CalculatorMCP().list_tools()]}")
        print("Utilisez --stdio pour le protocole MCP")


if __name__ == "__main__":
    main()
