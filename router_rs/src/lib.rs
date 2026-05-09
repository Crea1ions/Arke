use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashSet;

// ---------------------------------------------------------------------------
// Routing constants — mirrors arke/router.py, immutable until v0.2
// ---------------------------------------------------------------------------

const CLI_COMMANDS: &[&str] = &[
    "echo", "cat", "grep", "find", "ls", "head", "tail",
    "wc", "sort", "uniq", "awk", "sed", "cut", "tr",
    "mogrify", "convert", "ffmpeg",
    "git", "python", "python3",
    "curl", "wget", "jq",
];

const FS_KEYWORDS: &[&str] = &[
    "read", "write", "file", "fichier", "directory", "dossier", "path", "chemin", "list",
];

const SQLITE_KEYWORDS: &[&str] = &[
    "query", "database", "sqlite", "search", "requête", "cherche", "select",
];

const LOG_KEYWORDS: &[&str] = &[
    "log", "logs", "analyse", "analyz", "erreur", "error", "nginx", "apache", "access.log",
];

// ---------------------------------------------------------------------------
// Helper: tokenise intention string into lowercase words
// ---------------------------------------------------------------------------

fn tokenize(intention: &str) -> Vec<String> {
    intention
        .to_lowercase()
        .split_whitespace()
        .map(String::from)
        .collect()
}

fn first_word(tokens: &[String]) -> &str {
    tokens.first().map(String::as_str).unwrap_or("")
}

fn matches_any(tokens: &[String], keywords: &[&str]) -> bool {
    let kw_set: HashSet<&str> = keywords.iter().copied().collect();
    tokens.iter().any(|t| kw_set.contains(t.as_str()))
}

fn keyword_count(low: &str, keywords: &[&str]) -> usize {
    keywords.iter().filter(|&&kw| low.contains(kw)).count()
}

fn is_log_analysis(low: &str) -> bool {
    keyword_count(low, LOG_KEYWORDS) >= 2
}

// ---------------------------------------------------------------------------
// select_tool — exposed to Python
// ---------------------------------------------------------------------------

/// Return the single best tool name for *intention*.
///
/// Args:
///     intention (str): Raw user intention string.
///     _context (dict): Execution context (unused in routing decision).
///
/// Returns:
///     str: One of ``'cli'``, ``'fs'``, ``'sqlite'``, ``'llm'``.
///
/// Raises:
///     ValueError: If intention is empty or invalid.
#[pyfunction]
fn select_tool(intention: &str, _context: &Bound<'_, PyDict>) -> PyResult<String> {
    if intention.trim().is_empty() {
        return Err(PyValueError::new_err("intention must not be empty"));
    }

    let tokens = tokenize(intention);
    let fw = first_word(&tokens);

    let cli_set: HashSet<&str> = CLI_COMMANDS.iter().copied().collect();

    if cli_set.contains(fw) {
        return Ok("cli".to_string());
    }
    if matches_any(&tokens, FS_KEYWORDS) {
        return Ok("fs".to_string());
    }
    if matches_any(&tokens, SQLITE_KEYWORDS) {
        return Ok("sqlite".to_string());
    }
    Ok("llm".to_string())
}

// ---------------------------------------------------------------------------
// plan — builds a Python Task dict
// ---------------------------------------------------------------------------

/// Build a Task dict from *intention* and *context*.
///
/// Returns a Python dict matching the ``Task`` dataclass contract.
/// Multi-step plans are produced for log-analysis patterns.
///
/// Args:
///     intention (str): Raw user intention string.
///     context (dict): Execution context (``log_file``, ``path``, …).
///
/// Returns:
///     dict: Task description with keys ``id``, ``description``, ``steps``.
///
/// Raises:
///     ValueError: If intention is empty.
#[pyfunction]
fn plan<'py>(
    py: Python<'py>,
    intention: &str,
    context: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    if intention.trim().is_empty() {
        return Err(PyValueError::new_err("intention must not be empty"));
    }

    let task_id = new_id();
    let low = intention.to_lowercase();

    let steps: Vec<Bound<'py, PyDict>> = if is_log_analysis(&low) {
        let log_file = context
            .get_item("log_file")?
            .map(|v| v.to_string())
            .unwrap_or_else(|| "access.log".to_string());
        build_log_analysis_steps(py, &log_file)?
    } else {
        let tool = select_tool(intention, context)?;
        vec![build_single_step(py, intention, &tool, context)?]
    };

    let task = PyDict::new_bound(py);
    task.set_item("id", &task_id)?;
    task.set_item("description", intention)?;
    let steps_list = PyList::new_bound(py, steps.iter());
    task.set_item("steps", steps_list)?;
    Ok(task)
}

// ---------------------------------------------------------------------------
// Private builders
// ---------------------------------------------------------------------------

fn build_log_analysis_steps<'py>(
    py: Python<'py>,
    log_file: &str,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    // Step 1: grep (extract logs via CLI)
    // Now returns single CLI step (agent handles LLM summarization separately)
    let args1 = PyDict::new_bound(py);
    args1.set_item("command", format!("grep -E '\\s5[0-9][0-9]\\s' {log_file}"))?;

    let validation1 = PyDict::new_bound(py);
    validation1.set_item("type", "return_code")?;
    validation1.set_item("expected", 0)?;

    let step1 = PyDict::new_bound(py);
    step1.set_item("id", "step_1")?;
    step1.set_item("tool", "cli")?;
    step1.set_item("arguments", args1)?;
    step1.set_item("validation", validation1)?;
    step1.set_item("dependencies", Vec::<String>::new())?;

    Ok(vec![step1])
}

fn build_single_step<'py>(
    py: Python<'py>,
    intention: &str,
    tool: &str,
    context: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let args = PyDict::new_bound(py);
    let validation = PyDict::new_bound(py);

    match tool {
        "cli" => {
            args.set_item("command", intention.trim())?;
            validation.set_item("type", "return_code")?;
            validation.set_item("expected", 0)?;
        }
        "fs" => {
            let path = context
                .get_item("path")?
                .map(|v| v.to_string())
                .unwrap_or_else(|| intention.trim().to_string());
            args.set_item("path", &path)?;
            args.set_item("operation", "read")?;
            validation.set_item("type", "file_exists")?;
            validation.set_item("expected", path)?;
        }
        "sqlite" => {
            args.set_item("db", "global")?;
            args.set_item("query", intention.trim())?;
        }
        _ => {
            // llm
            args.set_item("prompt_template", intention.trim())?;
            args.set_item("task_type", "reasoning")?;
        }
    }

    let step = PyDict::new_bound(py);
    step.set_item("id", "step_1")?;
    step.set_item("tool", tool)?;
    step.set_item("arguments", args)?;
    if tool == "cli" || tool == "fs" {
        step.set_item("validation", validation)?;
    }
    step.set_item("dependencies", Vec::<String>::new())?;
    Ok(step)
}

fn new_id() -> String {
    // Lightweight UUID-like string without external deps
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.subsec_nanos())
        .unwrap_or(0);
    format!("rs-{:x}-{:x}", nanos, std::process::id())
}

// ---------------------------------------------------------------------------
// Module definition
// ---------------------------------------------------------------------------

/// Arke deterministic router — Rust/PyO3 extension module.
///
/// Exposes the same API as ``arke.router`` (Python fallback):
///     - ``select_tool(intention, context) -> str``
///     - ``plan(intention, context) -> dict``
#[pymodule]
fn router_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(select_tool, m)?)?;
    m.add_function(wrap_pyfunction!(plan, m)?)?;
    Ok(())
}
