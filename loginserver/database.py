#import sqlite3
#import hashlib
import time
import random
import os
import secrets
from typing import Optional, Dict, Any
import bcrypt

from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
# =========================
# Database Configuration
# =========================

# SQLite database file name
DB_NAME = "game.db"
MAP_FILENAME = "map.txt"
TILE_SIZE = 64

#creates connection to DB
# session creator that connects to the engine and creates the session through the connection of the engine to the DB
#the base is for the sqlalcheny to understand its a table
engine = create_engine("sqlite:///:memory:", echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# ==================================================
# hash_password
# --------------------------------------------------
# Hashes a plain-text password using bycrypt
# The hash is stored in the database instead of
# the original password for security reasons.
#
# =================================================
def hash_password(password: str) -> str:
     salt = bcrypt.gensalt()
     hashed = bcrypt.hashpw(password.encode(), salt)
     return hashed.decode()



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
    Base.metadata.create_all(engine)

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())
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
     session = SessionLocal()

     try:
         existing = session.query(Player).filter_by(username=username).first()
         if existing:
             return False

         secure_id = secrets.randbits(31)
         start_x, start_y = get_random_valid_position()

         player = Player(
             id=secure_id,
             username=username,
             password_hash=hash_password(password),
             created_at=int(time.time())
         )

         character = Character(
             player_id=secure_id,
             x=start_x,
             y=start_y,
             hp=100,
             last_save=int(time.time())
         )

         session.add(player)
         session.add(character)
         session.commit()

         return True

     except Exception as e:
         print("Register error:", e)
         session.rollback()
         return False

     finally:
         session.close()
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
#=================================================
def login(username: str, password: str):
    session = SessionLocal()

    try:
        player = session.query(Player).filter_by(username=username).first()

        if not player:
            return None

        if verify_password(password, player.password_hash):
            return player.id

        return None

    finally:
        session.close()
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
#==================================================

class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(Integer)

    character = relationship("Character", back_populates="player", uselist=False)


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), unique=True)
    x = Column(Integer, default=0)
    y = Column(Integer, default=0)
    hp = Column(Integer, default=100)
    last_save = Column(Integer)

    player = relationship("Player", back_populates="character")


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    slot = Column(Integer)
    item_type = Column(String)
    ammo = Column(Integer, default=0)

def load_player(player_id: int):
    session = SessionLocal()

    player = session.query(Player).filter_by(id=player_id).first()
    character = session.query(Character).filter_by(player_id=player_id).first()
    inventory_items = session.query(Inventory).filter_by(player_id=player_id).all()

    session.close()

    if not player or not character:
        return {}

    inventory_dict = {}
    for item in inventory_items:
        inventory_dict[item.slot] = {
            "type": item.item_type,
            "ammo": item.ammo
        }

    return {
        "player_id": player_id,
        "username": player.username,
        "x": character.x,
        "y": character.y,
        "hp": character.hp,
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
#==================================================
def save_player(state):
    session = SessionLocal()

    try:
        character = session.query(Character).filter_by(player_id=state["player_id"]).first()

        character.x = state["x"]
        character.y = state["y"]
        character.hp = state["hp"]
        character.last_save = int(time.time())

        session.query(Inventory).filter_by(player_id=state["player_id"]).delete()

        for slot, data in state["inventory"].items():
            item = Inventory(
                player_id=state["player_id"],
                slot=slot,
                item_type=data["type"],
                ammo=data["ammo"]
            )
            session.add(item)

        session.commit()

    except Exception as e:
        print("Save error:", e)
        session.rollback()

    finally:
        session.close()