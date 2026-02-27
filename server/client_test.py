import asyncio

from aioquic.asyncio import QuicConnectionProtocol
from aioquic.asyncio.client import connect
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent
1

class GameTestClient(QuicConnectionProtocol):
    def quic_event_received(self, event: QuicEvent) -> None:
        # הפונקציה הזו מופעלת בכל פעם שהשרת שולח לנו הודעה חזרה
        if isinstance(event, StreamDataReceived):
            data_str = event.data.decode("utf-8")
            print(f"\n[SERVER MESSAGE]: {data_str}")
            print("\n> ", end="", flush=True)  # מדפיס מחדש את החץ של הקלט

    def send_game_message(self, message: str):
        # פונקציה לשליחת טקסט לשרת
        self._quic.send_stream_data(0, message.encode("utf-8"), end_stream=False)
        self.transmit()


async def main():
    # 1. הגדרת QUIC בדיוק כמו בשרת (ללא אימות SSL כדי להקל על הבדיקות)
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=["echo-protocol"],
        verify_mode=False,
    )

    print("Connecting to server at 127.0.0.1:4433...")

    # 2. התחברות לשרת
    async with connect("127.0.0.1", 4433, configuration=configuration, create_protocol=GameTestClient) as protocol:
        print("Connected successfully!\n")

        while True:
            print("\n--- TEST MENU ---")
            print("1 - Send 'Connected' (Join game)")
            print("2 - Send 'UPDATE' (Move player)")
            print("3 - Send 'ATTACK' (Shoot gun)")
            print("4 - Send 'Disconnected' (Leave game)")
            print("q - Quit test client")

            # מחכים לקלט מהמשתמש בלי לתקוע את הלולאה האסינכרונית
            cmd = await asyncio.to_thread(input, "\nChoose option: ")

            if cmd == '1':
                protocol.send_game_message("Connected|10,10|100")
                print("Sent: Connected|10,10|100")
            elif cmd == '2':
                # שולחים תזוזה קטנה כדי לעבור את בדיקת ה- check_movement
                protocol.send_game_message("UPDATE|11,11")
                print("Sent: UPDATE|11,11")
            elif cmd == '3':
                # שולחים פקודת ירייה
                protocol.send_game_message("ATTACK|gun|45")
                print("Sent: ATTACK|gun|45")
            elif cmd == '4':
                protocol.send_game_message("Disconnected")
                print("Sent: Disconnected")
            elif cmd == 'q':
                break
            else:
                print("Invalid option.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nClient stopped.")