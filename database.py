import sqlite3

def create_table():
    conn = sqlite3.connect("insights.db")
    conn.execute("CREATE TABLE IF NOT EXISTS insights (id INTEGER PRIMARY KEY AUTOINCREMENT, buyer TEXT, problem TEXT, relevant_features TEXT, what_worked TEXT)")
    conn.commit()
    conn.close()

def save_insight(buyer, problem, relevant_features, what_worked):
    conn = sqlite3.connect("insights.db")
    conn.execute("INSERT INTO insights (buyer, problem, relevant_features, what_worked) VALUES (?, ?, ?, ?)", (buyer, problem, relevant_features, what_worked))
    conn.commit()
    conn.close()