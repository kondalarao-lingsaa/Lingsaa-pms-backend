import os
import sys

import pyodbc
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

SERVER = os.environ["DB_SERVER"]
DB_NAME = os.environ["DB_NAME"]
USER = os.environ["DB_USER"]
PASSWORD = os.environ["DB_PASSWORD"]
DRIVER = os.environ.get("DB_DRIVER", "ODBC Driver 17 for SQL Server")

conn_str = (
    f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE=master;"
    f"UID={USER};PWD={PASSWORD};TrustServerCertificate=yes;"
)

print(f"Connecting to {SERVER} as {USER} ...")
conn = pyodbc.connect(conn_str, autocommit=True)
cursor = conn.cursor()

cursor.execute("SELECT name FROM sys.databases WHERE name = ?", DB_NAME)
exists = cursor.fetchone() is not None

if exists:
    print(f"Database '{DB_NAME}' already exists. Nothing to do.")
else:
    print(f"Creating database '{DB_NAME}' ...")
    cursor.execute(f"CREATE DATABASE [{DB_NAME}]")
    print(f"Database '{DB_NAME}' created successfully.")

cursor.close()
conn.close()
