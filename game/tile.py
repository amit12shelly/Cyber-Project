import pygame 
from settings import *

class Tile(pygame.sprite.Sprite):
    def __init__(self, pos, groups):
        super().__init__(groups)

        # Replace image with a red rectangle
        self.image = pygame.Surface((64, 64))   # choose any size you want
        self.image.fill((0, 255, 0))            # red (RGB)

        self.rect = self.image.get_rect(topleft=pos)
        self.hitbox = self.rect.inflate(0, -10)
