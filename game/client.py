import asyncio
import pygame
from game_main import Game
from aioquic.asyncio.client import connect
from aioquic.quic.configuration import QuicConfiguration

configuration = QuicConfiguration(is_client=True)

def register_user(username, password):
    pass


def login_user(username, password):
    pass


async def listen_to_server(reader, game):
    try:
        while True:
            data = await reader.read(1024)

            if not data:
                print("נותק מהשרת")
                game.running = False
                break

            game.other_players_data = data.decode()

    except Exception as e:
        print(f"שגיאת רשת: {e}")


async def main_game_loop():
    reader, writer = None, None

    print("connecting...")
    try:
        async with connect("127.0.0.1", 8820, configuration=configuration) as protocol:
            stream_id = protocol._quic.get_next_available_stream_id()
    except Exception:
        print("Can't connect!")


if __name__ == "__main__":
    asyncio.run(main_game_loop())