import random


SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
TILE_SIZE = 64

MONSTER_TYPES = ["long", "short"]
MAX_MONSTERS = 5000


class GlobalState:
    def __init__(self):
        self.map_monsters = {}

state = GlobalState()

def spawn_monsters_per_camera_zone(game_map, per_zone=1):

    tiles_wide = len(game_map[0])
    tiles_high = len(game_map)

    zone_tiles_x = SCREEN_WIDTH // TILE_SIZE
    zone_tiles_y = SCREEN_HEIGHT // TILE_SIZE

    spawned_total = 0

    # מעבר על המפה ב"קפיצות" של גודל מסך
    for win_y in range(0, tiles_high, zone_tiles_y):
        for win_x in range(0, tiles_wide, zone_tiles_x):

            spawned_in_zone = 0
            attempts = 0

            while spawned_in_zone < per_zone and attempts < 50:
                attempts += 1

                # הגרלת טייל בתוך גבולות ה-Zone הנוכחי
                tile_x = random.randint(win_x, min(win_x + zone_tiles_x - 1, tiles_wide - 1))
                tile_y = random.randint(win_y, min(win_y + zone_tiles_y - 1, tiles_high - 1))

                # בדיקה שהטייל הוא רצפה ('.') ולא קיר ('#')
                if game_map[tile_y][tile_x] != "#":
                    x = tile_x * TILE_SIZE
                    y = tile_y * TILE_SIZE

                    m_type = random.choice(MONSTER_TYPES)
                    new_id = random.randint(1, MAX_MONSTERS)
                    while new_id in state.map_monsters:
                        new_id = random.randint(1, MAX_MONSTERS)

                    state.map_monsters[new_id] = {
                        "x": x,
                        "y": y,
                        "type": m_type,
                        "hp": 100
                    }

                    spawned_in_zone += 1
                    spawned_total += 1

    print(f"Server initialized with {spawned_total} monsters distributed across zones.")



def spawn_single_monster(game_map):
    tiles_wide = len(game_map[0])
    tiles_high = len(game_map)

    attempts = 0
    while attempts < 100:
        attempts += 1
        tile_x = random.randint(0, tiles_wide - 1)
        tile_y = random.randint(0, tiles_high - 1)

        if game_map[tile_y][tile_x] != "#":
            x = tile_x * TILE_SIZE
            y = tile_y * TILE_SIZE
            m_type = random.choice(MONSTER_TYPES)

            new_id = random.randint(1, MAX_MONSTERS * 10)  # טווח גדול למניעת כפילויות
            while new_id in state.map_monsters:
                new_id = random.randint(1, MAX_MONSTERS * 10)

            state.map_monsters[new_id] = {
                "x": x,
                "y": y,
                "type": m_type,
                "hp": 100
            }
            return state.map_monsters[new_id]
    return None