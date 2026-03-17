import random


SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
TILE_SIZE = 64

MONSTER_LIST = [["Potion", 40],["Poison",5]] #-> name,hp++
POTION_NAMES = [m[0] for m in MONSTER_LIST]

MAX_POTIONS = 9000


def spawn_random_monsters(amount):
    tiles_high = len(state.game_map)
    tiles_wide = len(state.game_map[0])
    global monsters_list
    monsters_list = []

    spawned = 0

    while spawned < amount:

        tile_x = random.randint(0, tiles_wide - 1)
        tile_y = random.randint(0, tiles_high - 1)

        if state.game_map[tile_y][tile_x] == ".":

            pixel_x = float(tile_x * TILE_SIZE)
            pixel_y = float(tile_y * TILE_SIZE)

            monster = Monster(pixel_x, pixel_y, 100)
            monsters_list.append(monster)

            spawned += 1

    print(f"Server initialized with {spawned} monsters on the map.")