import pygame
import random
import threading
import asyncio
import queue
import math
from queue import Queue
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

SERVER_IP = "127.0.0.1"
SERVER_PORT = 4433
TOLERANCE = 5
MY_ID = ""
incoming_messages = Queue()
outgoing_messages = Queue()
import time

CHAT_MAX_MESSAGES = 10
CHAT_FADE_SECONDS = 8
CHAT_INPUT_MAX_LEN = 100
CHAT_TEXT_COLOR = (255, 255, 255)
CHAT_FONT_SIZE = 18
CHAT_PADDING = 6
CHAT_MSG_HEIGHT = 22
CHAT_X = 10
CHAT_Y_BOTTOM_OFFSET = 120
BULLETS = []


async def quic_network_loop():
    config = QuicConfiguration(
        is_client=True,
        alpn_protocols=["echo-protocol"],
        verify_mode=False
    )

    async with connect(SERVER_IP, SERVER_PORT, configuration=config) as client:
        stream_reader, stream_writer = await client.create_stream()

        async def read_from_server():
            buffer = ""
            while True:
                data = await stream_reader.read(4096)
                if not data:
                    await asyncio.sleep(0.01)
                    continue

                buffer += data.decode()

                while "\n" in buffer:
                    msg, buffer = buffer.split("\n", 1)
                    msg = msg.strip()
                    if msg:
                        incoming_messages.put(msg)

        async def write_to_server():
            while True:
                try:
                    msg = outgoing_messages.get_nowait()
                    stream_writer.write((msg + "\n").encode())
                    await stream_writer.drain()
                except queue.Empty:
                    await asyncio.sleep(0.01)

        await asyncio.gather(read_from_server(), write_to_server())

def start_quic_thread():
    loop = asyncio.new_event_loop()

    def runner():
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(quic_network_loop())
        except Exception as e:
            print("NETWORK THREAD ERROR:", e)

    threading.Thread(target=runner, daemon=True).start()
# ---------------- MAP FUNCTIONS ---------------- #
def load_map(filename):
    with open(filename, "r") as f:
        lines = f.readlines()
    return [list(line.strip()) for line in lines]

def draw_map(screen, game_map, tile_size, camera_x, camera_y,floor_img, wall_img):
        start_tile_x = max(camera_x // tile_size, 0)
        start_tile_y = max(camera_y // tile_size, 0)
        end_tile_x = min((camera_x + screen.get_width()) // tile_size + 1, len(game_map[0]))
        end_tile_y = min((camera_y + screen.get_height()) // tile_size + 1, len(game_map))

        # מצייר רק את הטיילים שנמצאים בטווח
        for y in range(start_tile_y, end_tile_y):
            for x in range(start_tile_x, end_tile_x):
                draw_x = x * tile_size - camera_x
                draw_y = y * tile_size - camera_y

                tile = game_map[y][x]
                if tile == "#":
                    screen.blit(wall_img, (draw_x, draw_y))
                else:
                    screen.blit(floor_img, (draw_x, draw_y))

def is_wall(game_map, tile_x, tile_y):
    if tile_y < 0 or tile_y >= len(game_map):
        return True
    if tile_x < 0 or tile_x >= len(game_map[0]):
        return True
    return game_map[tile_y][tile_x] == "#"

# NEW: Full 64×64 collision check
def collides_with_wall(game_map, x, y, size, tile_size):
    corners = [
        (x, y),  # top-left
        (x + size - 1, y),  # top-right
        (x, y + size - 1),  # bottom-left
        (x + size - 1, y + size - 1)  # bottom-right
    ]

    for cx, cy in corners:
        tile_x = cx // tile_size
        tile_y = cy // tile_size
        if is_wall(game_map, tile_x, tile_y):
            return True

    return False

def spawn_loot_per_camera_zone(game_map, tile_size, loot_pool, screen_width, screen_height, per_zone=2):
    """
    Spawn loot so that each camera-sized zone has at least `per_zone` items.
    """
    loot_list = []

    tiles_wide = len(game_map[0])
    tiles_high = len(game_map)

    zone_tiles_x = screen_width // tile_size
    zone_tiles_y = screen_height // tile_size

    for win_y in range(0, tiles_high, zone_tiles_y):
        for win_x in range(0, tiles_wide, zone_tiles_x):
            spawned = 0
            attempts = 0
            while spawned < per_zone and attempts < 50:
                attempts += 1
                tile_x = random.randint(win_x, min(win_x + zone_tiles_x - 1, tiles_wide - 1))
                tile_y = random.randint(win_y, min(win_y + zone_tiles_y - 1, tiles_high - 1))

                if game_map[tile_y][tile_x] != "#":  # רק על רצפה
                    x = tile_x * tile_size
                    y = tile_y * tile_size
                    item_type, name, image = random.choice(loot_pool)
                    loot_list.append(Item(x, y, image, item_type, name))
                    spawned += 1

    return loot_list

def draw_inventory(screen, player):
    slot_size = 64
    padding = 10
    start_x = (screen.get_width() - (slot_size + padding) * 5) // 2  # 5 סלוטים
    y = screen.get_height() - slot_size - 20

    for i in range(5):  # 5 סלוטים
        x = start_x + i * (slot_size + padding)
        pygame.draw.rect(screen, (50, 50, 50), (x, y, slot_size, slot_size))  # גבול הסלוט
        pygame.draw.rect(screen, (200, 200, 200), (x + 2, y + 2, slot_size - 4, slot_size - 4), 2)  # מסגרת פנימית

        # אם יש נשק בסלוט, מציירים אותו
        if i < len(player.inventory):
            weapon = player.inventory[i]
            screen.blit(weapon.image, (x, y))

        # מדגישים את הסלוט הנבחר
        if i == player.selected_slot:
            pygame.draw.rect(screen, (255, 255, 0), (x, y, slot_size, slot_size), 3)

def get_nearby_item(player, loot_items, radius=70):
    """
    מחזירה את הפריט הראשון שנמצא בטווח מסוים מהשחקן.
    """
    for item in loot_items:
        dx = (player.x + player.size // 2) - (item.x + item.size // 2)
        dy = (player.y + player.size // 2) - (item.y + item.size // 2)
        distance = (dx**2 + dy**2) ** 0.5
        if distance <= radius:
            return item
    return None
# ---------------- Item CLASS ---------------- #
class Item:
    def __init__(self, x, y, image, item_type, name):
        self.x = x
        self.y = y
        self.image = image
        self.type = item_type  # "weapon" / "item"
        self.name = name
        self.size = 64
        self.rect = pygame.Rect(x, y, self.size, self.size)

    def update(self):
            self.rect.topleft = (self.x, self.y)

    def draw(self, screen, camera_x, camera_y):
        screen.blit(self.image, (self.x - camera_x, self.y - camera_y))

# ---------------- PLAYER CLASS ---------------- #
class Player:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.hp = 100
        self.speed = 4
        self.direction = "up"
        self.size = 64  # player size

        # Load sprites
        self.base_sprites = {
            "up": pygame.transform.scale(pygame.image.load("img/upSprite.png"), (64, 64)),
            "down": pygame.transform.scale(pygame.image.load("img/soldier.png"), (64, 64)),
            "left": pygame.transform.scale(pygame.image.load("img/soldier_left.png"), (64, 64)),
            "right": pygame.transform.scale(pygame.image.load("img/soldier_right.png"), (64, 64)),
        }

        self.weapon_sprites = {
            "up": pygame.transform.scale(pygame.image.load("img/soldier_left_gun.png").convert_alpha(), (64, 64)),
            "down": pygame.transform.scale(pygame.image.load("img/soldier_down_gun.png").convert_alpha(), (64, 64)),
            "left": pygame.transform.scale(pygame.image.load("img/soldier_left_gun.png").convert_alpha(), (64, 64)),
            "right": pygame.transform.scale(pygame.image.load("img/soldier_right_gun.png").convert_alpha(), (64, 64)),
        }

        self.auto_walk = False
        self.wander_direction = "down"
        self.wander_timer = 0

        self.inventory = []  # כאן נשמור את כל הנשקים שהשחקן אוסף
        self.selected_slot = 0  # איזה סלוט מחובר כרגע (אם רוצים לירות ממנו)

    def pick_item(self, item):
        self.inventory.append(item)
        print(f"Picked up {item.name}")

    def has_weapon_equipped(self):
        if 0 <= self.selected_slot < len(self.inventory):
            return self.inventory[self.selected_slot].type == "weapon"
        return False

    def pick_random_direction(self):
        self.wander_direction = random.choice(["up", "down", "left", "right"])
        self.direction = self.wander_direction
        self.wander_timer = random.randint(20, 60)

    def drop_selected_weapon(self):
        if 0 <= self.selected_slot < len(self.inventory):
            weapon = self.inventory.pop(self.selected_slot)
            # אם נשארו פחות נשקים, מתקן את selected_slot
            if self.selected_slot >= len(self.inventory):
                self.selected_slot = max(len(self.inventory) - 1, 0)
            return weapon
        return None

    def move(self, keys, game_map, tile_size):
        moved = False

        # --- Manual movement ---
        if keys[pygame.K_w]:
            if not collides_with_wall(game_map, self.x, self.y - self.speed, self.size, tile_size):
                self.y -= self.speed
            self.direction = "up"
            moved = True

        if keys[pygame.K_s]:
            if not collides_with_wall(game_map, self.x, self.y + self.speed, self.size, tile_size):
                self.y += self.speed
            self.direction = "down"
            moved = True

        if keys[pygame.K_a]:
            if not collides_with_wall(game_map, self.x - self.speed, self.y, self.size, tile_size):
                self.x -= self.speed
            self.direction = "left"
            moved = True

        if keys[pygame.K_d]:
            if not collides_with_wall(game_map, self.x + self.speed, self.y, self.size, tile_size):
                self.x += self.speed
            self.direction = "right"
            moved = True

        if moved:
            outgoing_messages.put(f"UPDATE|{self.x},{self.y}")
        # --- Auto-walk wandering ---
        if self.auto_walk and not moved:
            outgoing_messages.put(f"UPDATE|{self.x},{self.y}")
            if self.wander_timer <= 0:
                self.pick_random_direction()

            self.wander_timer -= 1

            dx = 0
            dy = 0

            if self.wander_direction == "up":
                dy = -self.speed
            elif self.wander_direction == "down":
                dy = self.speed
            elif self.wander_direction == "left":
                dx = -self.speed
            elif self.wander_direction == "right":
                dx = self.speed

            if not collides_with_wall(game_map, self.x + dx, self.y + dy, self.size, tile_size):
                self.x += dx
                self.y += dy

    def draw(self, screen, camera_x, camera_y):
        if self.has_weapon_equipped():
            sprite = self.weapon_sprites[self.direction]
        else:
            sprite = self.base_sprites[self.direction]
        # Draw player sprite
        screen.blit(sprite, (self.x - camera_x, self.y - camera_y))

        # --- HEALTH BAR ---
        bar_width = 100
        bar_height = 5
        bar_x = self.x - camera_x + (self.size // 2) - (bar_width // 2)
        bar_y = self.y - camera_y - 10  # 10px above the player

        for i in range(bar_width):
            color = (0, 255, 0) if i < self.hp else (255, 0, 0)
            pygame.draw.line(screen, color, (bar_x + i, bar_y), (bar_x + i, bar_y + bar_height))


class RemotePlayer:
    def __init__(self, x, y, hp, sprites):
        self.x = x
        self.y = y
        self.hp = hp
        self.old_x = x
        self.old_y = y
        self.direction = "down"
        self.sprites = sprites
        self.size = 64

    def update_from_server(self, x, y, hp):
        self.old_x = self.x
        self.old_y = self.y
        self.x = x
        self.y = y
        self.hp = hp

        dx = self.x - self.old_x
        dy = self.y - self.old_y

        if abs(dx) > abs(dy):
            self.direction = "right" if dx > 0 else "left"
        else:
            self.direction = "down" if dy > 0 else "up"

    def draw(self, screen, camera_x, camera_y):
        screen.blit(self.sprites[self.direction], (self.x - camera_x, self.y - camera_y))

        bar_width = 100
        bar_height = 5
        bar_x = self.x - camera_x + (self.size // 2) - (bar_width // 2)
        bar_y = self.y - camera_y - 10

        for i in range(bar_width):
            color = (0, 255, 0) if i < self.hp else (255, 0, 0)
            pygame.draw.line(screen, color, (bar_x + i, bar_y), (bar_x + i, bar_y + bar_height))
def draw_chat(screen, chat_font, chat_messages, chat_open, chat_input):
    screen_h = screen.get_height()
    now = time.time()
    visible = []
    for msg_text, msg_time in chat_messages[-CHAT_MAX_MESSAGES:]:
        age = now - msg_time
        if chat_open or age < CHAT_FADE_SECONDS:
            fade_start = CHAT_FADE_SECONDS * 0.75
            alpha = 255 if (chat_open or age < fade_start) else int(255 * (1.0 - (age - fade_start) / (CHAT_FADE_SECONDS - fade_start)))
            visible.append((msg_text, alpha))

    input_box_h = CHAT_MSG_HEIGHT + CHAT_PADDING * 2
    base_y = screen_h - CHAT_Y_BOTTOM_OFFSET - (input_box_h if chat_open else 0)

    for i, (msg_text, alpha) in enumerate(reversed(visible)):
        rendered = chat_font.render(msg_text, True, CHAT_TEXT_COLOR)
        row_y = base_y - (i + 1) * CHAT_MSG_HEIGHT - CHAT_PADDING
        bg_surf = pygame.Surface((rendered.get_width() + CHAT_PADDING * 2, rendered.get_height() + 4), pygame.SRCALPHA)
        bg_surf.fill((0, 0, 0, min(alpha // 2, 120)))
        screen.blit(bg_surf, (CHAT_X, row_y - 2))
        faded = rendered.copy()
        faded.set_alpha(alpha)
        screen.blit(faded, (CHAT_X + CHAT_PADDING, row_y))

    if chat_open:
        input_y = base_y
        input_w = 400
        input_box_h = CHAT_MSG_HEIGHT + CHAT_PADDING * 2
        bg_surf = pygame.Surface((input_w, input_box_h), pygame.SRCALPHA)
        bg_surf.fill((0, 0, 0, 160))
        screen.blit(bg_surf, (CHAT_X, input_y))
        pygame.draw.rect(screen, (180, 180, 180), (CHAT_X, input_y, input_w, input_box_h), 1)
        cursor = "|" if int(time.time() * 2) % 2 == 0 else " "
        screen.blit(chat_font.render(chat_input + cursor, True, CHAT_TEXT_COLOR), (CHAT_X + CHAT_PADDING, input_y + CHAT_PADDING))


def draw_fps(screen, clock, font):
    """
    מציירת מדד FPS מעוצב בפינה העליונה.
    """
    # שליפת ה-FPS הנוכחי מהשעון של Pygame
    fps_val = int(clock.get_fps())
    fps_text = f"FPS: {fps_val}"

    # יצירת המשטח של הטקסט
    # צבע ירוק אם ה-FPS גבוה, אדום אם הוא נמוך מ-30
    color = (0, 255, 0) if fps_val > 30 else (255, 50, 50)
    fps_surface = font.render(fps_text, True, color)

    # הגדרת מיקום וגודל הרקע (Rect)
    padding = 10
    rect_width = fps_surface.get_width() + (padding * 2)
    rect_height = fps_surface.get_height() + (padding)
    fps_rect = pygame.Rect(10, 10, rect_width, rect_height)

    # ציור רקע שחור חצי שקוף
    bg_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
    bg_surface.fill((0, 0, 0, 150))  # 150 זה רמת השקיפות
    screen.blit(bg_surface, (10, 10))

    # ציור מסגרת דקה סביב המדד
    pygame.draw.rect(screen, (100, 100, 100), fps_rect, 1)

    # ציור הטקסט עצמו
    screen.blit(fps_surface, (10 + padding, 10 + padding // 2))
# ---------------- MAIN GAME LOOP ---------------- #

def main():
    global MY_ID
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    pygame.display.set_caption("Game")
    clock = pygame.time.Clock()

    tile_size = 64
    floor_img = pygame.image.load("img/DesertTile.png").convert()
    wall_img = pygame.image.load("img/watertile.png").convert()

    bullet_img = pygame.image.load("img/bullet.png").convert()


    floor_img = pygame.transform.scale(floor_img, (tile_size, tile_size))
    wall_img = pygame.transform.scale(wall_img, (tile_size, tile_size))
    bullet_img = pygame.transform.scale(bullet_img, (10.7 ,5.4))
    game_map = load_map("map.txt")

    player = Player(128, 128)
    chat_font = pygame.font.SysFont("monospace", CHAT_FONT_SIZE)
    chat_open = False
    chat_input = ""
    chat_messages = []
    start_quic_thread()
    outgoing_messages.put(f"Connected|{player.x},{player.y}|{player.hp}")
    outgoing_messages.put(f"UPDATE|{player.x},{player.y}")

    # --- LOAD LOOT IMAGES ---
    gun1_img = pygame.transform.scale(
        pygame.image.load("img/rightWeapon1.png").convert_alpha(), (64, 64)
    )
    gun2_img = pygame.transform.scale(
        pygame.image.load("img/rightWeapon2.png").convert_alpha(), (64, 64)
    )
    remote_players = {}
    # Loot pool (מאגר פריטים)
    loot_pool = [
        ("weapon", "gun", gun1_img),
        ("weapon", "shotGun", gun2_img),
    ]

    # loot_items = spawn_loot_per_camera_zone(game_map, tile_size, loot_pool, screen.get_width(), screen.get_height(),per_zone=1)
    loot_items = []
    # print("Loot spawned:", len(loot_items))
    # print("First loot at:", loot_items[0].x, loot_items[0].y)
    bullets = []

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                outgoing_messages.put(f"Disconnected")
                running = False

            if event.type == pygame.KEYDOWN:
                if chat_open:
                    if event.key == pygame.K_RETURN:
                        if chat_input.strip():
                            outgoing_messages.put(f"CHAT|{chat_input.strip()}")
                        chat_input = ""
                        chat_open = False
                    elif event.key == pygame.K_ESCAPE:
                        chat_input = ""
                        chat_open = False
                    elif event.key == pygame.K_BACKSPACE:
                        chat_input = chat_input[:-1]
                    elif len(chat_input) < CHAT_INPUT_MAX_LEN and event.unicode.isprintable():
                        chat_input += event.unicode
                    continue  # block all other keys while typing

                if event.key == pygame.K_t:
                    chat_open = True
                    chat_input = ""


                if event.key == pygame.K_n:
                    player.auto_walk = not player.auto_walk
                    print("Auto-walk:", player.auto_walk)

                if event.key == pygame.K_e and len(player.inventory) < 5:
                    nearby = get_nearby_item(player, loot_items)
                    if nearby:
                        player.pick_item(nearby)  # מוסיף ל־Inventory
                        loot_items.remove(nearby)
                        outgoing_messages.put(f"PICKUP|{nearby.x},{nearby.y}|{nearby.name}")
                if event.key == pygame.K_q:
                    gun_slot = player.drop_selected_weapon()
                    if gun_slot:
                        gun_slot.x=player.x
                        gun_slot.y=player.y
                        loot_items.append(gun_slot)
                        print(f"Dropped {gun_slot.name}")

                elif event.key == pygame.K_1:
                    if len(player.inventory) >= 1:
                        player.selected_slot = 0
                elif event.key == pygame.K_2:
                    if len(player.inventory) >= 2:
                        player.selected_slot = 1
                elif event.key == pygame.K_3:
                    if len(player.inventory) >= 3:
                        player.selected_slot = 2
                elif event.key == pygame.K_4:
                    if len(player.inventory) >= 4:
                        player.selected_slot = 3
                elif event.key == pygame.K_5:
                    if len(player.inventory) >= 5:
                        player.selected_slot = 4



            elif event.type == pygame.MOUSEBUTTONDOWN:

                if event.button == 1:  # Left mouse button

                    current_camera_x = player.x - screen.get_width() // 2
                    current_camera_y = player.y - screen.get_height() // 2

                    mouse_x, mouse_y = pygame.mouse.get_pos()

                    world_mouse_x = mouse_x + current_camera_x
                    world_mouse_y = mouse_y + current_camera_y

                    player_center_x = player.x + (player.size // 2)
                    player_center_y = player.y + (player.size // 2)

                    dx = world_mouse_x - player_center_x
                    dy = world_mouse_y - player_center_y


                    angle_radians = math.atan2(dy, dx)

                    angle_degrees = math.degrees(angle_radians)

                    outgoing_messages.put(f"ATTACK|{player.selected_slot}|{angle_degrees}")



        if not chat_open:
            keys = pygame.key.get_pressed()
            player.move(keys, game_map, tile_size)

        while not incoming_messages.empty():
            msg = incoming_messages.get()
            print(msg)
            parts = msg.split("|")
            if not parts:
                continue

            if parts[0] == "UPDATE":
                if len(parts) < 4:
                    continue
                player_id = parts[1]
                x, y = map(float, parts[2].split(","))
                hp = int(parts[3])

                if player_id not in remote_players:
                    remote_players[player_id] = RemotePlayer(x, y, hp, player.base_sprites)
                    outgoing_messages.put(f"UPDATE|{player.x},{player.y}")
                else:
                    remote_players[player_id].update_from_server(x, y, hp)

            elif parts[0] == "REMOVE":
                if len(parts) < 2:
                    continue
                player_id = parts[1]
                if player_id in remote_players:
                    del remote_players[player_id]
                    if player_id == MY_ID:
                        pygame.quit();exit()
                else:
                    if player_id == MY_ID:
                        pygame.quit();exit()

            elif parts[0] == "SHOWBULLET":
                bullets.append({"pos": parts[1], "time": time.time()})

            elif parts[0] == "DROPPED":
                if len(parts) < 3:
                    continue
                x_dropped, y_dropped = parts[1].split(",")
                x_dropped = float(x_dropped)
                y_dropped = float(y_dropped)
                type_dropped = parts[2]
                if type_dropped == "rifle":
                    img = pygame.image.load("img/leftWeapon1.png")
                    img = pygame.transform.scale(img, (64, 64))
                elif type_dropped == "gun":
                    img = pygame.image.load("img/rightWeapon1.png")
                    img = pygame.transform.scale(img, (64, 64))
                else:
                    continue
                loot_items.append(Item(x_dropped,y_dropped,img,"weapon",type_dropped))
            elif parts[0] == "UNDROPPED":
                if len(parts) < 3:
                    continue
                x_pick, y_pick = parts[1].split(",")
                x_pick = float(x_pick)
                y_pick = float(y_pick)
                type_pick = parts[2]

                for item in loot_items:
                    if item.x==x_pick and item.y == y_pick and item.name == type_pick:
                        loot_items.remove(item)
                        break

            elif parts[0] == "CHAT":
                if len(parts) < 3:
                    continue
                sender_id = parts[1]
                short_id = sender_id[-6:] if len(sender_id) >= 6 else sender_id
                display_name = "You" if sender_id == MY_ID else short_id
                chat_messages.append((f"<{display_name}> {parts[2]}", time.time()))

            elif parts[0] == "SETID":
                if MY_ID == "":
                    MY_ID = parts[1]



        # --- CAMERA FOLLOWS PLAYER ---
        camera_x = player.x - screen.get_width() // 2
        camera_y = player.y - screen.get_height() // 2

        screen.fill((30, 30, 30))

        draw_map(screen, game_map, tile_size, camera_x, camera_y,floor_img, wall_img)
        # ציור הלוט
        for item in loot_items:
            item.update()
            item.draw(screen, camera_x, camera_y)
        player.draw(screen, camera_x, camera_y)
        for rp in remote_players.values():
            rp.draw(screen, camera_x, camera_y)

        current_time = time.time()
        alive_bullets = []  # רשימה שתשמור רק קליעים שעוד לא נעלמו

        for b in bullets:
            # בודקים אם עברו פחות מ-0.2 שניות
            if current_time - b["time"] < 0.008:
                alive_bullets.append(b)  # שומרים את הקליע
                try:
                    bx, by = map(float, b["pos"].split(","))
                    screen.blit(bullet_img, (bx - camera_x, by - camera_y))
                except Exception as e:
                    pass

        # מעדכנים את הרשימה הראשית שתכיל רק את הקליעים ששרדו
        bullets = alive_bullets

        draw_fps(screen, clock, chat_font)
        draw_inventory(screen, player)
        draw_chat(screen, chat_font, chat_messages, chat_open, chat_input)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

main()