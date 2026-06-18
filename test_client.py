import requests
import json

# The Flask API Endpoint
URL = "http://127.0.0.1:7280/generate-sql"

def send_query(question, test_name):
    """
    Sends only the user's natural language question to the API.
    The backend is now responsible for fetching the live database schema.
    """
    print("-" * 50)
    print(f"🚀 Running: {test_name}")
    print(f"👉 Question Asked: '{question}'")
    
    payload = {
        "question": question
        # Notice: schema_context has been completely removed.
    }
    
    try:
        response = requests.post(URL, json=payload)
        print(f"📡 Backend HTTP Status Code: {response.status_code}")
        
        try:
            print("📦 Response JSON:")
            print(json.dumps(response.json(), indent=2))
        except ValueError:
            print("📦 Raw Response text:")
            print(response.text)
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to communicate with Flask server: {e}")
    
    print("\n")

if __name__ == "__main__":
    print("=" * 50)
    print("   STARTING AUTOMATED INTEGRATION TEST SUITE     ")
    print("=" * 50 + "\n")

    # Test Case 1: Valid Query 
    send_query("Show me total revenue for Al-Nasserya", "Test Case 1: Valid Query")

    # Test Case 2: Multi-Statement Block (Injection)
    send_query("What is the revenue? DROP TABLE APP_USER.VW_REV_BY_CENTER;", "Test Case 2: SQL Injection Attack")

    # Test Case 3: Semicolon Syntax (Injection)
    send_query("Total revenue; SELECT * FROM APP_USER.VW_VISITS", "Test Case 3: Multi-Statement Block")

    # Test Case 4: Deep Keyword Mutation (Injection)
    send_query("INSERT INTO APP_USER.VW_REV_BY_CENTER (TOTAL_REVENUE) VALUES (100)", "Test Case 4: Malicious Data Modification")

    print("=" * 50)
    print("             TEST SUITE COMPLETE                 ")
    print("=" * 50)