from sqlalchemy import create_engine, MetaData

def extract_live_metadata():
    # URI updated to match your exact downloaded file
    engine = create_engine("sqlite:///Chinook_Sqlite.sqlite")
    metadata = MetaData()
    metadata.reflect(bind=engine)
    
    schema_context = "Allowed views:\n"
    for table in metadata.sorted_tables:
        columns = [col.name for col in table.c]
        schema_context += f"- {table.name}: {', '.join(columns)}\n"
        
    return schema_context

if __name__ == "__main__":
    print("Extracting live metadata...\n")
    print(extract_live_metadata())