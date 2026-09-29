import os
import sys

import pyodbc
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

SERVER = os.environ["DB_SERVER"]
USER = os.environ["DB_USER"]
PASSWORD = os.environ["DB_PASSWORD"]
DRIVER = os.environ.get("DB_DRIVER", "ODBC Driver 17 for SQL Server")

conn_str = f"DRIVER={{{DRIVER}}};SERVER={SERVER};UID={USER};PWD={PASSWORD};TrustServerCertificate=yes;"

print(f"Connecting to {SERVER} as {USER} using their default database ...")
conn = pyodbc.connect(conn_str)
cursor = conn.cursor()
cursor.execute("SELECT DB_NAME(), SUSER_SNAME()")
row = cursor.fetchone()
print(f"Connected successfully. Default database: {row[0]}, logged in as: {row[1]}")
cursor.close()
conn.close()
