import random


SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
TILE_SIZE = 64

MONSTER_TYPES = ["long", "short"]
MAX_MONSTERS = 5000


class GlobalState:
    def __init__(self):
        self.map_monsters = {}
        self.monster_id_counter = 1

    def get_next_id(self):
        current_id = self.monster_id_counter
        self.monster_id_counter += 1
        return current_id

state = GlobalState()


def spawn_monsters(game_map, total_to_spawn=MAX_MONSTERS):
    """
    מייצר כמות מוגדרת ומדויקת של מפלצות בכל המפה
    """
    tiles_wide = len(game_map[0])
    tiles_high = len(game_map)

    spawned_total = 0
    attempts = 0
    max_attempts = total_to_spawn * 10  # מניעת לולאה אינסופית במקרה של מפה מלאה בקירות

    while spawned_total < total_to_spawn and attempts < max_attempts:
        attempts += 1

        # הגרלת נקודה אקראית בכל רחבי המפה
        tile_x = random.randint(0, tiles_wide - 1)
        tile_y = random.randint(0, tiles_high - 1)

        # בדיקה שהטייל הוא רצפה ולא קיר
        if game_map[tile_y][tile_x] != "#":
            x = tile_x * TILE_SIZE
            y = tile_y * TILE_SIZE
            m_type = random.choice(MONSTER_TYPES)

            new_id = state.get_next_id()

            state.map_monsters[new_id] = {
                "x": x,
                "y": y,
                "type": m_type,
                "hp": 100
            }

            spawned_total += 1

    print(f"[*] World initialized with EXACTLY {spawned_total} monsters.")


def spawn_single_monster(game_map):
    """מייצר מפלצת בודדת (לשימוש כשאחת מתה)"""
    tiles_wide = len(game_map[0])
    tiles_high = len(game_map)

    for _ in range(MAX_MONSTERS):
        tile_x = random.randint(0, tiles_wide - 1)
        tile_y = random.randint(0, tiles_high - 1)

        if game_map[tile_y][tile_x] != "#":
            x = tile_x * TILE_SIZE
            y = tile_y * TILE_SIZE
            m_type = random.choice(MONSTER_TYPES)

            new_id = state.get_next_id()

            state.map_monsters[new_id] = {
                "x": x,
                "y": y,
                "type": m_type,
                "hp": 100
            }
            return state.map_monsters[new_id]
    return None