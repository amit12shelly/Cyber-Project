import asyncio
import pygame
from aioquic.asyncio import QuicConnectionProtocol
from aioquic.quic.events import QuicEvent, StreamDataReceived
from aioquic.quic.configuration import QuicConfiguration

import game_main
from aioquic.asyncio.client import connect
from aioquic.quic.configuration import QuicConfiguration


configuration = QuicConfiguration(is_client=True)
global GS_IP
global GS_PORT
def login_user(username, password):
    return GS_IP,GS_PORT

def set_up():
    pass

async def get_map():
    pass

async def run_pygame():
    my_game = game_main.Game()
    my_game.run()

async def sand_changes_to_game_server():
    pass

async def update_other_players():
    pass

async def get_game_server():
    pass


class GameClientProtocol(QuicConnectionProtocol):
    def quic_event_received(self, event: QuicEvent):
        if isinstance(event, StreamDataReceived):
            data = event.data.decode("utf-8")
            if data.startswith("UPDATE|"):
                pass
            elif data.startswith("NEWGS|"):
                global GS_IP, GS_PORT
                GS_IP = data.split("|")[1]
                GS_PORT = data.split("|")[2]

async def listen_to_game_server(reader, game):
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
    global GS_IP, GS_PORT
    login_port = 8820
    login_ip = "x.x.x.x"  # login server ip - defined every time by us
    user_name = "x" #from pygame
    password = "x"  # from pygame
    print("processing login...")
    GS_IP, GS_PORT = login_user(user_name , password)
    print("connecting...")
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=["GameClientProtocol"],
        verify_mode=False
    )
    async with connect(
            GS_IP,
            GS_PORT,
            configuration=configuration,
            create_protocol=GameClientProtocol,
    ):
        await run_pygame()
    EXIT = False
    while not EXIT:
        pass



if __name__ == "__main__":
    asyncio.run(main_game_loop())