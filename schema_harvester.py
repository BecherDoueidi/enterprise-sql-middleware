import sqlite3

def fetch_live_schema(db_path="business_data.db"):
    """
    Dynamically interrogates the database dictionary to build the LLM context.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables/views in the database
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        schema_lines = ["Allowed views:"]
        
        for table in tables:
            table_name = table[0]
            # Get columns for each table dynamically
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()
            
            # Format: - TABLE_NAME: COL1, COL2, COL3
            col_names = [col[1] for col in columns]
            schema_lines.append(f"- APP_USER.{table_name}: {', '.join(col_names)}")
            
        return "\n".join(schema_lines)
        
    except Exception as e:
        return f"Error extracting schema: {str(e)}"
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    # Test the harvester in isolation
    print("Extracting live metadata...\n")
    live_schema = fetch_live_schema()
    print(live_schema)