import asyncio
import pygame
from aioquic.asyncio import QuicConnectionProtocol
from aioquic.quic.events import QuicEvent, StreamDataReceived
from aioquic.quic.configuration import QuicConfiguration

import game_main
import login_main
from aioquic.asyncio.client import connect
from aioquic.quic.configuration import QuicConfiguration


configuration = QuicConfiguration(is_client=True)
global GS_IP
global GS_PORT


def login_user():
    login_main.run_game_client()
    return GS_IP,GS_PORT


def get_map(map):
    pass

async def run_pygame():
    my_game = game_main.Game()
    my_game.run()

async def sand_changes_to_game_server():
    pass


class GameClientProtocol(QuicConnectionProtocol):
    def quic_event_received(self, event: QuicEvent):
        if isinstance(event, StreamDataReceived):
            data = event.data.decode("utf-8")
            if data.startswith("UPDATE|"):
                pass #should call an update function in the pygame file
                # also should sand the player updates to the gs

            elif data.startswith("SETMAP|"):
                 get_map(data.split("|")[1])

            elif data.startswith("NEWGS|"):
                global GS_IP, GS_PORT
                GS_IP = data.split("|")[1]
                GS_PORT = data.split("|")[2]

            elif data.startswith("UPDATE|"):
                player_id =  data.split("|")[1]
                player_pos = data.split("|")[2]
                player_hp = data.split("|")[3]
                #update_player = update_player.Game(player_id, player_pos , player_hp) #call a function that doesn't exist right now
                #update_player.run(player_id , player_pos , player_hp)


            elif data.startswith("REMOVE|"):
                player_id =  data.split("|")[1]
                #remove_player = remove_player_player.Game() #call a function that doesn't exist right now
                #remove_player.run(player_id , player_pos , player_hp)


async def main_game_loop():
    global GS_IP, GS_PORT
    print("processing login...")
    GS_IP, GS_PORT = login_user()
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



if __name__ == "__main__":
    asyncio.run(main_game_loop())