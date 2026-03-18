import random


SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
TILE_SIZE = 64

MONSTER_NAMES = []

MAX_POTIONS = 9000


def spawn_monsters_per_camera_zone(game_map, per_zone=1):
    """
    מפזר מפלצות כך שבכל אזור בגודל מסך (Camera-sized zone)
    תהיה לפחות כמות של per_zone מפלצות.
    """
    global monsters_list
    monsters_list = []

    tiles_wide = len(game_map[0])
    tiles_high = len(game_map)

    # חישוב כמה טיילים נכנסים ברוחב וגובה של מסך אחד
    zone_tiles_x = SCREEN_WIDTH // TILE_SIZE
    zone_tiles_y = SCREEN_HEIGHT // TILE_SIZE

    spawned_total = 0

    # מעבר על המפה ב"קפיצות" של גודל מסך
    for win_y in range(0, tiles_high, zone_tiles_y):
        for win_x in range(0, tiles_wide, zone_tiles_x):

            spawned_in_zone = 0
            attempts = 0

            # ניסיון להספין את כמות המפלצות המבוקשת לאזור הזה
            while spawned_in_zone < per_zone and attempts < 50:
                attempts += 1

                # הגרלת טייל בתוך גבולות ה-Zone הנוכחי
                tile_x = random.randint(win_x, min(win_x + zone_tiles_x - 1, tiles_wide - 1))
                tile_y = random.randint(win_y, min(win_y + zone_tiles_y - 1, tiles_high - 1))

                # בדיקה שהטייל הוא רצפה ('.') ולא קיר ('#')
                if game_map[tile_y][tile_x] == ".":
                    pixel_x = float(tile_x * TILE_SIZE)
                    pixel_y = float(tile_y * TILE_SIZE)

                    # יצירת המפלצת (הוספתי סוג רנדומלי מהרשימה)
                    m_type = random.choice(MONSTER_TYPES)
                    monster = Monster(pixel_x, pixel_y, 100)
                    # אם ל-Monster שלך יש שדה type, אפשר להוסיף אותו כאן:
                    # monster.type = m_type

                    monsters_list.append(monster)

                    spawned_in_zone += 1
                    spawned_total += 1

    print(f"Server initialized with {spawned_total} monsters distributed across zones.")