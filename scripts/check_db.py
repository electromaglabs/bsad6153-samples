"""Week 2 database check. Run it from the project folder:

    python scripts/check_db.py          # connects as the owner (DATABASE_URL)
    python scripts/check_db.py --app    # connects as the read-only role (APP_DATABASE_URL)

It confirms that your connection string works and shows which database user you
are connected as. It never prints the connection string, which contains your password.
"""

import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

variable = "APP_DATABASE_URL" if "--app" in sys.argv else "DATABASE_URL"
url = os.environ.get(variable)

if not url:
    print(f"[FAIL] {variable} is not set. Add it to your .env file (see .env.example).")
    sys.exit(1)

try:
    # connect_timeout keeps a wrong address from hanging forever.
    with psycopg.connect(url, connect_timeout=10) as conn:
        version, user = conn.execute("select version(), current_user").fetchone()
except psycopg.OperationalError as error:
    # The error text from the server doesn't include your password.
    print(f"[FAIL] Could not connect using {variable}.")
    print(f"       {str(error).strip().splitlines()[0]}")
    print("       Check: Supabase Session pooler string? Correct password? Project paused?")
    sys.exit(1)

print(f"[ok] Connected using {variable}")
print(f"     Database user: {user}")
print(f"     Server: {version.split(',')[0]}")
