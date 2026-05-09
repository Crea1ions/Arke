# Router Rust (PyO3 Binding)

## Overview

This directory contains the **Rust performance optimization layer** for Arke's dispatch system.

## Important: What This Is NOT

❌ NOT a "cognitive router"  
❌ NOT an "intelligent dispatch system"  
❌ NOT responsible for tool selection  
❌ NOT a decision engine  

## What This IS

✅ **Performance optimization** — Compiled Rust for fast dispatch  
✅ **Transport layer** — Moves data through the pipeline efficiently  
✅ **Non-cognitive** — Zero decision-making logic  

## Architecture

```
Python (Agent Decision)
    ↓
[Agent chooses: "cli"]
    ↓
Rust Router (PyO3 binding)
    ├─ Parse tool_name
    ├─ Route to executor
    └─ Pass through result
    ↓
Python (Execute + Format)
```

### Philosophy

- **Agent decides** which tool to use
- **Rust routes** the request to the right executor
- **Python executes** the tool and formats output

**Rust is for speed, not intelligence.**

## Build

### Prerequisites
- Rust 1.70+ ([rustup](https://rustup.rs/))
- Python 3.11+ dev headers
- Cargo (included with Rust)

### Compile

```bash
# From project root
cd router_rs
cargo build --release

# PyO3 will create .so file
ls target/release/lib*.so
```

### Link to Python

```bash
# Automatic via setup.py
pip install -e ..

# Or manually
cp target/release/lib*.so ../arke/router_rs.so
```

## Usage

```python
from arke.router_rs import dispatch_tool

# Call from Python
result = dispatch_tool(
    tool_name="cli",
    args={"command": "date"},
    context={}
)
```

## Implementation Details

### Current Status

- **PyO3 binding:** Working
- **Compiled targets:** Linux x86_64, macOS x86_64/arm64
- **Integration:** Optional performance layer

### Future Optimizations

- [ ] Async dispatch
- [ ] Connection pooling
- [ ] Result caching
- [ ] Metrics collection

## Testing

```bash
# Python tests (via Arke)
pytest ../tests/test_router_rs.py -v

# Rust tests
cargo test

# Benchmark
cargo bench
```

## Important Notes

1. **This router does NOT make cognitive decisions**
   - All tool selection happens in Python agent
   - Rust simply transports the request

2. **Fallback available**
   - If compilation fails, Python uses pure Python dispatcher
   - Zero impact on functionality

3. **No special privileges**
   - Rust code runs in same security context as Python
   - Sandbox restrictions still apply

## Architecture Alignment

See [../Arke-02-architecture/Arke-architecture.md](../Arke-02-architecture/Arke-architecture.md) for full system design.

Key principle: **Rust handles transport performance, not cognitive decisions.**

---

**Version:** 1.0 · **Status:** Optional performance layer · **Fallback:** Pure Python available
