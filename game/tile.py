import pygame 
from settings import *

class Tile(pygame.sprite.Sprite):
    def __init__(self, pos, groups):
        super().__init__(groups)

        # Replace image with a red rectangle
        self.image = pygame.image.load("img/bush.png").convert_alpha()   # choose any size you want
        self.image = pygame.transform.scale(self.image,(64, 64))

        self.rect = self.image.get_rect(topleft=pos)
        self.hitbox = self.rect.inflate(0, -10)
