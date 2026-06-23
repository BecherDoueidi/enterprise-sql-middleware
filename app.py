import os
import re
from flask import Flask, request, jsonify
# The ghost import is gone. We only import the correct, live harvester.
from schema_harvester import extract_live_metadata
from openai import OpenAI

app = Flask(__name__)

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
    
    # 2. Input Validation Layer (Defense-in-Depth)
    if violates_security_matrix(user_query):
        return jsonify({
            "status": "error",
            "error_code": "SECURITY_VIOLATION",
            "message": "Malicious input signatures detected. Transaction aborted."
        }), 403

    try:
        # 3. Dynamic Context Harvesting
        live_schema = extract_live_metadata()
        
        # 4. Strict System Boundary Construction
        system_prompt = f"""You are an enterprise-grade Text-to-SQL compilation engine.
Your sole mandate is to convert natural language queries into valid, optimized SQL statements.

CRITICAL OPERATIONAL BOUNDARIES:
1. You must generate SQL statements based EXCLUSIVELY on the allowed table schemas provided below.
2. Do NOT hallucinate tables, columns, or relations that are not explicitly defined.
3. Only generate SELECT statements. DML or DDL modifications (INSERT, UPDATE, DELETE, DROP) are strictly forbidden.
4. Return ONLY the raw SQL query string inside the response. Do not include markdown code blocks (```sql), explanations, or trailing commentary.

Target Database Schema Context:
{live_schema}
"""
        
        # 5. LLM Execution Phase - Now fully live
        generated_sql = call_llm_api(system_prompt, user_query)
        
        # 6. Post-Generation Output Fence
        if violates_security_matrix(generated_sql):
            return jsonify({
                "status": "error",
                "error_code": "MALICIOUS_OUTPUT_BLOCKED",
                "message": "The engine generated an unvalidated or destructive query string."
            }), 500

        # 7. Standardized Success Response Contract
        return jsonify({
            "status": "success",
            "data": {
                "input_query": user_query,
                "generated_sql": generated_sql.strip()
            }
        }), 200

    except Exception as e:
        # 8. FATAL ERROR EXPOSURE
        # This will print the exact reason the API crashed into your server terminal
        print(f"\n--- FATAL PIPELINE CRASH ---\n{str(e)}\n----------------------------\n")
        
        return jsonify({
            "status": "error",
            "error_code": "INTERNAL_SYSTEM_FAILURE",
            "message": "An unhandled exception occurred in the middleware backend pipeline."
        }), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)