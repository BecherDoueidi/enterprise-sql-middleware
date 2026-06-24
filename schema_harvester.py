from sqlalchemy import create_engine, MetaData
from sqlalchemy import create_engine, inspect
def extract_live_metadata(connection_string="postgresql+psycopg2://postgres:admin@127.0.0.1:5432/postgres"):
    # In a real enterprise environment, this connection string is loaded from an .env file
    engine = create_engine(connection_string)
    inspector = inspect(engine)
    
    # 1. Interrogate the engine for its exact dialect (e.g., 'sqlite', 'postgresql', 'oracle')
    db_dialect = engine.dialect.name
    
    # 2. Harvest the schema (This should match your existing extraction logic)
    schema_text = ""
    for table_name in inspector.get_table_names():
        schema_text += f"Table: {table_name}\n"
        # Open schema_harvester.py and ensure column['type'] is explicitly cast to a string
    for column in inspector.get_columns(table_name):
        schema_text += f"  - {column['name']} ({str(column['type'])})\n"
            
    # 3. Return both the dialect and the schema as a tuple
    return db_dialect, schema_text

if __name__ == "__main__":
    print("Extracting live metadata...\n")
    print(extract_live_metadata())