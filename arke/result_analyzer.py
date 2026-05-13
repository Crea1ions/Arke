"""Result Analyzer — Interprets and summarizes task execution results.

Post-execution analysis:
- Analyzes success/failure of steps
- Extracts key metrics from diagnostic commands
- Generates structured summary for user feedback
- Interprets errors without overwhelming user
"""

from __future__ import annotations

from typing import Any


def analyze_diagnostic_results(steps: list[Any], intention: str) -> dict[str, Any]:
    """Analyze results of diagnostic tasks (status, health check, etc).

    Args:
        steps: List of executed Task steps with output
        intention: Original user intention (for context)

    Returns:
        dict with:
            - summary: Human-readable summary
            - metrics: Key findings
            - failures: Failed steps with analysis
            - recommendation: Next steps if applicable
    """
    result = {
        "summary": [],
        "metrics": {},
        "failures": [],
        "recommendation": None,
    }

    intention_lower = intention.lower()
    has_failures = False
    
    for step in steps:
        tool = step.tool
        status = step.status
        output = step.output or {}
        
        if isinstance(output, dict):
            text = output.get("stdout", "").rstrip()
        else:
            text = str(output).rstrip()
        
        if status.name == "FAILED":
            has_failures = True
            result["failures"].append({
                "tool": tool,
                "reason": _infer_failure_reason(tool, text),
            })
            continue
        
        # Analyze successful diagnostic outputs
        if "df" in step.goal or "disk" in intention_lower:
            metrics = _analyze_disk_output(text)
            result["metrics"]["disk"] = metrics
            if metrics:
                result["summary"].append(f"💾 Disque: {metrics}")
        
        elif "free" in step.goal or "memory" in intention_lower or "mémoire" in intention_lower:
            metrics = _analyze_memory_output(text)
            result["metrics"]["memory"] = metrics
            if metrics:
                result["summary"].append(f"🧠 Mémoire: {metrics}")
        
        elif "uptime" in step.goal or "load" in intention_lower:
            metrics = _analyze_load_output(text)
            result["metrics"]["load"] = metrics
            if metrics:
                result["summary"].append(f"⚙️ Charge: {metrics}")
        
        elif "ps " in step.goal or "processus" in intention_lower:
            metrics = _analyze_process_output(text)
            result["metrics"]["processes"] = metrics
            if metrics:
                result["summary"].append(f"📊 Processus: {metrics}")
    
    # Generate recommendation
    if has_failures:
        result["recommendation"] = (
            "ℹ️ Certaines commandes ne sont pas disponibles (ss, systemctl) "
            "— données de réseau et services inaccessibles dans cet environnement."
        )
    elif all(m for m in result["metrics"].values()):
        result["recommendation"] = "✅ Système opérationnel."
    
    return result


def _infer_failure_reason(tool: str, output: str) -> str:
    """Infer why a command failed."""
    output_lower = output.lower()
    
    if "permission denied" in output_lower:
        return "Accès refusé (permissions insuffisantes)"
    elif "command not found" in output_lower or "not found" in output_lower:
        return "Commande non disponible dans cet environnement"
    elif "no such file" in output_lower:
        return "Fichier ou répertoire non trouvé"
    else:
        return "Échec de la commande (environnement sandbox possible)"


def _analyze_disk_output(text: str) -> str:
    """Extract disk usage summary from df output."""
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return ""
    
    # Parse df -h output (Filesystem, Taille, Utilisé, Dispo, Uti%)
    main_disk = None
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 5 and ("sda" in line or "sdb" in line or "nvme" in line):
            # Found main disk line
            main_disk = line
            break
    
    if not main_disk:
        return "Données disque disponibles"
    
    parts = main_disk.split()
    if len(parts) >= 5:
        used, avail, pct = parts[2], parts[3], parts[4]
        return f"{used} utilisé, {avail} libre ({pct} utilisé)"
    
    return "Disque accessible"


def _analyze_memory_output(text: str) -> str:
    """Extract memory usage summary from free output."""
    lines = text.strip().split("\n")
    for line in lines:
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 3:
                total, used = parts[1], parts[2]
                return f"{used} / {total} utilisée"
    
    return "Mémoire accessible"


def _analyze_load_output(text: str) -> str:
    """Extract load average from uptime output."""
    # uptime format: "HH:MM:SS up X days, HH:MM, N users, load average: X.XX, X.XX, X.XX"
    if "load average" in text:
        parts = text.split("load average: ")
        if len(parts) > 1:
            load = parts[1].strip()
            return f"Charge système: {load}"
    
    return "État système accessible"


def _analyze_process_output(text: str) -> str:
    """Extract top processes from ps output."""
    lines = text.strip().split("\n")
    if len(lines) > 2:
        # ps aux header: USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
        non_sys_procs = [l for l in lines[1:] if l.strip() and "devdipp" in l]
        if non_sys_procs:
            return f"{len(non_sys_procs)} processus utilisateur en cours"
    
    return "Processus système accessibles"


def format_summary(analysis: dict[str, Any]) -> str:
    """Format analysis result as user-friendly text."""
    lines = []
    
    if analysis["summary"]:
        lines.append("📋 **Résumé du diagnostic :**")
        lines.extend(analysis["summary"])
    
    if analysis["failures"]:
        lines.append("")
        lines.append("⚠️ **Commandes non disponibles :**")
        for fail in analysis["failures"]:
            lines.append(f"  • {fail['tool']}: {fail['reason']}")
    
    if analysis["recommendation"]:
        lines.append("")
        lines.append(analysis["recommendation"])
    
    return "\n".join(lines)
