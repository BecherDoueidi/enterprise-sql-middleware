import os
import re
from flask import Flask, request, jsonify
# The ghost import is gone. We only import the correct, live harvester.
from schema_harvester import extract_live_metadata
from openai import OpenAI
from sqlalchemy import text, create_engine
from sqlalchemy.exc import SQLAlchemyError

app = Flask(__name__)
# Initialize the global database connection for the execution block
engine = create_engine("postgresql+psycopg2://postgres:admin@127.0.0.1:5432/postgres")
# Hijack the OpenAI client to point to your local Ollama daemon
client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="local-bypass" # The library requires a string here, but Ollama ignores it
)

def call_llm_api(system_prompt, user_query):
    """
    Executes a live inference call to the local Ollama engine.
    """
    response = client.chat.completions.create(
        model="llama3.2",  # Must match the exact model you verified in step 1
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ],
        temperature=0.0  # Zero hallucination tolerance for code generation
    )
    return response.choices[0].message.content

def violates_security_matrix(query):
    """
    Your defense layer. Inspects raw natural language or generated queries 
    for injection threats before parsing.
    """
    malicious_patterns = [
        r"(?i)\bDROP\b", 
        r"(?i)\bALTER\b", 
        r"(?i)\bDELETE\b", 
        r"(?i)\bTRUNCATE\b",
        r"(?i)--", 
        r"(?i);", 
        r"UNION\s+SELECT"
    ]
    for pattern in malicious_patterns:
        if re.search(pattern, query):
            return True
    return False

@app.route('/api/generate-sql', methods=['POST'])
def generate_sql():
    # 1. Enforce strict JSON data contract
    data = request.get_json()
    if not data or 'query' not in data:
        return jsonify({
            "status": "error",
            "error_code": "INVALID_REQUEST",
            "message": "Missing 'query' parameter in request body."
        }), 400
    
    user_query = data['query']
    
    # 2. Input Validation Layer
    if violates_security_matrix(user_query):
        return jsonify({
            "status": "error",
            "error_code": "SECURITY_VIOLATION",
            "message": "Malicious input signatures detected. Transaction aborted."
        }), 403

    try:
        # 3. Dynamic Context & Dialect Harvesting
        db_dialect, live_schema = extract_live_metadata()
        
        # Explicit few-shot anchors
        few_shot_examples = ""
        if db_dialect.lower() == "sqlite":
            few_shot_examples = """
### CORRECT SYNTAX EXAMPLES FOR SQLITE:
User Query: Combine first and last names of the top 2 oldest employees and get their hire year.
Correct Response: SELECT FirstName || ' ' || LastName AS FullName, strftime('%Y', HireDate) AS HireYear FROM Employee ORDER BY BirthDate ASC LIMIT 2

User Query: Concatenate city and country for customers and limit to 5.
Correct Response: SELECT BillingCity || ', ' || BillingCountry FROM Invoice LIMIT 5
"""

        # 4. Strict System Boundary Construction
        system_prompt = f"""You are an enterprise-grade Text-to-SQL compilation engine.
Your sole mandate is to convert natural language queries into valid, optimized SQL statements.

CRITICAL OPERATIONAL BOUNDARIES:
1. TARGET DIALECT: You are generating SQL for a '{db_dialect.upper()}' database. You MUST write strictly valid {db_dialect.upper()} syntax.
2. Follow the exact formatting patterns demonstrated in the examples below. Banned syntax includes TOP clauses, CONCAT functions, and YEAR() calls.
3. NEVER append a semicolon (;) to the end of your generated SQL string.
{few_shot_examples}

Target Database Schema Context:
{live_schema}
"""

        # 5. The Execution & Agentic Healing Loop
        max_retries = 2
        attempt = 0
        current_sql = ""
        current_system_prompt = system_prompt 

        while attempt <= max_retries:
            # 5a. Generate SQL
            current_sql = call_llm_api(current_system_prompt, user_query)
            
            # ---> THE ENGINEERING FIX: Programmatic Sanitization <---
            # Strip trailing whitespace and physically remove any trailing semicolons
            current_sql = current_sql.strip().rstrip(';')
            
            # Logging
            print(f"\n[Attempt {attempt}] AI Generated: {current_sql}")
            
            # 5b. Run Security Fence
            if violates_security_matrix(current_sql):
                print(f"[Attempt {attempt}] BLOCKED BY SECURITY MATRIX") # ---> ADD THIS
                return jsonify({
                    "status": "error", 
                    "error_code": "MALICIOUS_OUTPUT_BLOCKED", 
                    "message": "Query violated security matrix."
                }), 403

            # 5c. Database Execution Attempt
            try:
                with engine.connect() as connection:
                    result = connection.execute(text(current_sql))
                    
                    if current_sql.strip().upper().startswith("SELECT"):
                        data = [dict(row) for row in result.mappings()]
                        return jsonify({
                            "status": "success", 
                            "generated_sql": current_sql, 
                            "retries_used": attempt, 
                            "data": data
                        }), 200
                    else:
                        connection.commit()
                        return jsonify({
                            "status": "success", 
                            "generated_sql": current_sql, 
                            "retries_used": attempt, 
                            "message": "Executed successfully."
                        }), 200
            
            # 5d. Catch Database Execution Errors
            except SQLAlchemyError as db_error:
                error_msg = str(db_error._message()) if hasattr(db_error, '_message') else str(db_error)
                print(f"\n--- EXECUTION FAILED (Attempt {attempt + 1}) ---")
                print(f"Failed SQL: {current_sql}")
                print(f"DB Error: {error_msg}")
                
                # If retry limit hit, fail safely
                if attempt == max_retries:
                    return jsonify({
                        "status": "error", 
                        "message": "AI failed to generate a valid query after maximum retry attempts.",
                        "final_sql": current_sql,
                        "database_error": error_msg
                    }), 500
                
                # 5e. Re-frame Context
                print(">>> Triggering AI Self-Healing Prompt...")
                current_system_prompt = f"""You are an expert database administrator. 
Your previous SQL query failed to execute on the '{db_dialect.upper()}' database.

Target Database Schema Context:
{live_schema}

Original User Request: {user_query}
Failed SQL Query: {current_sql}
Database Error Message: {error_msg}

Analyze the error message. Rewrite the query to fix the syntax, type mismatch, or missing column. 
Return ONLY the corrected raw SQL string. Do not include markdown formatting or explanations."""
                
                attempt += 1

    except Exception as e:
        # 6. FATAL ERROR EXPOSURE
        print(f"\n--- FATAL PIPELINE CRASH ---\n{str(e)}\n----------------------------\n")
        return jsonify({
            "status": "error",
            "error_code": "INTERNAL_SYSTEM_FAILURE",
            "message": "An unhandled exception occurred in the middleware backend pipeline."
        }), 500
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)