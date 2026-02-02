import asyncio
from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent, ConnectionTerminated


class GameState:
    players_pos = {}
    active_clients = set()


state = GameState()


class EchoQuicProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        state.active_clients.add(self)
        self.client_id = None

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            # 1. פענוח המידע והפרדה לפי שורות (למניעת הדבקת חבילות)
            data_chunk = event.data.decode("utf-8")
            messages = data_chunk.split('\n')  # מפרידים הודעות לפי ירידת שורה

            for message in messages:
                if not message: continue  # דילוג על שורות ריקות

                self.process_message(message)

        elif isinstance(event, ConnectionTerminated):
            print(f"Client {self.client_id} disconnected (Terminated)")
            self.remove_player()

    def process_message(self, data_str):
        # קבלת ה-ID הייחודי של החיבור
        self.client_id = self._quic.host_cid.hex()

        if data_str.startswith("Connected"):
            try:
                # פורמט צפוי: "Connected:x,y"
                start_pos = data_str.split(':')[1]
                state.players_pos[self.client_id] = start_pos
                print(f"New player: {self.client_id} at {start_pos}")

                # 1. שליחת המיקום של כל השחקנים האחרים לשחקן החדש
                for other_id, pos in state.players_pos.items():
                    if other_id != self.client_id:
                        # שים לב ל-\n בסוף!
                        sync_msg = f"UPDATE|{other_id}|{pos}\n".encode()
                        self._quic.send_stream_data(0, sync_msg, end_stream=False)

                # 2. עדכון כולם על השחקן החדש
                self.broadcast_position(self.client_id, start_pos, False)

            except Exception as e:
                print(f"Error parsing connection: {e}")

        elif data_str.startswith("moved to:"):
            try:
                new_pos = data_str.split(":")[1]
                state.players_pos[self.client_id] = new_pos
                self.broadcast_position(self.client_id, new_pos, False)
            except:
                pass

        elif data_str == "Disconnected":
            self.remove_player()

    def remove_player(self):
        if self in state.active_clients:
            state.active_clients.remove(self)
        if self.client_id and self.client_id in state.players_pos:
            del state.players_pos[self.client_id]
            self.broadcast_remove(self.client_id)

    def broadcast_remove(self, client_id):
        message = f"REMOVE|{client_id}\n".encode("utf-8")  # הוספנו \n
        for client in state.active_clients:
            try:
                client._quic.send_stream_data(0, message, end_stream=False)
                client.transmit()
            except:
                pass

    def broadcast_position(self, sender_id, pos_str, to_yourself):
        message = f"UPDATE|{sender_id}|{pos_str}\n".encode("utf-8")  # הוספנו \n

        for client in state.active_clients:
            if client == self and not to_yourself: continue
            try:
                client._quic.send_stream_data(0, message, end_stream=False)
                client.transmit()
            except:
                pass


async def main():
    configuration = QuicConfiguration(
        is_client=False,
        alpn_protocols=["echo-protocol"],
        verify_mode=False
    )
    # וודא שהנתיבים לקבצים נכונים ביחס לאיפה שאתה מריץ
    configuration.load_cert_chain("cert.pem", "server/key.pem")

    print("Starting QUIC server on udp:0.0.0.0:4433")
    await serve(
        host="0.0.0.0",
        port=4433,
        configuration=configuration,
        create_protocol=EchoQuicProtocol,
    )
    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass