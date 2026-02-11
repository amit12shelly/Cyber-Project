import asyncio

import pygame

def run_pygame():
    pygame.init()
    screen = pygame.display.set_mode((1200, 600))
    clock = pygame.time.Clock()
    map = []
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return

        screen.fill((20, 100, 200))

        pygame.display.flip()
        clock.tick(60)

def init_map():
    with open('map','w') as f:
        for i in range(80):
            for j in range(99):
                f.write('0,')
            f.write('0\n')

def main():
    run_pygame()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass