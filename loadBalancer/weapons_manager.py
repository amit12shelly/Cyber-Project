import random


SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
TILE_SIZE = 64

WEAPON_LIST = [["gun", 20, TILE_SIZE * 10],["rifle" ,10 , TILE_SIZE * 20],["rpg",30,TILE_SIZE*25], ["knife", 35, 5]] #-> name,damage,range
WEAPON_NAMES = [w[0] for w in WEAPON_LIST]

MAX_WEAPONS = 9000


class GlobalState:
    def __init__(self):
        self.map_weapons = {}

state = GlobalState()


# Spawn loot so that each camera-sized zone has at least per_zone items.
def spawn_loot_per_camera_zone(game_map, per_zone=2):
    loot_list = []

    tiles_wide = len(game_map[0])
    tiles_high = len(game_map)

    zone_tiles_x = SCREEN_WIDTH // TILE_SIZE
    zone_tiles_y = SCREEN_HEIGHT // TILE_SIZE

    for win_y in range(0, tiles_high, zone_tiles_y):
        for win_x in range(0, tiles_wide, zone_tiles_x):
            spawned = 0
            attempts = 0
            while spawned < per_zone and attempts < 50:
                attempts += 1
                tile_x = random.randint(win_x, min(win_x + zone_tiles_x - 1, tiles_wide - 1))
                tile_y = random.randint(win_y, min(win_y + zone_tiles_y - 1, tiles_high - 1))

                if game_map[tile_y][tile_x] != "#":
                    x = tile_x * TILE_SIZE
                    y = tile_y * TILE_SIZE
                    name = random.choice(WEAPON_NAMES)
                    loot_list.append((x, y, name))

                    new_id = random.randint(1, int(MAX_WEAPONS))
                    while new_id in state.map_weapons:
                        new_id = random.randint(1, int(MAX_WEAPONS))
                    state.map_weapons[new_id] = {
                        "x": x,
                        "y": y,
                        "type": name
                    }

                    spawned += 1