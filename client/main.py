import asyncio
from random import randint
import pygame
from aioquic.asyncio import connect, QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent


class GameState:
    my_pos = [randint(0, 350), randint(0, 250)]
    other_players = {}


state = GameState()


class EchoClientProtocol(QuicConnectionProtocol):
    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            data_chunk = event.data.decode("utf-8")
            # פירוק ההודעות לפי ירידת שורה למניעת הדבקה
            messages = data_chunk.split('\n')

            for msg in messages:
                if not msg: continue

                if msg.startswith("UPDATE|"):
                    try:
                        parts = msg.split("|")
                        p_id = parts[1]
                        coords = parts[2].split(",")
                        state.other_players[p_id] = (int(coords[0]), int(coords[1]))
                    except:
                        print(f"Error parsing update: {msg}")

                elif msg.startswith("REMOVE|"):
                    try:
                        p_id = msg.split("|")[1]
                        if p_id in state.other_players:
                            del state.other_players[p_id]
                    except:
                        pass


async def run_pygame(client, stream_id):
    pygame.init()
    screen = pygame.display.set_mode((400, 300))
    pygame.display.set_caption("QUIC Game")
    clock = pygame.time.Clock()

    # שליחת הודעת התחברות עם \n בסוף
    login_msg = f"Connected:{state.my_pos[0]},{state.my_pos[1]}\n".encode()
    client._quic.send_stream_data(stream_id, login_msg, end_stream=False)
    client.transmit()

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                client._quic.send_stream_data(stream_id, b"Disconnected\n", end_stream=False)
                client.transmit()
                running = False

        # תזוזה
        keys = pygame.key.get_pressed()
        moved = False
        step = 5
        if keys[pygame.K_a]: state.my_pos[0] -= step; moved = True
        if keys[pygame.K_d]: state.my_pos[0] += step; moved = True
        if keys[pygame.K_w]: state.my_pos[1] -= step; moved = True
        if keys[pygame.K_s]: state.my_pos[1] += step; moved = True

        if moved:
            # שליחת מיקום עם \n בסוף
            msg = f"moved to:{state.my_pos[0]},{state.my_pos[1]}\n".encode()
            client._quic.send_stream_data(stream_id, msg, end_stream=False)
            client.transmit()

        # ציור
        screen.fill((30, 30, 30))

        # שחקנים אחרים (כחול)
        for p_id, pos in list(state.other_players.items()):
            pygame.draw.rect(screen, (50, 100, 255), (*pos, 30, 30))

        # השחקן שלי (אדום)
        pygame.draw.rect(screen, (255, 50, 50), (*state.my_pos, 30, 30))

        pygame.display.flip()
        await asyncio.sleep(0)
        clock.tick(60)

    pygame.quit()


async def main():
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=["echo-protocol"],
        verify_mode=False
    )
    # שים לב: בדרך כלל בקליינט לא צריך מפתח פרטי, רק verify אם רוצים
    configuration.verify_mode = False

    print("Connecting to server...")
    # אם אתה מריץ מקומית, השתמש ב-127.0.0.1. אם לא, ב-IP של השרת
    target_ip = "127.0.0.1"

    async with connect(
            target_ip,
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