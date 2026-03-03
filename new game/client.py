import pygame
import random
import threading
import asyncio
from queue import Queue
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

# ---------------- NETWORKING ---------------- #

SERVER_IP = "127.0.0.1"
SERVER_PORT = 4433

incoming_messages = Queue()
outgoing_messages = Queue()


async def quic_network_loop():
    config = QuicConfiguration(
        is_client=True,
        alpn_protocols=["echo-protocol"],
        verify_mode=False
    )

    async with connect(SERVER_IP, SERVER_PORT, configuration=config) as client:
        stream = client.create_stream(is_unidirectional=False)

        async def reader():
            while True:
                data = await stream.receive()
                if not data:
                    break
                incoming_messages.put(data.decode("utf-8"))

        async def writer():
            loop = asyncio.get_event_loop()
            while True:
                msg = await loop.run_in_executor(None, outgoing_messages.get)
                stream.send(msg.encode("utf-8"))

        await asyncio.gather(reader(), writer())


def start_quic_thread():
    loop = asyncio.new_event_loop()

    def runner():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(quic_network_loop())

    threading.Thread(target=runner, daemon=True).start()


# ---------------- MAP FUNCTIONS ---------------- #

def load_map(filename):
    with open(filename, "r") as f:
        lines = f.readlines()
    return [list(line.strip()) for line in lines]


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


def spawn_loot_per_camera_zone(game_map, tile_size, loot_pool, screen_width, screen_height, per_zone=2):
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

                if game_map[tile_y][tile_x] != "#":
                    x = tile_x * tile_size
                    y = tile_y * tile_size
                    item_type, name, image = random.choice(loot_pool)
                    loot_list.append(Item(x, y, image, item_type, name))
                    spawned += 1

    return loot_list


# ---------------- Item CLASS ---------------- #

class Item:
    def __init__(self, x, y, image, item_type, name):
        self.x = x
        self.y = y
        self.image = image
        self.type = item_type
        self.name = name
        self.size = 64
        self.rect = pygame.Rect(x, y, self.size, self.size)

    def update(self):
        self.rect.topleft = (self.x, self.y)

    def draw(self, screen, camera_x, camera_y):
        screen.blit(self.image, (self.x - camera_x, self.y - camera_y))


# ---------------- PLAYER CLASSES ---------------- #

class Player:
    def __init__(self, x, y, hp=50):
        self.x = x
        self.y = y
        self.hp = hp
        self.speed = 4
        self.direction = "down"
        self.size = 64

        self.sprites = {
            "up": pygame.transform.scale(pygame.image.load("img/upSprite.png"), (64, 64)),
            "down": pygame.transform.scale(pygame.image.load("img/downSprite.png"), (64, 64)),
            "left": pygame.transform.scale(pygame.image.load("img/leftSprite.png"), (64, 64)),
            "right": pygame.transform.scale(pygame.image.load("img/rightSprite.png"), (64, 64)),
        }

        self.auto_walk = False
        self.wander_direction = "down"
        self.wander_timer = 0

    def pick_random_direction(self):
        self.wander_direction = random.choice(["up", "down", "left", "right"])
        self.direction = self.wander_direction
        self.wander_timer = random.randint(20, 60)

    def move(self, keys, game_map, tile_size):
        moved = False

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

        if self.auto_walk and not moved:
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
        screen.blit(self.sprites[self.direction], (self.x - camera_x, self.y - camera_y))

        bar_width = 100
        bar_height = 5
        bar_x = self.x - camera_x + (self.size // 2) - (bar_width // 2)
        bar_y = self.y - camera_y - 10

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


# ---------------- MAIN GAME LOOP ---------------- #

def main():
    pygame.init()
    screen = pygame.display.set_mode((1280, 720))
    pygame.display.set_caption("Game")
    clock = pygame.time.Clock()

    tile_size = 64
    floor_img = pygame.image.load("img/DesertTile.png").convert()
    wall_img = pygame.image.load("img/watertile.png").convert()

    floor_img = pygame.transform.scale(floor_img, (tile_size, tile_size))
    wall_img = pygame.transform.scale(wall_img, (tile_size, tile_size))
    game_map = load_map("map.txt")

    player = Player(128, 128)

    # Start networking
    start_quic_thread()
    outgoing_messages.put(f"Connected|{player.x},{player.y}|{player.hp}")

    # Load loot images
    gun1_img = pygame.transform.scale(
        pygame.image.load("img/rightWeapon1.png").convert_alpha(), (64, 64)
    )
    gun2_img = pygame.transform.scale(
        pygame.image.load("img/rightWeapon2.png").convert_alpha(), (64, 64)
    )

    loot_pool = [
        ("weapon", "Sword", gun1_img),
        ("weapon", "Gun", gun2_img),
    ]

    loot_items = spawn_loot_per_camera_zone(
        game_map, tile_size, loot_pool, screen.get_width(), screen.get_height(), per_zone=1
    )

    remote_players = {}
    bullets = []

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                outgoing_messages.put("Disconnected")

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_n:
                    player.auto_walk = not player.auto_walk

                if event.key == pygame.K_SPACE:
                    angle = 0
                    outgoing_messages.put(f"ATTACK|gun|{angle}")

        keys = pygame.key.get_pressed()

        old_x, old_y = player.x, player.y
        player.move(keys, game_map, tile_size)

        if (player.x, player.y) != (old_x, old_y):
            outgoing_messages.put(f"UPDATE|{player.x},{player.y}")

        # Process server messages
        while not incoming_messages.empty():
            msg = incoming_messages.get()
            parts = msg.split("|")

            if parts[0] == "UPDATE":
                player_id = parts[1]
                x, y = map(float, parts[2].split(","))
                hp = int(parts[3])

                if player_id not in remote_players:
                    remote_players[player_id] = RemotePlayer(x, y, hp, player.sprites)
                else:
                    remote_players[player_id].update_from_server(x, y, hp)

            elif parts[0] == "REMOVE":
                player_id = parts[1]
                if player_id in remote_players:
                    del remote_players[player_id]

            elif parts[0] == "SHOWBULLET":
                bx, by = map(float, parts[1].split(","))
                bullets.append({"x": bx, "y": by, "timer": 12})

        camera_x = player.x - screen.get_width() // 2
        camera_y = player.y - screen.get_height() // 2

        screen.fill((30, 30, 30))

        draw_map(screen, game_map, tile_size, camera_x, camera_y, floor_img, wall_img)

        for item in loot_items:
            item.update()
            item.draw(screen, camera_x, camera_y)

        for b in bullets[:]:
            pygame.draw.circle(
                screen,
                (255, 255, 0),
                (b["x"] - camera_x, b["y"] - camera_y),
                5
            )
            b["timer"] -= 1
            if b["timer"] <= 0:
                bullets.remove(b)

        player.draw(screen, camera_x, camera_y)

        for rp in remote_players.values():
            rp.draw(screen, camera_x, camera_y)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()
