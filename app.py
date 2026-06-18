from flask import Flask, request, jsonify, render_template
import requests
import sqlglot
import sqlite3
import yaml
import os
from schema_harvester import fetch_live_schema

app = Flask(__name__)

# =========================================================================
# SYSTEM CONFIGURATION
# =========================================================================

SYSTEM_PROMPT_TEMPLATE = """You are an Oracle SQL generator for a healthcare reporting layer.

You MUST follow every rule below. Violating ANY rule means your output is rejected:
1. Output ONLY raw SQL. No prose. No markdown. No SQL fences. No explanations.
2. SELECT statements only. No INSERT / UPDATE / DELETE / MERGE / DDL / EXECUTE / BEGIN / DECLARE / CALL.
3. Reference ONLY the views listed in the schema context below. The views are prefixed APP_USER.VW_*.
   Never query base tables.
4. ONE statement only. No semicolons except at the very end (optional).
5. Use Oracle syntax: TRUNC(x, 'MM') / TRUNC(SYSDATE) / FETCH FIRST n ROWS ONLY / HEXTORAW for RAW(16) ids.
6. Aggregate when the question implies it ("how many", "total", "count of") — return a single scalar row.
   List per-row when the question asks for detail ("show me", "list").
7. ALWAYS qualify columns with the view alias to avoid ambiguity.
8. Never reference columns not present in the schema context.

Schema context (the only views and columns you may use):
{schema}"""


# =========================================================================
# DATABASE & LOGGING UTILITIES (PHASE 2)
# =========================================================================

def init_db():
    conn = sqlite3.connect("promotion_queue.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS adhoc_promotion_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_question TEXT NOT NULL,
            generated_sql TEXT,
            execution_status TEXT NOT NULL,  -- 'Approved', 'Rejected', or 'Promoted'
            rejection_details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def log_transaction(question, sql, status, details=""):
    try:
        conn = sqlite3.connect("promotion_queue.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO adhoc_promotion_queue (user_question, generated_sql, execution_status, rejection_details)
            VALUES (?, ?, ?, ?)
        """, (question, sql, status, details))
        conn.commit()
    except Exception as e:
        print(f"[-] Database Logging Failure: {str(e)}")
    finally:
        conn.close()


# =========================================================================
# SECURITY & VALIDATION FENCES
# =========================================================================

def build_error_response(layer, code, message, details=None):
    response = {
        "status": "Rejected",
        "layer": layer,
        "error_code": code,
        "message": message
    }
    if details:
        response["details"] = details
    return jsonify(response), 400

def validate_sql(raw_sql):
    cleaned_sql = raw_sql.strip()
    if cleaned_sql.startswith("```sql"):
        cleaned_sql = cleaned_sql[6:]
    if cleaned_sql.startswith("```"):
        cleaned_sql = cleaned_sql[3:]
    if cleaned_sql.endswith("```"):
        cleaned_sql = cleaned_sql[:-3]
    cleaned_sql = cleaned_sql.strip()

    forbidden_keywords = ["insert", "drop", "delete", "update", "truncate", "alter"]
    if any(keyword in cleaned_sql.lower() for keyword in forbidden_keywords):
        return False, {"code": "SECURITY_VIOLATION", "msg": "Prohibited database mutation keywords found."}

    try:
        parsed = sqlglot.parse(cleaned_sql, read="oracle")
        if len(parsed) > 1:
            return False, {"code": "INJECTION_ATTACK", "msg": "Multiple statements detected."}
        statement = parsed[0]
        if not isinstance(statement, sqlglot.exp.Select):
            return False, {"code": "INVALID_OPERATION", "msg": "Only SELECT statements are authorized."}
        return True, statement.sql(dialect="oracle")
    except sqlglot.errors.ParseError as e:
        return False, {"code": "PARSE_ERROR", "msg": "The AI generated invalid SQL syntax.", "trace": str(e)}


# =========================================================================
# DETERMINISTIC COMPILER ROUTER (PHASE 6)
# =========================================================================

def get_promoted_sql(user_question):
    """
    Checks the YAML catalog for a pre-approved SQL match.
    Bypasses the LLM entirely if a match is found.
    """
    if not os.path.exists("catalog.yaml"):
        return None
        
    try:
        with open("catalog.yaml", "r") as f:
            catalog = yaml.safe_load(f)
            
        if not catalog or "promoted_queries" not in catalog:
            return None
            
        # Normalize input to prevent case-sensitivity or punctuation misses
        normalized_input = user_question.lower().strip().replace("?", "")
        
        for entry in catalog.get("promoted_queries", []):
            if entry["intent"].lower() == normalized_input:
                return entry["sql"]
    except Exception as e:
        print(f"[-] Catalog load error: {e}")
        
    return None


# =========================================================================
# ADMIN UI ROUTES (PHASE 5)
# =========================================================================

@app.route('/admin', methods=['GET'])
def admin_dashboard():
    return render_template('admin.html')

@app.route('/api/queue', methods=['GET'])
def get_queue():
    conn = sqlite3.connect("promotion_queue.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_question, generated_sql, execution_status, rejection_details FROM adhoc_promotion_queue ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    data = [{"id": r[0], "question": r[1], "sql": r[2], "status": r[3], "details": r[4]} for r in rows]
    return jsonify(data)

@app.route('/api/promote/<int:row_id>', methods=['POST'])
def promote_query(row_id):
    conn = sqlite3.connect("promotion_queue.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE adhoc_promotion_queue SET execution_status = 'Promoted' WHERE id = ?", (row_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Successfully promoted"}), 200


# =========================================================================
# CORE GENERATION PIPELINE
# =========================================================================

@app.route('/generate-sql', methods=['POST'])
def generate_sql():
    data = request.get_json()
    if not data or 'question' not in data:
        return build_error_response("API Gateway", "MISSING_PAYLOAD", "Missing question in request.")
        
    question = data['question']
    
    # -------------------------------------------------------------------------
    # 1. INPUT GUARDRAIL FENCE
    # -------------------------------------------------------------------------
    if ";" in question:
        log_transaction(question, sql=None, status="Rejected", details="Input Guardrail Block")
        return build_error_response("Input Guardrail", "MALICIOUS_INPUT", "Character ';' is strictly prohibited.")

    # -------------------------------------------------------------------------
    # 2. DETERMINISTIC COMPILER CHECK (PATH 3)
    # -------------------------------------------------------------------------
    promoted_sql = get_promoted_sql(question)
    if promoted_sql:
        print(f"[+] COMPILER HIT: Bypassing LLM for '{question}'")
        log_transaction(question, sql=promoted_sql, status="Promoted", details="Cache hit from catalog.yaml")
        return jsonify({
            "generated_sql": promoted_sql,
            "status": "Promoted"
        })

    # -------------------------------------------------------------------------
    # 3. LLM GENERATION (PATH 2)
    # -------------------------------------------------------------------------
    schema_context = fetch_live_schema("business_data.db")
    if schema_context.startswith("Error"):
        return build_error_response("Database Layer", "SCHEMA_FETCH_FAILED", "Could not connect to live dictionary.")
    
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(schema=schema_context)
    user_prompt = f"Question: {question}\n\nReturn the SQL only:"
    ollama_payload = {
        "model": "qwen2.5-coder:14b",
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "temperature": 0.0
    }
    
    try:
        print(f"[*] COMPILER MISS: Routing '{question}' to LLM Engine...")
        response = requests.post("http://localhost:11434/api/generate", json=ollama_payload)
        response.raise_for_status()
        raw_sql = response.json().get("response", "").strip()
        
        # -------------------------------------------------------------------------
        # 4. OUTPUT VALIDATION FENCE
        # -------------------------------------------------------------------------
        is_valid, validation_result = validate_sql(raw_sql)
        if not is_valid:
             log_transaction(question, sql=raw_sql, status="Rejected", details=validation_result["msg"])
             return build_error_response("Output Fence", validation_result["code"], validation_result["msg"], validation_result.get("trace"))
             
        # -------------------------------------------------------------------------
        # 5. SUCCESSFUL PATH REGISTRATION
        # -------------------------------------------------------------------------
        log_transaction(question, sql=validation_result, status="Approved", details="Passed all validation gates.")
        return jsonify({
            "generated_sql": validation_result, 
            "status": "AdHoc"
        })
        
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Ollama connection failed: {str(e)}"}), 503

if __name__ == '__main__':
    init_db()
    app.run(port=7280, debug=True)