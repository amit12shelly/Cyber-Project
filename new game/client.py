import pygame
import random
import threading
import asyncio
import queue
import math
from queue import Queue
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration
import client_test


SERVER_IP = "127.0.0.1"
SERVER_PORT = 4433
TOLERANCE = 5
UP_HP = 40
MY_ID = ""
incoming_messages = Queue()
#outgoing_messages defined with BroadcastQueue
import time

WEAPON_AMMO = {"gun": 30, "rifle": 20, "rpg": 5}  # must match server

CHAT_MAX_MESSAGES = 10
CHAT_FADE_SECONDS = 8
CHAT_INPUT_MAX_LEN = 100
CHAT_TEXT_COLOR = (255, 255, 255)
CHAT_FONT_SIZE = 18
CHAT_PADDING = 6
CHAT_MSG_HEIGHT = 22
CHAT_X = 10
CHAT_Y_BOTTOM_OFFSET = 120
servers = []




async def quic_network_loop(ip, port):
    config = QuicConfiguration(
        is_client=True,
        alpn_protocols=["echo-protocol"],
        verify_mode=False
    )

    outgoing_messages.add_server(ip, port)

    try:
        async with connect(ip, port, configuration=config) as client:
            stream_reader, stream_writer = await client.create_stream()
            print(f"Connected to Game Server at {ip}:{port}!")

            connection_alive = True

            async def read_from_server():
                nonlocal connection_alive
                buffer = ""
                try:
                    while connection_alive:
                        data = await stream_reader.read(4096)
                        if not data:
                            break  # השרת ניתק אותנו - יוצאים מהלולאה במקום continue

                        buffer += data.decode()
                        while "\n" in buffer:
                            msg, buffer = buffer.split("\n", 1)
                            msg = msg.strip()
                            if msg:
                                incoming_messages.put((ip, port, msg))
                except Exception:
                    pass
                finally:
                    connection_alive = False

            async def write_to_server():
                nonlocal connection_alive
                while connection_alive:
                    try:
                        msg = outgoing_messages.get_nowait(ip, port)
                        stream_writer.write((msg + "\n").encode())
                        await stream_writer.drain()
                    except queue.Empty:
                        await asyncio.sleep(0.01)
                    except Exception:
                        break  # השרת ניתק אותנו ושגיאת כתיבה קפצה - יוצאים מהלולאה
                connection_alive = False

            await asyncio.gather(read_from_server(), write_to_server())
    except Exception as e:
        print(f"Quic connection error ({ip}:{port}):", e)
    finally:
        outgoing_messages.remove_server(ip, port)
        incoming_messages.put((ip, port, "INTERNAL_SERVER_DISCONNECT"))

def start_quic_thread(ip, port):
    loop = asyncio.new_event_loop()

    def runner(target_ip, target_port):
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(quic_network_loop(ip, port))
        except Exception as e:
            print("NETWORK THREAD ERROR:", e)

    threading.Thread(target=runner, args=(ip, port), daemon=True).start()
class BroadcastQueue:
    def __init__(self):
        self.queues = {}

    def add_server(self, ip, port):
        if (ip, port) not in self.queues:
            self.queues[(ip, port)] = queue.Queue()

    def remove_server(self, ip, port):
        if (ip, port) in self.queues:
            del self.queues[(ip, port)]

    def put(self, msg):
        """שולח את ההודעה לכל השרתים המחוברים"""
        for q in self.queues.values():
            q.put(msg)

    def put_to_specific(self, ip, port, msg):
        """שולח הודעה רק לשרת אחד ספציפי"""
        if (ip, port) in self.queues:
            self.queues[(ip, port)].put(msg)

    def get_nowait(self, ip, port):
        """שולף הודעה ששייכת לשרת ספציפי"""
        if (ip, port) in self.queues:
            return self.queues[(ip, port)].get_nowait()
        raise queue.Empty
outgoing_messages = BroadcastQueue()
# ---------------- MAP FUNCTIONS ---------------- #
def load_map(filename):
    with open(filename, "r") as f:
        lines = f.readlines()
    return [list(line.strip()) for line in lines]

def draw_shield(screen, shield_center):
    x, y = shield_center

    shield_surface = pygame.Surface((140, 140), pygame.SRCALPHA)
    center = (70, 70)

    pygame.draw.circle(shield_surface, (78, 149, 217, 40), center, 48, 6)

    pygame.draw.circle(shield_surface, (78, 149, 217, 100), center, 42, 4)

    pygame.draw.circle(shield_surface, (150, 220, 255, 160), center, 38, 2)

    pygame.draw.circle(shield_surface, (200, 240, 255, 120), center, 30, 1)

    screen.blit(shield_surface, (x - 70, y - 70))

def draw_potion_slot(screen, potions):
    radius = 30
    y = screen.get_height() - 64 - 20 + 32
    x = 60
    pygame.draw.circle(screen, (50, 50, 50), (x, y), radius)
    pygame.draw.circle(screen, (255, 255, 0), (x, y), radius, 3)
    if len(potions) > 0:
        item = potions[0]
        img = pygame.transform.scale(item.image, (radius * 2 - 12, radius * 2 - 12))
        rect = img.get_rect(center=(x, y))
        screen.blit(img, rect)

def draw_map(screen, game_map, tile_size, camera_x, camera_y, floor_img, wall_img):
    start_tile_x = max(camera_x // tile_size, 0)
    start_tile_y = max(camera_y // tile_size, 0)
    end_tile_x = min((camera_x + screen.get_width()) // tile_size + 1, len(game_map[0]))
    end_tile_y = min((camera_y + screen.get_height()) // tile_size + 1, len(game_map))
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

def collides_with_wall(game_map, x, y, size, tile_size):
    corners = [
        (x, y),
        (x + size - 1, y),
        (x, y + size - 1),
        (x + size - 1, y + size - 1)
    ]
    for cx, cy in corners:
        tile_x = cx // tile_size
        tile_y = cy // tile_size
        if is_wall(game_map, tile_x, tile_y):
            return True
    return False

def draw_big_inventory(screen, player, potions, font):
    width = 800
    height = 500
    x = (screen.get_width() - width) // 2
    y = (screen.get_height() - height) // 2

    panel = pygame.Surface((width, height), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 200))
    screen.blit(panel, (x, y))
    pygame.draw.rect(screen, (150, 150, 150), (x, y, width, height), 2)

    # PLAYER
    title = font.render("PLAYER", True, (255, 255, 255))
    screen.blit(title, (x + 20, y + 20))
    sprite_size = 120
    if player.has_weapon_equipped():
        sprite = player.weapon_sprites[player.direction][player.anim_frame]
    else:
        sprite = player.base_sprites[player.direction][player.anim_frame]
    sprite = pygame.transform.scale(sprite, (sprite_size, sprite_size))
    screen.blit(sprite, (x + 20, y + 60))

    # HP
    bar_width = 200
    hp_ratio = player.hp / 100
    hp_x = x + 180
    hp_y = y + 90
    pygame.draw.rect(screen, (100, 0, 0), (hp_x, hp_y, bar_width, 20))
    pygame.draw.rect(screen, (0, 255, 0), (hp_x, hp_y, int(bar_width * hp_ratio), 20))
    hp_text = font.render(f"HP {player.hp}/100", True, (255, 255, 255))
    screen.blit(hp_text, (hp_x, hp_y - 25))

    # WEAPONS
    title = font.render("WEAPONS", True, (255, 255, 255))
    screen.blit(title, (x + 20, y + 220))
    slot_size = 70
    for i in range(5):
        slot_x = x + 20 + i * (slot_size + 10)
        slot_y = y + 260
        pygame.draw.rect(screen, (60, 60, 60), (slot_x, slot_y, slot_size, slot_size))
        if i < len(player.inventory):
            weapon = player.inventory[i]
            img = pygame.transform.scale(weapon.image, (slot_size, slot_size))
            screen.blit(img, (slot_x, slot_y))
            if weapon.ammo is not None:
                color = (255, 80, 80) if weapon.ammo <= 5 else (255, 255, 255)
                ammo_surf = font.render(str(weapon.ammo), True, color)
                screen.blit(ammo_surf, (slot_x + slot_size - ammo_surf.get_width() - 4,
                                        slot_y + slot_size - ammo_surf.get_height() - 2))
        if i == player.selected_slot:
            pygame.draw.rect(screen, (255, 255, 0), (slot_x, slot_y, slot_size, slot_size), 3)

    # ITEMS
    title = font.render("ITEMS", True, (255, 255, 255))
    screen.blit(title, (x + 20, y + 360))
    item_size = 60
    max_slots = 6
    for i in range(max_slots):
        draw_x = x + 20 + i * (item_size + 10)
        draw_y = y + 400
        pygame.draw.rect(screen, (60, 60, 60), (draw_x, draw_y, item_size, item_size))
        if i < len(potions):
            item = potions[i]
            img = pygame.transform.scale(item.image, (item_size, item_size))
            screen.blit(img, (draw_x, draw_y))

def draw_inventory(screen, player, font):
    slot_size = 64
    padding = 10
    start_x = (screen.get_width() - (slot_size + padding) * 5) // 2
    y = screen.get_height() - slot_size - 20

    for i in range(5):
        x = start_x + i * (slot_size + padding)
        pygame.draw.rect(screen, (50, 50, 50), (x, y, slot_size, slot_size))
        pygame.draw.rect(screen, (200, 200, 200), (x + 2, y + 2, slot_size - 4, slot_size - 4), 2)

        if i < len(player.inventory):
            weapon = player.inventory[i]
            screen.blit(weapon.image, (x, y))
            if weapon.ammo is not None:
                color = (255, 80, 80) if weapon.ammo <= 5 else (255, 255, 255)
                ammo_surf = font.render(str(weapon.ammo), True, color)
                screen.blit(ammo_surf, (x + slot_size - ammo_surf.get_width() - 4,
                                        y + slot_size - ammo_surf.get_height() - 2))

        if i == player.selected_slot:
            pygame.draw.rect(screen, (255, 255, 0), (x, y, slot_size, slot_size), 3)

def get_nearby_item(player, loot_items, radius=70):
    for item in loot_items:
        dx = (player.x + player.size // 2) - (item.x + item.size // 2)
        dy = (player.y + player.size // 2) - (item.y + item.size // 2)
        distance = (dx ** 2 + dy ** 2) ** 0.5
        if distance <= radius:
            return item
    return None
# ---------------- ExplosionEffect CLASS ---------------- #
class ExplosionEffect:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.particles = []
        self.smoke = []
        self.flash = 10  # הבזק בהתחלה

        # חלקיקי אש מהירים
        for _ in range(150):
            angle = random.uniform(0, math.pi * 2)
            speed = random.uniform(4, 12)

            self.particles.append({
                "x": x,
                "y": y,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "size": random.randint(6, 16),
                "life": random.randint(25, 45),
                "color": random.choice([
                    (255,120,0),
                    (255,200,0),
                    (255,60,0)
                ])
            })

        # עשן שמתפזר לאט
        for _ in range(60):
            angle = random.uniform(0, math.pi * 2)
            speed = random.uniform(1, 4)

            self.smoke.append({
                "x": x,
                "y": y,
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "size": random.randint(10, 25),
                "life": random.randint(40, 80)
            })

    def update(self):

        # חלקיקי אש
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]

            p["vx"] *= 0.97
            p["vy"] *= 0.97

            p["vy"] += 0.08
            p["size"] *= 0.95
            p["life"] -= 1

        # עשן
        for s in self.smoke:
            s["x"] += s["vx"]
            s["y"] += s["vy"]

            s["vx"] *= 0.96
            s["vy"] *= 0.96

            s["size"] += 0.25
            s["life"] -= 1

        self.particles = [p for p in self.particles if p["life"] > 0]
        self.smoke = [s for s in self.smoke if s["life"] > 0]

        if self.flash > 0:
            self.flash -= 1

    def draw(self, screen, camera_x, camera_y):

        # FLASH לבן בתחילת הפיצוץ
        if self.flash > 0:
            radius = 80 - self.flash * 6
            pygame.draw.circle(
                screen,
                (255,255,255),
                (int(self.x - camera_x), int(self.y - camera_y)),
                max(10, radius)
            )
        # חלקיקי אש
        for p in self.particles:
            alpha = int(255 * (p["life"] / 45))

            surf = pygame.Surface((int(p["size"] * 2) + 2, int(p["size"] * 2) + 2), pygame.SRCALPHA)

            pygame.draw.circle(
                surf,
                (*p["color"], alpha),
                (int(p["size"]), int(p["size"])),
                max(1, int(p["size"]))
            )

            screen.blit(
                surf,
                (p["x"] - camera_x - p["size"], p["y"] - camera_y - p["size"])
            )

        # עשן
        for s in self.smoke:
            alpha = int(120 * (s["life"] / 80))

            surf = pygame.Surface((int(s["size"] * 2), int(s["size"] * 2)), pygame.SRCALPHA)

            pygame.draw.circle(
                surf,
                (90, 90, 90, alpha),
                (int(s["size"]), int(s["size"])),
                int(s["size"])
            )

            screen.blit(
                surf,
                (s["x"] - camera_x - s["size"], s["y"] - camera_y - s["size"])
            )


# -----------------SERVER CLASS-----------------#
class Server:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port


# ---------------- PoisonEffect CLASS ---------------- #
class PoisonEffect:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.particles = []
        for _ in range(120):
            angle = random.uniform(0, math.pi * 2)
            dist = random.uniform(0, 10)
            self.particles.append({
                "x": x + math.cos(angle) * dist,
                "y": y + math.sin(angle) * dist,
                "vx": random.uniform(-0.6, 0.6),
                "vy": random.uniform(-0.8, -0.2),
                "size": random.randint(10, 24),
                "life": random.randint(70, 110)
            })

    def update(self):
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vx"] *= 0.98
            p["vy"] *= 0.98
            p["size"] += 0.15
            p["life"] -= 1
        self.particles = [p for p in self.particles if p["life"] > 0]

    def draw(self, screen, camera_x, camera_y):
        for p in self.particles:
            alpha = int(180 * (p["life"] / 110))
            surf = pygame.Surface((int(p["size"] * 2), int(p["size"] * 2)), pygame.SRCALPHA)
            pygame.draw.circle(surf, (140, 0, 190, alpha),
                               (int(p["size"]), int(p["size"])), int(p["size"]))
            screen.blit(surf, (p["x"] - camera_x - p["size"], p["y"] - camera_y - p["size"]))

# ---------------- Item CLASS ---------------- #
class Item:
    def __init__(self, x, y, image, item_type, name, ammo=None):
        self.x = x
        self.y = y
        self.image = image
        self.type = item_type  # "weapon" / "item"
        self.name = name
        self.size = 64
        self.rect = pygame.Rect(x, y, self.size, self.size)
        self.ammo = ammo  # display only — authoritative value comes from server

    def update(self):
        self.rect.topleft = (self.x, self.y)

    def draw(self, screen, camera_x, camera_y):
        draw_x = self.x - camera_x
        draw_y = self.y - camera_y
        if -self.size <= draw_x <= screen.get_width() and -self.size <= draw_y <= screen.get_height():
            screen.blit(self.image, (draw_x, draw_y))

# ---------------- Potion CLASS ---------------- #
class Potion:
    def __init__(self, x, y, image, name):
        self.image = image
        self.x = x
        self.y = y
        self.size = 64
        self.name = name

    def draw(self, screen, camera_x, camera_y):
        draw_x = self.x - camera_x
        draw_y = self.y - camera_y
        if -self.size <= draw_x <= screen.get_width() and -self.size <= draw_y <= screen.get_height():
            screen.blit(self.image, (draw_x, draw_y))

# ---------------- Monster CLASS ---------------- #
class Monster:
    def __init__(self, x, y, hp, image):
        self.x = x
        self.y = y
        self.hp = hp
        self.image = image
        self.size = 64
        self.rect = pygame.Rect(x, y, self.size, self.size)

    def update(self):
        self.rect.topleft = (self.x, self.y)

    def draw(self, screen, camera_x, camera_y):
        draw_x = self.rect.x - camera_x
        draw_y = self.rect.y - camera_y
        screen.blit(self.image, (draw_x, draw_y))
        if -self.size <= draw_x <= screen.get_width() and -self.size <= draw_y <= screen.get_height():
            bar_width = 100
            bar_height = 5
            bar_x = draw_x + (self.size // 2) - (bar_width // 2)
            bar_y = draw_y - 10
            pygame.draw.rect(screen, (255, 0, 0), (bar_x, bar_y, bar_width, bar_height))
            if self.hp > 0:
                current_hp_width = min(self.hp, bar_width)
                pygame.draw.rect(screen, (0, 255, 0), (bar_x, bar_y, current_hp_width, bar_height))

#----------------- SKILL CLASS  ---------------#
class Skill:
    def __init__(self, name, duration_time, last_action_time, is_active):
        self.name = name
        self.duration_time = duration_time
        self.last_action_time = last_action_time
        self.is_active = is_active

# ---------------- PLAYER CLASS ---------------- #
class Player:
    def __init__(self, x, y, skill):
        self.x = x
        self.y = y
        self.hp = 100
        self.speed = 4
        self.direction = "up"
        self.size = 64

        # Animation state
        self.anim_frame = 0
        self.anim_timer = 0
        self.anim_speed = 8
        self.is_moving = False

        # Base sprites: 2 frames per direction, left is mirrored right
        right_0 = pygame.transform.scale(pygame.image.load("img/right_1.png"), (64, 64))
        right_1 = pygame.transform.scale(pygame.image.load("img/right_2.png"), (64, 64))
        left_0  = pygame.transform.flip(right_0, True, False)
        left_1  = pygame.transform.flip(right_1, True, False)
        self.base_sprites = {
            "up":    [
                pygame.transform.scale(pygame.image.load("img/1.png"), (64, 64)),
                pygame.transform.scale(pygame.image.load("img/2.png"), (64, 64)),
            ],
            "down":  [
                pygame.transform.scale(pygame.image.load("img/down_1.png"), (64, 64)),
                pygame.transform.scale(pygame.image.load("img/down_2.png"), (64, 64)),
            ],
            "left":  [left_0, left_1],
            "right": [right_0, right_1],
        }

        # Weapon sprites: 2 frames per direction, left is mirrored right
        w_right_0 = pygame.transform.scale(pygame.image.load("img/soldier_right_gun.png").convert_alpha(), (64, 64))
        w_right_1 = pygame.transform.scale(pygame.image.load("img/soldier_right_gun.png").convert_alpha(), (64, 64))
        w_left_0  = pygame.transform.flip(w_right_0, True, False)
        w_left_1  = pygame.transform.flip(w_right_1, True, False)

        self.weapon_sprites = {
            "up":    [
                pygame.transform.scale(pygame.image.load("img/soldier_left_gun.png").convert_alpha(), (64, 64)),
                pygame.transform.scale(pygame.image.load("img/soldier_left_gun.png").convert_alpha(), (64, 64)),
            ],
            "down":  [
                pygame.transform.scale(pygame.image.load("img/adown1.png").convert_alpha(), (64, 64)),
                pygame.transform.scale(pygame.image.load("img/adown2.png").convert_alpha(), (64, 64)),
            ],
            "left":  [w_left_0, w_left_1],
            "right": [w_right_0, w_right_1],
        }

        self.auto_walk = False
        self.wander_direction = "down"
        self.wander_timer = 0
        self.inventory = []
        self.selected_slot = 0

    def _update_animation(self):
        if self.is_moving:
            self.anim_timer += 1
            if self.anim_timer >= self.anim_speed:
                self.anim_timer = 0
                self.anim_frame = 1 - self.anim_frame
        else:
            self.anim_frame = 0
            self.anim_timer = 0
        # self.skill = skill
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
            if self.selected_slot >= len(self.inventory):
                self.selected_slot = max(len(self.inventory) - 1, 0)
            return weapon
        return None

    def move(self, keys, game_map, tile_size, skill):
        moved = False
        current_speed = self.speed * (2 if skill.name == "Speed Boost" and skill.is_active == True else 1)
        # --- Manual movement ---
        if keys[pygame.K_w]:
            if not collides_with_wall(game_map, self.x, self.y - current_speed, self.size, tile_size):
                self.y -= current_speed
            self.direction = "up"
            moved = True

        if keys[pygame.K_s]:
            if not collides_with_wall(game_map, self.x, self.y + current_speed, self.size, tile_size):
                self.y += current_speed
            self.direction = "down"
            moved = True

        if keys[pygame.K_a]:
            if not collides_with_wall(game_map, self.x - current_speed, self.y, self.size, tile_size):
                self.x -= current_speed
            self.direction = "left"
            moved = True

        if keys[pygame.K_d]:
            if not collides_with_wall(game_map, self.x + current_speed, self.y, self.size, tile_size):
                self.x += current_speed
            self.direction = "right"
            moved = True

        if moved:
            outgoing_messages.put(f"UPDATE|{self.x},{self.y}")

        if self.auto_walk and not moved:
            outgoing_messages.put(f"UPDATE|{self.x},{self.y}")

            if self.wander_timer <= 0:
                self.pick_random_direction()
            self.wander_timer -= 1
            dx, dy = 0, 0
            if self.wander_direction == "up":     dy = -self.speed
            elif self.wander_direction == "down":  dy =  self.speed
            elif self.wander_direction == "left":  dx = -self.speed
            elif self.wander_direction == "right": dx =  self.speed
            if not collides_with_wall(game_map, self.x + dx, self.y + dy, self.size, tile_size):
                self.x += dx
                self.y += dy
            moved = True

        self.is_moving = moved
        self._update_animation()

    def draw(self, screen, camera_x, camera_y, active_skills):
        if self.has_weapon_equipped():
            sprite = self.weapon_sprites[self.direction][self.anim_frame]
        else:
            sprite = self.base_sprites[self.direction][self.anim_frame]

        screen.blit(sprite, (self.x - camera_x, self.y - camera_y))
        try:
            if active_skills[MY_ID].name == "Shield":
                shield_center = (self.x - camera_x + 32, self.y - camera_y + 32)  # +32 to center on 64x64 sprite
                draw_shield(screen, shield_center)
        except:
            pass
        # --- HEALTH BAR ---
        hp_bar_width = 100
        hp_bar_height = 5
        hp_bar_x = self.x - camera_x + (self.size // 2) - (hp_bar_width // 2)
        hp_bar_y = self.y - camera_y - 10  # 10px above the player

        for i in range(hp_bar_width):
            color = (0, 255, 0) if i < self.hp else (255, 0, 0)
            pygame.draw.line(screen, color, (hp_bar_x + i, hp_bar_y), (hp_bar_x + i, hp_bar_y + hp_bar_height))



class RemotePlayer:
    def __init__(self, x, y, hp, sprites,weapon_sprites, id, bool):
        self.x = x
        self.y = y
        self.hp = hp
        self.old_x = x
        self.old_y = y
        self.id = id
        self.bool = bool
        self.direction = "down"
        self.weopons = weapon_sprites
        self.sprites = sprites
        self.size = 64

    def update_from_server(self, x, y, hp,has_weapon):
        self.old_x = self.x
        self.old_y = self.y
        self.x = x
        self.y = y
        self.hp = hp
        self.bool = has_weapon

        dx = self.x - self.old_x
        dy = self.y - self.old_y
        if abs(dx) > abs(dy):
            self.direction = "right" if dx > 0 else "left"
        else:
            self.direction = "down" if dy > 0 else "up"

    def draw(self, screen, camera_x, camera_y, active_skills):
        if self.bool:
            sprite = self.weopons[self.direction][0]  # פריים 0
        else:
            sprite = self.sprites[self.direction][0]  # פריים 0

        screen.blit(sprite, (self.x - camera_x, self.y - camera_y))

        try:
            if active_skills[self.id].name == "Shield":
                shield_center = (self.x - camera_x + 32, self.y - camera_y + 32)  # +32 to center on 64x64 sprite
                pygame.draw.circle(screen, (78, 149, 217), shield_center, 40, 3)
        except:
            pass
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
            alpha = 255 if (chat_open or age < fade_start) else int(
                255 * (1.0 - (age - fade_start) / (CHAT_FADE_SECONDS - fade_start)))
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
        screen.blit(chat_font.render(chat_input + cursor, True, CHAT_TEXT_COLOR),
                    (CHAT_X + CHAT_PADDING, input_y + CHAT_PADDING))

def draw_fps(screen, clock, font, server_fps):
    client_fps_val = int(clock.get_fps())
    client_color = (0, 255, 0) if client_fps_val > 30 else (255, 50, 50)
    client_surface = font.render(f"Client FPS: {client_fps_val}", True, client_color)

    try:
        server_fps_val = int(server_fps)
        server_color = (0, 255, 0) if server_fps_val > 30 else (255, 50, 50)
        server_text = f"Server TPS: {server_fps_val}"
    except (ValueError, TypeError):
        server_text = "Server TPS: ?"
        server_color = (255, 255, 255)

    server_surface = font.render(server_text, True, server_color)
    padding = 10
    max_text_width = max(client_surface.get_width(), server_surface.get_width())
    rect_width = max_text_width + (padding * 2)
    rect_height = client_surface.get_height() + server_surface.get_height() + (padding * 2)
    fps_rect = pygame.Rect(10, 10, rect_width, rect_height)
    bg_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
    bg_surface.fill((0, 0, 0, 150))
    screen.blit(bg_surface, (10, 10))
    pygame.draw.rect(screen, (100, 100, 100), fps_rect, 1)
    screen.blit(client_surface, (10 + padding, 10 + padding // 2))
    screen.blit(server_surface, (10 + padding, 10 + padding + client_surface.get_height()))

def draw_bullet(screen, bullet_img, x, y, angle, camera_x, camera_y,bullet_type="bullet"):
    draw_x = x - camera_x
    draw_y = y - camera_y

    if bullet_type == "bomb":
        # פצצה מסתובבת
        rotation_angle = (pygame.time.get_ticks() // 5) % 360
        rotated_bullet = pygame.transform.rotate(bullet_img, rotation_angle)
    else:
        rotated_bullet = pygame.transform.rotate(bullet_img, -angle)

    rect = rotated_bullet.get_rect(center=(draw_x, draw_y))
    screen.blit(rotated_bullet, rect)

def get_next_bullet_position(x, y, angle_degrees):
    angle_rad = math.radians(angle_degrees)
    return x + math.cos(angle_rad) * 15, y + math.sin(angle_rad) * 15
def draw_icons(screen, icons_lst, skill):
    current_time = pygame.time.get_ticks() / 1000

    elapsed = current_time - skill.last_action_time - (skill.duration_time if skill.is_active else 0)

    total_wait_required = (skill.duration_time if skill.last_action_time != 0 else 0) + SKILL_COOL_TIME

    padding_x = 8
    padding_y = 8
    x = screen.get_width() - padding_x*2
    y = screen.get_height() - padding_y
    icons_dict = {"Shield": 0, "Speed Boost": 1, "Bombs": 2}
    for i in range(len(icons_lst)):
        if(skill.is_active and icons_dict[skill.name] == i and skill.last_action_time != 0) or (elapsed >= total_wait_required):
            icons_lst[i].set_alpha(255)
        else:
            icons_lst[i].set_alpha(128)

        x -= icons_lst[i].get_width()
        screen.blit(icons_lst[i], (x, y - icons_lst[i].get_height()))
        x -= padding_x

    skill_bar_width = 2*(padding_x) + 3*(icons_lst[0].get_width())
    skill_bar_height = 5

    skill_bar_x = x + padding_x
    skill_bar_y = y - icons_lst[0].get_height() - 2 * padding_y

    if skill.is_active:
        skill_percent = round(
            (1 - (current_time - skill.last_action_time) / skill.duration_time) * skill_bar_width)
    else:
        if (skill.last_action_time == 0):
            skill_percent = round((current_time / SKILL_COOL_TIME) * skill_bar_width)
        else:
            skill_percent = round(((current_time - skill.last_action_time - skill.duration_time) / SKILL_COOL_TIME) * skill_bar_width)

    for i in range(skill_bar_width):
        color = (78, 149, 217) if i < skill_percent else (255, 255, 255)
        pygame.draw.line(screen, color, (skill_bar_x + i, skill_bar_y),
                         (skill_bar_x + i, skill_bar_y + skill_bar_height))


# ---------------- MAIN GAME LOOP ---------------- #

def draw_death_screen(screen, font_title, font_btn, mouse_pos):
    sw, sh = screen.get_width(), screen.get_height()

    # Same dim overlay used by draw_big_inventory
    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    screen.blit(overlay, (0, 0))

    # Central panel — same style as draw_big_inventory
    panel_w, panel_h = 500, 300
    px = (sw - panel_w) // 2
    py = (sh - panel_h) // 2

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 200))
    screen.blit(panel, (px, py))
    pygame.draw.rect(screen, (150, 150, 150), (px, py, panel_w, panel_h), 2)

    # Title — white, same font style as inventory labels
    title = font_title.render("YOU DIED", True, (255, 255, 255))
    screen.blit(title, title.get_rect(center=(sw // 2, py + 70)))

    # Subtitle in dimmed white
    sub_font = pygame.font.SysFont("arial", 18)
    sub = sub_font.render("Your items were dropped at your location.", True, (180, 180, 180))
    screen.blit(sub, sub.get_rect(center=(sw // 2, py + 130)))

    # Two buttons styled as inventory slots
    btn_w, btn_h = 160, 50
    gap = 20
    total = btn_w * 2 + gap
    b1x = sw // 2 - total // 2
    b2x = b1x + btn_w + gap
    by  = py + 200

    result = None
    for label, bx, key in [("RESPAWN", b1x, "respawn"), ("QUIT", b2x, "quit")]:
        r = pygame.Rect(bx, by, btn_w, btn_h)
        hovered = r.collidepoint(mouse_pos)

        # Slot fill — brighter on hover, matching (50,50,50) slot style
        fill = (80, 80, 80) if hovered else (50, 50, 50)
        pygame.draw.rect(screen, fill, r)
        # Inner border — same (200,200,200) as inventory slots; yellow on hover like selected slot
        border_color = (255, 255, 0) if hovered else (200, 200, 200)
        pygame.draw.rect(screen, border_color, (r.x + 2, r.y + 2, r.w - 4, r.h - 4), 2)

        lbl = font_btn.render(label, True, (255, 255, 255))
        screen.blit(lbl, lbl.get_rect(center=r.center))

        if hovered and pygame.mouse.get_pressed()[0]:
            result = key

    return result


def main():
    player_data = client_test.login_client()

    if player_data != None:
        gs_ip = player_data["gs_ip"]
        gs_port = player_data["gs_port"]
        servers.append(Server(gs_ip, gs_port))

        global MY_ID
        MY_ID = player_data.get("id", "")

        global SKILL_COOL_TIME
        SKILL_COOL_TIME = 12
        pygame.init()
        screen = pygame.display.set_mode((1280, 720))
        pygame.display.set_caption("Game")
        clock = pygame.time.Clock()

        tile_size = 64
        floor_img = pygame.image.load("img/DesertTile.png").convert()
        wall_img = pygame.image.load("img/watertile.png").convert()
        bomb_img = pygame.image.load("img/bomb.png").convert_alpha()
        bullet_img = pygame.image.load("img/bullet.png").convert_alpha()
        bomb_icon = pygame.image.load("img/bomb_icon.png").convert_alpha()
        speed_boost_icon = pygame.image.load("img/speed_boost_icon.png").convert_alpha()
        shield_icon = pygame.image.load("img/shield_icon.png").convert_alpha()

        inventory_open = False
        is_transferring = False
        ui_font = pygame.font.SysFont("arial", 22)

        floor_img = pygame.transform.scale(floor_img, (tile_size, tile_size))
        wall_img = pygame.transform.scale(wall_img, (tile_size, tile_size))
        bullet_img = pygame.transform.scale(bullet_img, (21, 11))
        bomb_img = pygame.transform.scale(bomb_img, (40, 40))
        bomb_icon = pygame.transform.smoothscale(bomb_icon, (64, 70))
        speed_boost_icon = pygame.transform.smoothscale(speed_boost_icon, (64, 70))
        shield_icon = pygame.transform.smoothscale(shield_icon, (64, 70))
        game_map = load_map("map.txt")

        skills_dict = {
            "Speed Boost": Skill("Speed Boost", 10, 0, False),
            "Shield": Skill("Shield", 6, 0, False),
            "Bombs": Skill("Bombs", 7, 0, False)
        }
        skill = skills_dict["Shield"]
        px = int(float(player_data.get("x", 128)))
        py = int(float(player_data.get("y", 128)))
        php = int(player_data.get("hp", 100))  # player hp
        player = Player(px, py, skill)
        player.hp = php
        shoot_direction_timer = 0
        shoot_direction = None
        player_name = player_data.get("username", "Unknown")

        chat_font = pygame.font.SysFont("monospace", CHAT_FONT_SIZE)
        chat_open = False
        chat_input = ""
        chat_messages = []
        is_dead = False
        respawn_sent = False
        death_font_title = pygame.font.SysFont("arial", 48, bold=True)
        death_font_btn = pygame.font.SysFont("arial", 22)
        start_quic_thread(servers[0].ip, servers[0].port)

        raw_inv = player_data.get("inventory", "Empty")

        weapon_images = {
            "rifle": pygame.transform.scale(pygame.image.load("img/leftWeapon1.png").convert_alpha(), (64, 64)),
            "gun": pygame.transform.scale(pygame.image.load("img/rightWeapon1.png").convert_alpha(), (64, 64)),
            "rpg": pygame.transform.scale(pygame.image.load("img/rpg_right.png").convert_alpha(), (64, 64))
        }
        monster_img = pygame.transform.scale(pygame.image.load("img/monster_down.png").convert_alpha(), (45, 45))
        potion_img = pygame.transform.scale(pygame.image.load("img/hp_Potion.png").convert_alpha(), (40, 40))
        poison_img = pygame.transform.scale(pygame.image.load("img/poison_item.png").convert_alpha(), (40, 40))
        remote_players = {}
        active_skills = {}
        # Loot pool (מאגר פריטים)

        # loot_items = spawn_loot_per_camera_zone(game_map, tile_size, loot_pool, screen.get_width(), screen.get_height(),per_zone=1)
        loot_items = []
        poison_effects = []
        monsters = []
        inventory = []  # הרשימה של השיקויים שלך (סלוטים 5-10)
        hp_items = []
        bullets = {}
        server_fps = 0

        # ==========================================
        # אתחול ציוד ושיקויים מתוך player_data
        # ==========================================
        # ==========================================
        # אתחול ציוד ושיקויים מתוך player_data
        # ==========================================
        # ==========================================
        # אתחול ציוד ושיקויים מתוך player_data
        # ==========================================
        if raw_inv and raw_inv != "Empty":
            items_list = raw_inv.split(";")

            temp_weapons = {}  # שומרים זמנית כדי לסדר לפי הסלוט

            for item_str in items_list:
                if not item_str:
                    continue

                slot_str, item_type, ammo_str = item_str.split(",")
                slot = int(slot_str)
                ammo = int(ammo_str)

                if 0 <= slot <= 4:
                    img_key = item_type.lower()
                    if img_key in weapon_images:
                        new_weapon = Item(player.x, player.y, weapon_images[img_key], "weapon", item_type)
                        new_weapon.ammo = ammo
                        temp_weapons[slot] = new_weapon  # שומרים לפי אינדקס
                    else:
                        print(f"[!] Warning: Unknown weapon '{item_type}' from DB")

                elif 5 <= slot <= 10:
                    if item_type == "Potion":
                        inventory.append(Potion(player.x, player.y, potion_img, "Potion"))
                    elif item_type == "Poison":
                        inventory.append(Potion(player.x, player.y, poison_img, "Poison"))

            # עכשיו נכניס אותם לרשימת השחקן לפי הסדר (0 עד 4)
            for i in range(5):
                if i in temp_weapons:
                    player.inventory.append(temp_weapons[i])

        # ==========================================
        # בניית המחרוזת לשליחה לשרת המשחק - מחוץ ל-if!!
        # השרת מצפה להפרדה בעזרת מקף (-) ולמילה none עבור סלוט ריק!
        # ==========================================
        inv_str_parts = []
        for i in range(5):
            if i < len(player.inventory):
                inv_str_parts.append(f"{player.inventory[i].name},{player.inventory[i].ammo}")
            else:
                inv_str_parts.append("none,0")

        final_inv_str = "-".join(inv_str_parts)

        potions_names = [p.name for p in inventory]
        potions_str = ",".join(potions_names) if potions_names else "None"

        # השליחה עצמה
        outgoing_messages.put(f"Connected|{MY_ID}|{player_name}|{player.x},{player.y}|{player.hp}|{final_inv_str}|{potions_str}|True")
        outgoing_messages.put(f"UPDATE|{player.x},{player.y}")

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    outgoing_messages.put("Disconnected")
                    running = False

                if is_dead:
                    continue

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
                        continue

                    if event.key == pygame.K_t:
                        chat_open = True
                        chat_input = ""

                    if event.key == pygame.K_i:
                        inventory_open = not inventory_open

                    if event.key == pygame.K_n:
                        player.auto_walk = not player.auto_walk
                        print("Auto-walk:", player.auto_walk)

                    if event.key == pygame.K_e and len(player.inventory) < 5:
                        nearby_loot   = get_nearby_item(player, loot_items)
                        nearby_potion = get_nearby_item(player, hp_items)
                        if nearby_loot:
                            # Set starting ammo from WEAPON_AMMO so counter shows immediately
                            nearby_loot.ammo = WEAPON_AMMO.get(nearby_loot.name)
                            player.pick_item(nearby_loot)
                            loot_items.remove(nearby_loot)
                            outgoing_messages.put(f"PICKUP|{nearby_loot.x},{nearby_loot.y}|{nearby_loot.name}")
                        elif nearby_potion:
                            hp_items.remove(nearby_potion)
                            inventory.append(nearby_potion)
                            outgoing_messages.put(f"PPICKUP|{nearby_potion.x},{nearby_potion.y}|{nearby_potion.name}")
                            print(nearby_potion.name)
                            print("Picked potion")

                    if event.key == pygame.K_r:
                        if len(inventory) > 0:
                            item = inventory[0]
                            if item.name == "Potion":
                                if player.hp == 100:
                                    continue
                                inventory.pop(0)
                                player.hp += UP_HP
                                if player.hp > 100:
                                    player.hp = 100
                                outgoing_messages.put(f"USE|{item.name}")
                            elif item.name == "Poison":
                                inventory.pop(0)
                                outgoing_messages.put(f"USE|{item.name}|{player.x + 32},{player.y + 32}")

                    if event.key == pygame.K_z or event.key == pygame.K_x or event.key == pygame.K_c:
                        current_time = pygame.time.get_ticks() / 1000

                        elapsed = current_time - skill.last_action_time - (skill.duration_time if skill.is_active else 0)

                        if skill.is_active and elapsed < skill.duration_time:
                            print(f"Skill is already active! Ends in {skill.duration_time - elapsed:.1f}s")

                        total_wait_required = (skill.duration_time if skill.last_action_time != 0 else 0) + SKILL_COOL_TIME

                        if elapsed >= total_wait_required:
                            skill = skills_dict["Speed Boost"] if event.key == pygame.K_x else skills_dict["Shield"] if event.key == pygame.K_c else skills_dict["Bombs"]
                            skill.last_action_time = current_time
                            skill.is_active = True
                            player.skill = skill
                            print("Skill Active!")
                            active_skills[MY_ID] = skill
                            outgoing_messages.put(f"SKILL|{skill.name}|{current_time}")
                        else:
                            remaining = total_wait_required - elapsed
                            print(f"Skill on cooldown. Wait {remaining:.1f}s")

                    if event.key == pygame.K_q:
                        slot_to_drop = player.selected_slot
                        gun = player.drop_selected_weapon()
                        if gun:
                            dropped = Item(player.x, player.y, gun.image, "weapon", gun.name)
                            loot_items.append(dropped)
                            outgoing_messages.put(f"DROP|{player.x},{player.y}|{slot_to_drop}")
                            print(f"Dropped {gun.name}")

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
                    if event.button == 1:
                        current_camera_x = player.x - screen.get_width() // 2
                        current_camera_y = player.y - screen.get_height() // 2
                        mouse_x, mouse_y = pygame.mouse.get_pos()
                        world_mouse_x = mouse_x + current_camera_x
                        world_mouse_y = mouse_y + current_camera_y
                        player_center_x = player.x + (player.size // 2)
                        player_center_y = player.y + (player.size // 2)
                        dx = world_mouse_x - player_center_x
                        dy = world_mouse_y - player_center_y
                        angle_degrees = math.degrees(math.atan2(dy, dx))
                        # שמור כיוון ירי זמני
                        if abs(dx) > abs(dy):
                            shoot_direction = "right" if dx > 0 else "left"
                        else:
                            shoot_direction = "down" if dy > 0 else "up"
                        shoot_direction_timer = 10  # 10 פריימים

                        outgoing_messages.put(f"ATTACK|{player.selected_slot}|{angle_degrees}")

            if not chat_open and not is_dead:
                keys = pygame.key.get_pressed()
                player.move(keys, game_map, tile_size, skill)

            while not incoming_messages.empty():
                sender_ip, sender_port, msg = incoming_messages.get()

                if msg == "INTERNAL_SERVER_DISCONNECT":
                    print(f"Server {sender_ip}:{sender_port} disconnected. Removing from list.")
                    for s in servers:
                        if s.ip == sender_ip and s.port == sender_port:
                            servers.remove(s)
                            break

                    if len(servers) == 0:
                        running = False
                    continue  # לא ממשיכים לפרסר הודעה פנימית כהודעת רשת

                # ------------------------------

                print(f"[{sender_ip}:{sender_port}] {msg}")
                parts = msg.split("|")
                if not parts:
                    continue

                if parts[0] == "SWITCHED":
                    if len(parts) < 4:
                        continue

                    new_ip = parts[1]
                    new_port = int(parts[2])
                    is_host_flag = parts[3]

                    already_connected = any(srv.ip == new_ip and srv.port == new_port for srv in servers)

                    is_transferring = True

                    if not already_connected:
                        servers.append(Server(new_ip, new_port))
                        outgoing_messages.add_server(new_ip, new_port)
                        start_quic_thread(new_ip, new_port)
                        print("connect to the other server")
                    else:
                        print(f"Already connected to {new_ip}:{new_port}, forcing handoff sync.")

                    current_inv_parts = []
                    for i in range(5):
                        if i < len(player.inventory):
                            current_inv_parts.append(f"{player.inventory[i].name},{player.inventory[i].ammo}")
                        else:
                            current_inv_parts.append("none,0")
                    current_inv_str = "-".join(current_inv_parts)

                    current_potions_names = [p.name for p in inventory]
                    current_potions_str = ",".join(current_potions_names) if current_potions_names else "None"

                    outgoing_messages.put_to_specific(new_ip, new_port,f"Connected|{MY_ID}|{player_name}|{player.x},{player.y}|{player.hp}|{current_inv_str}|{current_potions_str}|{is_host_flag}")

                    is_transferring = True
                elif parts[0] == "CHANGECONTROL":
                    if len(parts) < 4:
                        continue

                    target_ip = parts[1]
                    target_port = int(parts[2])
                    is_host_flag = parts[3]

                    # שולחים את אישור השליטה לשרת החדש
                    outgoing_messages.put_to_specific(target_ip, target_port, f"CHANGECONTROL|{is_host_flag}")

                    server_to_remove = None
                    for srv in servers:
                        # תיקון קריטי: מוחקים את השרת הישן (השולח) ולא את השרת החדש (המטרה)
                        if srv.ip == sender_ip and srv.port == sender_port:
                            server_to_remove = srv
                            break

                    if server_to_remove:
                        servers.remove(server_to_remove)
                        outgoing_messages.remove_server(server_to_remove.ip, server_to_remove.port)
                        print(f"Disconnected from old server {server_to_remove.ip}:{server_to_remove.port}")

                    is_transferring = False


                if parts[0] == "UPDATE":
                    if len(parts) < 4:
                        continue
                    player_id = parts[1]
                    x, y = map(float, parts[2].split(","))
                    hp = int(parts[3])
                    has_weapon = bool(int(parts[4])) if len(parts) > 4 else False

                    if player_id == MY_ID:
                        player.hp = hp
                    else:
                        if player_id not in remote_players:
                            remote_players[player_id] = RemotePlayer(x, y, hp, player.base_sprites, player.weapon_sprites, player_id, has_weapon)
                            outgoing_messages.put(f"UPDATE|{player.x},{player.y}")
                        else:
                            remote_players[player_id].update_from_server(x, y, hp, has_weapon)

                elif parts[0] == "REMOVE":
                    if len(parts) < 2:
                        continue
                    player_id = parts[1]
                    if player_id == MY_ID:
                        if is_transferring:
                            print(f"Ignored REMOVE from {sender_ip}:{sender_port} because we are transferring to a new server.")
                            continue

                        is_active_server = any(srv.ip == sender_ip and srv.port == sender_port for srv in servers)
                        if not is_active_server:
                            print(f"Ignored REMOVE for MY_ID from disconnected server {sender_ip}:{sender_port}")
                            continue
                        else:
                            pygame.quit()
                            exit()
                elif parts[0] == "SHOW-BULLET":
                    if len(parts) < 5:
                        continue
                    bullet_x = parts[1].split(',')[0]
                    bullet_y = parts[1].split(',')[1]
                    bullets[parts[3]] = {"x": bullet_x, "y": bullet_y, "angle": parts[2], "type": parts[4]}
                elif parts[0] == "DEAD":
                    is_dead = True
                    bullets.clear()
                    monsters.clear()
                elif parts[0] == "DEL-BULLET":
                    if len(parts) < 2:
                        continue
                    try:
                        b = bullets.get(parts[1])
                        if b and b.get("type") == "bomb":
                            # הוסף אפקט פיצוץ במיקום הפצצה
                            poison_effects.append(ExplosionEffect(float(b["x"]), float(b["y"])))
                        del bullets[parts[1]]
                    except:
                        pass
                elif parts[0] == "RESPAWNED":
                    if len(parts) < 3:
                        continue
                    rx, ry = map(float, parts[1].split(","))
                    player.x, player.y = int(rx), int(ry)  # int() fixes draw_map range() crash
                    player.hp = int(parts[2])
                    player.inventory = []
                    player.selected_slot = 0
                    skill = skills_dict["Shield"]
                    skill.is_active = False
                    skill.last_action_time = 0
                    active_skills.pop(MY_ID, None)
                    inventory.clear()
                    bullets.clear()
                    monsters.clear()
                    is_dead = False
                    respawn_sent = False
                    outgoing_messages.put(f"UPDATE|{player.x},{player.y}")


                elif parts[0] == "DROPPED":
                    if len(parts) < 3:
                        continue
                    x_dropped, y_dropped = parts[1].split(",")
                    x_dropped = float(x_dropped)
                    y_dropped = float(y_dropped)
                    type_dropped = parts[2]
                    if type_dropped in weapon_images:
                        img = weapon_images[type_dropped]
                        loot_items.append(Item(x_dropped, y_dropped, img, "weapon", type_dropped))
                    else:
                        print(f"Warning: Unknown weapon type dropped: {type_dropped}")

                elif parts[0] == "UNDROPPED":
                    if len(parts) < 3:
                        continue
                    x_pick, y_pick = parts[1].split(",")
                    x_pick = float(x_pick)
                    y_pick = float(y_pick)
                    type_pick = parts[2]
                    if type_pick in ("Potion", "Poison"):
                        for potion in hp_items:
                            if potion.x == x_pick and potion.y == y_pick and potion.name == type_pick:
                                hp_items.remove(potion)
                                break
                    else:
                        for item in loot_items:
                            if item.x == x_pick and item.y == y_pick and item.name == type_pick:
                                loot_items.remove(item)
                                break

                elif parts[0] == "AMMO":
                    # Server sends current ammo after every shot so the display stays live
                    if len(parts) < 3:
                        continue
                    try:
                        slot = int(parts[1])
                        ammo  = int(parts[2])
                        if 0 <= slot < len(player.inventory):
                            player.inventory[slot].ammo = ammo
                    except:
                        pass

                elif parts[0] == "REMOVE_WEAPON":
                    # Server tells us a weapon slot ran out of ammo and was removed
                    if len(parts) < 2:
                        continue
                    try:
                        slot = int(parts[1])
                        if 0 <= slot < len(player.inventory):
                            player.inventory.pop(slot)
                            if player.selected_slot >= len(player.inventory):
                                player.selected_slot = max(len(player.inventory) - 1, 0)
                    except:
                        pass

                elif parts[0] == "CHAT":
                    if len(parts) < 3:
                        continue
                    sender_id = parts[1]
                    short_id = sender_id[-6:] if len(sender_id) >= 6 else sender_id
                    display_name = "You" if sender_id == MY_ID else short_id
                    chat_messages.append((f"<{display_name}> {parts[2]}", time.time()))


                elif parts[0] == "FPS":
                    server_fps = parts[1]

                elif parts[0] == "MONSTERS":
                    monsters.clear()
                    for monster_data in parts[1:]:
                        x_monster, y_monster, hp_monster = monster_data.split(",")
                        x_monster  = float(x_monster)
                        y_monster  = float(y_monster)
                        hp_monster = int(hp_monster)
                        if hp_monster > 0:
                            monsters.append(Monster(x_monster, y_monster, hp_monster, monster_img))

                elif parts[0] == "POTIONS":
                    x_potion, y_potion = parts[1].split(",")
                    x_potion = float(x_potion)
                    y_potion = float(y_potion)
                    if parts[2] == "Potion":
                        hp_items.append(Potion(x_potion, y_potion, potion_img, "Potion"))
                    elif parts[2] == "Poison":
                        hp_items.append(Potion(x_potion, y_potion, poison_img, "Poison"))


                elif parts[0] == "SKILL":
                    player_id = parts[1]
                    player_skill = parts[2]
                    is_active = parts[3]

                    if is_active == "True":
                        active_skills[player_id] = skills_dict[player_skill]
                    else:
                        if player_id in active_skills:
                            del active_skills[player_id]


                elif parts[0] == "POISON":
                    pos = parts[1]
                    x, y = map(float, pos.split(","))
                    poison_effects.append(PoisonEffect(x, y))

                elif parts[0] == "ITEMS":
                    if len(parts) < 3:
                        continue
                    x_item, y_item = parts[1].split(",")
                    x_item = float(x_item)
                    y_item = float(y_item)
                    if parts[2] == "Potion":
                        hp_items.append(Potion(x_item, y_item, potion_img, "Potion"))
                    elif parts[2] == "Poison":
                        hp_items.append(Potion(x_item, y_item, poison_img, "Poison"))

            # --- CAMERA ---
            camera_x = player.x - screen.get_width() // 2
            camera_y = player.y - screen.get_height() // 2

            screen.fill((30, 30, 30))
            draw_map(screen, game_map, tile_size, camera_x, camera_y, floor_img, wall_img)

            for item in loot_items:
                item.update()
                item.draw(screen, camera_x, camera_y)
            if shoot_direction_timer > 0:
                shoot_direction_timer -= 1
                player.direction = shoot_direction
            player.draw(screen, camera_x, camera_y, active_skills)
            for rp in remote_players.values():
                rp.draw(screen, camera_x, camera_y, active_skills)
            for monster in monsters:
                if (camera_x - 100 <= monster.x <= camera_x + screen.get_width() + 100 and
                        camera_y - 100 <= monster.y <= camera_y + screen.get_height() + 100):
                    monster.update()
                    monster.draw(screen, camera_x, camera_y)

            for hp_item in hp_items:
                hp_item.draw(screen, camera_x, camera_y)

            for effect in poison_effects:
                effect.update()
                effect.draw(screen, camera_x, camera_y)
            poison_effects = [e for e in poison_effects if len(e.particles) > 0]

            for i in bullets:
                bullet_x     = float(bullets[i]["x"])
                bullet_y     = float(bullets[i]["y"])
                bullet_angle = float(bullets[i]["angle"])
                bullet_type = str(bullets[i]["type"])
                draw_bullet(screen, bullet_img if bullet_type == "bullet" else bomb_img, bullet_x, bullet_y, bullet_angle, camera_x, camera_y,bullet_type)
                new_x, new_y = get_next_bullet_position(bullet_x, bullet_y, bullet_angle)
                bullets[i]["x"] = new_x
                bullets[i]["y"] = new_y

                #if on player/outside the map/on water:
                #del bullets[i]

            current_time = pygame.time.get_ticks() / 1000
            if skill.is_active:
                if current_time - skill.last_action_time >= skill.duration_time:
                    skill.is_active = False
                    player.skill = skill
                    del active_skills[MY_ID]
                    print("Skill duration finished! (Speed boost ended)")
            draw_fps(screen, clock, chat_font, server_fps)
            draw_inventory(screen, player, chat_font)
            draw_chat(screen, chat_font, chat_messages, chat_open, chat_input)
            draw_icons(screen, [shield_icon, speed_boost_icon, bomb_icon], skill)
            draw_potion_slot(screen, inventory)
            if inventory_open:
                draw_big_inventory(screen, player, inventory, ui_font)

            if is_dead:
                action = draw_death_screen(screen, death_font_title, death_font_btn, pygame.mouse.get_pos())
                if action == "respawn" and not respawn_sent:
                    respawn_sent = True
                    outgoing_messages.put("RESPAWN")
                elif action == "quit":
                    outgoing_messages.put("Disconnected")
                    pygame.quit(); exit()

            pygame.display.flip()
            clock.tick(60)

    pygame.quit()

main()