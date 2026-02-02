import asyncio
from random import randint

import pygame
from aioquic.asyncio import connect, QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent


class GameState:
    # Your local position (for prediction/sending)
    my_pos = [randint(0, 400), randint(0,300)]
    # Dictionary of other players: { "client_id": (x, y) }
    other_players = {}


state = GameState()


class EchoClientProtocol(QuicConnectionProtocol):
    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            data = event.data.decode("utf-8")

            # Handle Broadcast Update: "UPDATE|client_id|x,y"
            if data.startswith("UPDATE|"):
                parts = data.split("|")
                if len(parts) == 3:
                    p_id = parts[1]
                    coords = parts[2].split(",")

                    # Only update if it's not us (server might reflect our own move back)
                    # You can compare p_id with self._quic.original_destination_connection_id if needed
                    state.other_players[p_id] = (int(coords[0]), int(coords[1]))

            elif data.startswith("REMOVE|"):
                p_id = data.split("|")[1]
                if p_id in state.other_players:
                    del state.other_players[p_id]

async def run_pygame(client, stream_id):
    pygame.init()
    screen = pygame.display.set_mode((400, 300))
    clock = pygame.time.Clock()
    client._quic.send_stream_data(stream_id, "Connected pos:{},{}".format(state.my_pos[0], state.my_pos[1]).encode(), end_stream=False)
    client.transmit()

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                client._quic.send_stream_data(stream_id, b"Disconnected", end_stream=False)
                client.transmit()
                return

        # --- Input Handling ---
        keys = pygame.key.get_pressed()
        moved = False
        if keys[pygame.K_a]:
            state.my_pos[0] -= 5
            moved = True
        if keys[pygame.K_d]:
            state.my_pos[0] += 5
            moved = True
        if keys[pygame.K_w]:
            state.my_pos[1] -= 5
            moved = True
        if keys[pygame.K_s]:
            state.my_pos[1] += 5
            moved = True

        # --- Network Sync ---
        if moved:
            msg = f"moved to:{state.my_pos[0]},{state.my_pos[1]}".encode()
            client._quic.send_stream_data(stream_id, msg, end_stream=False)
            client.transmit()

        # --- Drawing ---
        screen.fill((30, 30, 30))

        # 1. Draw Other Players (Blue)
        for p_id, pos in state.other_players.items():
            pygame.draw.rect(screen, (20, 20, 120), (*pos, 40, 40))

        # 2. Draw My Player (Red)
        pygame.draw.rect(screen, (120, 20, 20), (*state.my_pos, 40, 40))

        pygame.display.flip()
        await asyncio.sleep(0)
        clock.tick(60)

    pygame.quit()


async def main():
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=["echo-protocol"],
    )

    configuration.load_verify_locations("../cert.pem")
    print("Connecting to server...")
    async with connect(
            "10.12.9.203",
            4433,
            configuration=configuration,
            create_protocol=EchoClientProtocol,
    ) as client:
        await client.wait_connected()
        print("Connected!")
        stream_id = client._quic.get_next_available_stream_id()
        await run_pygame(client, stream_id)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass