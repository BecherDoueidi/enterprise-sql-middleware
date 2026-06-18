# Enterprise Secure Text-to-SQL Middleware Engine

A production-grade, secure, multi-path middleware architecture designed to translate natural language user intents into optimized, Oracle-compliant SQL queries. This engine eliminates semantic hallucinations through dynamic database dictionary harvesting and provides defense-in-depth protection against SQL injection vectors via Abstract Syntax Tree (AST) token parsing.

---

## 🏗️ Architectural Topology

The engine routes incoming traffic through an intelligent **Dual-Path Routing Topology** to minimize latency, eliminate compute costs for known intents, and isolate untrusted AI responses.

### 1. Path 3: The Deterministic Compiler (Bypass Engine)
* **Mechanism:** Intercepts traffic at the API gateway layer and cross-references queries against a static `catalog.yaml` manifest.
* **Impact:** Near-zero latency, 0% hallucination risk, and zero token consumption for previously promoted corporate reporting schemas.

### 2. Path 2: Hardened Generative Inference Engine
* **Inference Model:** `qwen2.5-coder:14b` executing via a local isolated instance.
* **Dynamic Context Injection:** Fully automated runtime context resolution via `schema_harvester.py`, extracting live database schemas dynamically via `PRAGMA` table constraints.
* **Defense-in-Depth Security Fences:**
  * **Input Guardrail:** Instant regex blocking of command-chaining punctuation (`;`) prior to model execution.
  * **Output Fence (AST Verification):** Deep-packet inspection of raw generated SQL strings utilizing `sqlglot`. Validates statements down to structural tokens to explicitly block Data Manipulation (DML) or Data Definition (DDL) commands (e.g., `DROP`, `INSERT`).

---

## 📁 System Topology

```text
├── app.py                  # Core Engine Orchestrator & Multi-Path Router
├── schema_harvester.py     # Live Database Dictionary Context Extractor
├── test_client.py          # Automated Acceptance Test Harness
├── catalog.yaml            # Deterministic Promoted Intent Manifest
├── .gitignore              # Production Workspace Rule Manifest
├── templates/
│   └── admin.html          # Human-in-the-Loop Staging & Promotion Dashboard