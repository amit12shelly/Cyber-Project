import sqlite3
import hashlib
import time
import random
import os
import secrets
from typing import Optional, Dict, Any

# =========================
# Database Configuration
# =========================

# SQLite database file name
DB_NAME = "game.db"
MAP_FILENAME = "map.txt"
TILE_SIZE = 64

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
# get_random_valid_position
# --------------------------------------------------
# סורקת את קובץ המפה ומחזירה קואורדינטות (x, y)
# של אריח שאינו קיר (#).
# ==================================================
def get_random_valid_position() -> tuple[int, int]:
    valid_tiles = []

    if os.path.exists(MAP_FILENAME):
        try:
            with open(MAP_FILENAME, "r") as f:
                game_map = [line.strip() for line in f.readlines()]

            for row_idx, row in enumerate(game_map):
                for col_idx, tile in enumerate(row):
                    if tile != "#":
                        valid_tiles.append((col_idx, row_idx))
        except Exception as e:
            print(f"Error reading map file: {e}")

    if valid_tiles:
        tile_x, tile_y = random.choice(valid_tiles)
        # מחזיר את המיקום בפיקסלים (עולם המשחק)
        return tile_x * TILE_SIZE, tile_y * TILE_SIZE

    # ברירת מחדל אם המפה לא נמצאה או לא תקינה
    return TILE_SIZE, TILE_SIZE

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
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
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
            last_save INTEGER,
            FOREIGN KEY(player_id) REFERENCES players(id)
        )
        """)

    # ---------------- Inventory Table ----------------
    # Stores all items owned by a player
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            player_id INTEGER NOT NULL,
            slot INTEGER NOT NULL CHECK(slot >= 0 AND slot < 11), 
            item_type TEXT NOT NULL,    -- למשל: 'AK47', 'Pistol', 'HP_Potion'
            ammo INTEGER DEFAULT 0,     -- רלוונטי לנשקים, בשיקויים יהיה 0
            FOREIGN KEY(player_id) REFERENCES players(id),
            UNIQUE(player_id, slot)     -- מונע כפל פריטים באותו סלוט
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
        start_x, start_y = get_random_valid_position()

        secure_id = secrets.randbits(31)

        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO players (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (secure_id, username, hash_password(password), int(time.time()))
        )

        cur.execute(
            "INSERT INTO characters (player_id, x, y, hp, last_save) VALUES (?, ?, ?, ?, ?)",
            (secure_id, start_x, start_y, 100, int(time.time()))
        )

        conn.commit()
        conn.close()
        return True

    except sqlite3.IntegrityError:
        # שם משתמש כבר קיים
        return False
    except Exception as e:
        print(f"Registration error: {e}")
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

    cur.execute("SELECT username FROM players WHERE id=?", (player_id,))
    player_row = cur.fetchone()

    cur.execute("SELECT x, y, hp FROM characters WHERE player_id=?", (player_id,))
    char_row = cur.fetchone()

    cur.execute("SELECT slot, item_type, ammo FROM inventory WHERE player_id=?", (player_id,))
    inv_rows = cur.fetchall()

    conn.close()

    if not player_row or not char_row:
        print(f"[!] Player {player_id} not found in database.")
        return {}

    inventory_dict = {}
    for row in inv_rows:
        slot_id = row[0]
        item_type = row[1]
        ammo_count = row[2]

        inventory_dict[slot_id] = {
            "type": item_type,
            "ammo": ammo_count
        }

    return {
        "player_id": player_id,
        "username": player_row[0],
        "x": char_row[0],
        "y": char_row[1],
        "hp": char_row[2],
        "inventory": inventory_dict
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

    # עדכון נתוני דמות
    cur.execute(
        "UPDATE characters SET x=?, y=?, hp=?, last_save=? WHERE player_id=?",
        (state["x"], state["y"], state["hp"], int(time.time()), state["player_id"])
    )

    cur.execute("DELETE FROM inventory WHERE player_id=?", (state["player_id"],))
    for slot, data in state["inventory"].items():
        cur.execute(
            "INSERT INTO inventory (player_id, slot, item_type, ammo) VALUES (?, ?, ?, ?)",
            (state["player_id"], slot, data["type"], data["ammo"])
        )

    conn.commit()
    conn.close()