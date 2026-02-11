import sqlite3
import hashlib
import time
from typing import Optional, Dict, Any

# =========================
# Database Configuration
# =========================

# SQLite database file name
DB_NAME = "game.db"


# ==================================================
# hash_password
# --------------------------------------------------
# Hashes a plain-text password using SHA-256.
# The hash is stored in the database instead of
# the original password for security reasons.
#
# NOTE:
# This is a basic implementation.
# In production systems, a salted and iterated
# hashing algorithm (e.g., bcrypt) should be used.
# ==================================================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ==================================================
# get_conn
# --------------------------------------------------
# Creates and returns a new connection to the SQLite
# database.
#
# Each database operation opens and closes its own
# connection to keep the logic simple and isolated.
# ==================================================
def get_conn():
    return sqlite3.connect(DB_NAME)


# ==================================================
# init_db
# --------------------------------------------------
# Initializes the database schema.
# Creates all required tables if they do not exist.
#
# Tables:
# - players     : Stores account-level information
# - characters  : Stores in-game character state
# - inventory   : Stores player inventory items
# ==================================================
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # ---------------- Players Table ----------------
    # Stores login credentials and persistent player data
    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        level INTEGER DEFAULT 1,
        exp INTEGER DEFAULT 0,
        gold INTEGER DEFAULT 0,
        created_at INTEGER
    )
    """)

    # ---------------- Characters Table ----------------
    # Stores the in-game character state for each player
    # One character per player (player_id is UNIQUE)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS characters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER UNIQUE,
        x INTEGER DEFAULT 0,
        y INTEGER DEFAULT 0,
        hp INTEGER DEFAULT 100,
        mp INTEGER DEFAULT 50,
        last_save INTEGER,
        FOREIGN KEY(player_id) REFERENCES players(id)
    )
    """)

    # ---------------- Inventory Table ----------------
    # Stores all items owned by a player
    cur.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        slot INTEGER NOT NULL CHECK(slot >= 0 AND slot < 10),
        item_name TEXT,
        amount INTEGER DEFAULT 0,
        FOREIGN KEY(player_id) REFERENCES players(id),
        UNIQUE(player_id, slot)
    );
    """)

    conn.commit()
    conn.close()


# ==================================================
# register
# --------------------------------------------------
# Registers a new user account.
#
# Parameters:
# - username : desired username (must be unique)
# - password : plain-text password
#
# Behavior:
# - Inserts a new row into the players table
# - Automatically creates a default character
#
# Returns:
# - True  -> registration successful
# - False -> username already exists
# ==================================================
def register(username: str, password: str) -> bool:
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Insert new player
        cur.execute(
            "INSERT INTO players (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), int(time.time()))
        )

        player_id = cur.lastrowid

        # Create default character for the player
        cur.execute(
            "INSERT INTO characters (player_id, last_save) VALUES (?, ?)",
            (player_id, int(time.time()))
        )

        conn.commit()
        conn.close()
        return True

    except sqlite3.IntegrityError:
        # Triggered when username already exists
        return False


# ==================================================
# login
# --------------------------------------------------
# Authenticates a user.
#
# Parameters:
# - username : account username
# - password : plain-text password
#
# Returns:
# - player_id (int) if credentials are valid
# - None if authentication fails
# ==================================================
def login(username: str, password: str) -> Optional[int]:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM players WHERE username=? AND password_hash=?",
        (username, hash_password(password))
    )

    row = cur.fetchone()
    conn.close()

    return row[0] if row else None


# ==================================================
# load_player
# --------------------------------------------------
# Loads all persistent player data from the database
# into memory (RAM).
#
# Used when a player successfully logs in and
# enters the game server.
#
# Returns:
# A dictionary containing:
# - account data
# - character state
# - inventory
# ==================================================
def load_player(player_id: int) -> Dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()

    # Load basic player data
    cur.execute(
        "SELECT username, level, exp, gold FROM players WHERE id=?",
        (player_id,)
    )
    p = cur.fetchone()

    # Load character state
    cur.execute(
        "SELECT x, y, hp, mp FROM characters WHERE player_id=?",
        (player_id,)
    )
    c = cur.fetchone()

    # Load inventory
    cur.execute(
        "SELECT item_name, amount FROM inventory WHERE player_id=?",
        (player_id,)
    )
    inv = cur.fetchall()

    conn.close()

    return {
        "player_id": player_id,
        "username": p[0],
        "level": p[1],
        "exp": p[2],
        "gold": p[3],
        "x": c[0],
        "y": c[1],
        "hp": c[2],
        "mp": c[3],
        "inventory": {name: amount for name, amount in inv}
    }


# ==================================================
# save_player
# --------------------------------------------------
# Saves the current in-memory player state back
# into the database.
#
# Called periodically or on player logout.
#
# Parameters:
# - state : dictionary containing player state
# ==================================================
def save_player(state: Dict[str, Any]):
    conn = get_conn()
    cur = conn.cursor()

    # Update player stats
    cur.execute(
        "UPDATE players SET level=?, exp=?, gold=? WHERE id=?",
        (state["level"], state["exp"], state["gold"], state["player_id"])
    )

    # Update character state
    cur.execute(
        "UPDATE characters SET x=?, y=?, hp=?, mp=?, last_save=? WHERE player_id=?",
        (state["x"], state["y"], state["hp"], state["mp"], int(time.time()), state["player_id"])
    )

    # Replace inventory (simple but safe approach)
    cur.execute(
        "DELETE FROM inventory WHERE player_id=?",
        (state["player_id"],)
    )

    for item, amount in state["inventory"].items():
        cur.execute(
            "INSERT INTO inventory (player_id, item_name, amount) VALUES (?, ?, ?)",
            (state["player_id"], item, amount)
        )

    conn.commit()
    conn.close()