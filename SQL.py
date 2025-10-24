import sqlite3

conn = sqlite3.connect(r"C:\Users\ishan\OneDrive\Desktop\career-navigator-ai\backend\users.db")
cursor = conn.cursor()

# Check existing tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("📋 Existing Tables:", cursor.fetchall())

# Create Jobs table
cursor.execute("""
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    description TEXT,
    link TEXT,
    posted_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")

# Create Saved Jobs table
cursor.execute("""
CREATE TABLE IF NOT EXISTS saved_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    job_id INTEGER,
    saved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
""")

# Add optional indexes
cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);")
cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_saved ON saved_jobs(user_id, job_id);")

conn.commit()
conn.close()
print("✅ Job tables created successfully!")
