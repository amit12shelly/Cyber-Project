import pygame
import random

# ---------------- MAP FUNCTIONS ---------------- #

def load_map(filename):
    with open(filename, "r") as f:
        lines = f.readlines()
    return [list(line.strip()) for line in lines]

def draw_map(screen, game_map, tile_size, camera_x, camera_y):
    wall_color = (100, 100, 100)
    floor_color = (50, 50, 50)

    for y, row in enumerate(game_map):
        for x, tile in enumerate(row):
            rect = pygame.Rect(
                x * tile_size - camera_x,
                y * tile_size - camera_y,
                tile_size,
                tile_size
            )

            if tile == "#":
                pygame.draw.rect(screen, wall_color, rect)
            else:
                pygame.draw.rect(screen, floor_color, rect)

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

        # --- Auto-walk wandering ---
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

# ---------------- MAIN GAME LOOP ---------------- #

def main():
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Game")
    clock = pygame.time.Clock()

    tile_size = 64
    game_map = load_map("map.txt")

    player = Player(64, 64)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_n:
                    player.auto_walk = not player.auto_walk
                    print("Auto-walk:", player.auto_walk)

        keys = pygame.key.get_pressed()
        player.move(keys, game_map, tile_size)

        # --- CAMERA FOLLOWS PLAYER ---
        camera_x = player.x - screen.get_width() // 2
        camera_y = player.y - screen.get_height() // 2

        screen.fill((30, 30, 30))

        draw_map(screen, game_map, tile_size, camera_x, camera_y)
        player.draw(screen, camera_x, camera_y)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

main()