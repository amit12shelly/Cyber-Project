import asyncio

from aioquic.asyncio import QuicConnectionProtocol
from aioquic.asyncio.client import connect
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent, ConnectionTerminated


class GameTestClient(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recv_buffer = ""

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            self.recv_buffer += event.data.decode("utf-8")

            # מעבד הודעות מהשרת שמופרדות ב- \n
            while "\n" in self.recv_buffer:
                line, self.recv_buffer = self.recv_buffer.split("\n", 1)
                line = line.strip()
                if line:
                    print(f"\n[SERVER]: {line}")

            print("\nChoose option: ", end="", flush=True)

        elif isinstance(event, ConnectionTerminated):
            print("\n[!] Connection terminated by server.")

    def send_game_message(self, message: str):
        """
        שולח הודעה לשרת עם תו שורה חדשה.
        ב-QUIC, לקוח לרוב מתחיל תקשורת על Stream 0.
        """
        full_message = (message + "\n").encode("utf-8")
        self._quic.send_stream_data(0, full_message, end_stream=False)
        self.transmit()


async def client_loop(protocol: GameTestClient):
    """
    לולאת התפריט שרצה במקביל לקבלת הנתונים מהשרת
    """
    print("\nConnected successfully!")

    while True:
        print("\n--- TEST MENU ---")
        print("1 - Send 'Connected' (Join game)")
        print("2 - Send 'UPDATE' (Move player 4px)")
        print("3 - Send 'ATTACK' (Shoot gun)")
        print("4 - Send 'PICKUP' (Try pickup at 0,0)")
        print("5 - Send 'Disconnected' (Leave game)")
        print("q - Quit test client")

        # שימוש ב-to_thread כדי שה-input לא יחסום הודעות נכנסות מהשרת
        cmd = await asyncio.to_thread(input, "\nChoose option: ")

        if cmd == '1':
            protocol.send_game_message("Connected|0,0|100")
            print("Sent: Connected|0,0|100")
        elif cmd == '2':
            # בשרת מותר לזוז רק 8 פיקסלים בכל פעם
            protocol.send_game_message("UPDATE|4,4")
            print("Sent: UPDATE|4,4")
        elif cmd == '3':
            protocol.send_game_message("ATTACK|gun|45")
            print("Sent: ATTACK|gun|45")
        elif cmd == '4':
            protocol.send_game_message("PICKUP|0,0|gun")
            print("Sent: PICKUP|0,0|gun")
        elif cmd == '5':
            protocol.send_game_message("Disconnected")
            print("Sent: Disconnected")
            break
        elif cmd == 'q':
            break
        else:
            print("Invalid option.")


async def main():
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=["echo-protocol"],
        verify_mode=False,
    )

    print("Connecting to server at 127.0.0.1:4433...")

    # שימוש נכון ב-async with כדי למשוך את הפרוטוקול ולהעביר אותו ללולאת התפריט
    async with connect(
            "127.0.0.1",
            4433,
            configuration=configuration,
            create_protocol=GameTestClient
    ) as protocol:
        # הרצת לולאת התפריט כל עוד החיבור פעיל
        await client_loop(protocol)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nClient stopped.")
    except Exception as e:
        print(f"\nError: {e}")