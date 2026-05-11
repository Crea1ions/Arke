"""
Workspace View System (WVS) — Renderers for structured output.

CRITICAL: This module is orchestrator-only. Never expose to LLM context.

Provides rendering logic for /SHOW_WORKSPACE and related commands.
All renderers are pure functions returning formatted strings.
"""

from typing import Dict, Any
from arke.wvs.cache import WorkspaceCache


# Lazy import of theme to avoid circular dependencies
def _get_theme():
    """Get the chat theme module."""
    from arke import chat_theme as T
    return T


class WorkspaceViewRenderer:
    """Renders workspace structure in various formats."""
    
    # Section display order
    SECTION_ORDER = ["mobile-notes", "code", "projects", "shared", "archive"]
    
    # Section metadata for rendering
    SECTION_META = {
        "mobile-notes": {
            "emoji": "📱",
            "label": "mobile-notes",
            "description": "Capture layer (fleeting, ideas, voice, quick-capture, channels)",
        },
        "code": {
            "emoji": "💻",
            "label": "code",
            "description": "Production artifacts (apps, services, libs, experiments)",
        },
        "projects": {
            "emoji": "🧠",
            "label": "projects/TEMP",
            "description": "Structuration layer (dev-sessions, meta-decisions, ops-logs, etc.)",
        },
        "shared": {
            "emoji": "📦",
            "label": "shared",
            "description": "Restitution outputs (session-summaries, generated-insights)",
        },
        "archive": {
            "emoji": "🗃️",
            "label": "archive",
            "description": "Passive storage (archived items)",
        },
    }
    
    @staticmethod
    def render_overview() -> str:
        """
        Render complete workspace overview (all 5 sections).
        
        Shows:
        - Overview of each section with file counts + sizes
        - Notes indicating sub-commands (/SHOW_X)
        
        Returns:
            Formatted string for display
        """
        stats = WorkspaceCache.get()
        if not stats:
            return "⚠️  Workspace cache not initialized"
        
        T = _get_theme()
        lines = [
            f"{T.ACCENT}🧭 WORKSPACE OVERVIEW{T.RESET}",
            "",
        ]
        
        for section in WorkspaceViewRenderer.SECTION_ORDER:
            if section not in stats:
                continue
            
            meta = WorkspaceViewRenderer.SECTION_META[section]
            stat = stats[section]
            
            # Section header with emoji
            lines.append(f"{meta['emoji']} {T.ACCENT}{meta['label']}{T.RESET}")
            
            # Stats line
            files_str = f"{stat['files']} file" + ("s" if stat['files'] != 1 else "")
            size_str = stat.get("size_formatted", "0 B")
            lines.append(f"   {T.TEXT}{files_str} ({size_str}){T.RESET}")
            
            # Subdirectories (if any, and not too many)
            if stat.get("subdirs") and len(stat["subdirs"]) <= 10:
                for subdir in stat["subdirs"][:10]:
                    subdir_files = subdir.get("files", 0)
                    subdir_size = f"{subdir.get('size_bytes', 0) / 1e6:.1f} MB" if subdir.get('size_bytes', 0) > 1e6 else f"{subdir.get('size_bytes', 0) / 1e3:.1f} KB"
                    lines.append(
                        f"   ├─ {T.MUTED}{subdir['name']} ({subdir_files}, {subdir_size}){T.RESET}"
                    )
            
            # Command note (lowercase, with underscores replacing hyphens)
            cmd = f"/show_{section.replace('-', '_')}"
            lines.append(f"   {T.MUTED}👉 {cmd}{T.RESET}")
            lines.append("")
        
        output = "\n".join(lines)
        return T.box(output.split("\n"), title="WORKSPACE OVERVIEW")
    
    @staticmethod
    def render_section(section_id: str) -> str:
        """
        Render detailed view of a single section.
        
        Args:
            section_id: Section identifier (mobile-notes, code, projects, shared, archive)
            
        Returns:
            Formatted string for display
        """
        stats = WorkspaceCache.get()
        if not stats:
            return "⚠️  Workspace cache not initialized"
        
        if section_id not in stats:
            return f"❌ Unknown section: {section_id}"
        
        T = _get_theme()
        meta = WorkspaceViewRenderer.SECTION_META.get(
            section_id,
            {"emoji": "📂", "label": section_id, "description": ""}
        )
        
        stat = stats[section_id]
        
        lines = [
            f"{meta['emoji']} {T.ACCENT}{meta['label']}{T.RESET}",
            f"{T.MUTED}{meta['description']}{T.RESET}",
            "",
            f"{T.TEXT}📊 Statistics{T.RESET}",
            f"  Files: {stat['files']}",
            f"  Size: {stat.get('size_formatted', '0 B')}",
        ]
        
        if stat.get("truncated"):
            lines.append(f"  {T.MUTED}(truncated at 50 files){T.RESET}")
        
        lines.append("")
        
        # Subdirectories tree
        if stat.get("subdirs"):
            lines.append(f"{T.TEXT}📂 Subdirectories{T.RESET}")
            for i, subdir in enumerate(stat["subdirs"]):
                is_last = i == len(stat["subdirs"]) - 1
                prefix = "└─ " if is_last else "├─ "
                subdir_files = subdir.get("files", 0)
                lines.append(
                    f"  {prefix}{T.ACCENT}{subdir['name']}{T.RESET} "
                    f"({T.MUTED}{subdir_files} file{'s' if subdir_files != 1 else ''}{T.RESET})"
                )
                
                # Nested subdirectories (if any)
                if subdir.get("subdirs"):
                    for j, nested in enumerate(subdir["subdirs"]):
                        is_last_nested = j == len(subdir["subdirs"]) - 1
                        nested_prefix = "    └─ " if is_last_nested else "    ├─ "
                        lines.append(
                            f"{nested_prefix}{T.MUTED}{nested['name']} "
                            f"({nested.get('files', 0)} file{'s' if nested.get('files', 0) != 1 else ''}){T.RESET}"
                        )
        else:
            lines.append(f"{T.MUTED}(no subdirectories){T.RESET}")
        
        output = "\n".join(lines)
        return T.box(output.split("\n"), title=f"{meta['label'].upper()} DETAILS")
