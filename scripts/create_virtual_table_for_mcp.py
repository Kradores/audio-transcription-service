import sqlite3

DB_PATH = r"C:\Users\Alex\source\repos\audio-transcription-service\config\transcripts.db"
SQL_PATH = (
    r"C:\Users\Alex\source\repos\CoreMcp\src\CoreMcp.Tools.Transcript\Sql\transcripts-fts5.sql"
)

with open(SQL_PATH, encoding="utf-8") as f:
    sql_script = f.read()

with sqlite3.connect(DB_PATH) as conn:
    cursor = conn.cursor()
    cursor.executescript(sql_script)
    conn.commit()

print("Database updated successfully.")
