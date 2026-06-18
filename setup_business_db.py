import sqlite3

def setup_dummy_warehouse():
    conn = sqlite3.connect("business_data.db")
    cursor = conn.cursor()
    
    # Simulating the Oracle views your LLM has been querying
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS VW_REV_BY_CENTER (
            CENTER_ID INTEGER,
            CENTER_NAME TEXT,
            TOTAL_REVENUE REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS VW_VISITS (
            VISIT_ID INTEGER,
            CENTER_ID INTEGER,
            VISIT_DATE DATE
        )
    """)
    conn.commit()
    print("[+] business_data.db created with healthcare views.")
    conn.close()

if __name__ == "__main__":
    setup_dummy_warehouse()