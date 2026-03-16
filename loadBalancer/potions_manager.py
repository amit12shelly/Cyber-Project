import random


SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
TILE_SIZE = 64

POTION_LIST = [["Potion", 40],["Poison",5]] #-> name,hp++
POTION_NAMES = [p[0] for p in POTION_LIST]

MAX_POTIONS = 9000


class GlobalState:
    def __init__(self):
        self.map_potions = {}

state = GlobalState()


def spawn_potions_per_camera_zone(game_map, per_zone=2):
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

                    potion_type = random.choice(POTION_NAMES)

                    new_id = random.randint(1, int(MAX_POTIONS))
                    while new_id in state.map_potions:
                        new_id = random.randint(1, MAX_POTIONS)

                    state.map_potions[new_id] = {
                        "x": x,
                        "y": y,
                        "type": potion_type
                    }

                    spawned += 1