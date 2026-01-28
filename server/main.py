import asyncio
from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent, ConnectionTerminated

class GameState:
    players_pos = {}
    # Track all active client protocols
    active_clients = set()


state = GameState()


class EchoQuicProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add this client to the set when they connect
        state.active_clients.add(self)

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            data_str = event.data.decode("utf-8")
            client_id = self._quic.host_cid.hex()

            if data_str.startswith("Connected"):
                # 1. Initialize this player in the master list if they aren't there
                if client_id not in state.players_pos:
                    state.players_pos[client_id] = data_str.split(':')[1]

                    # 2. Tell the NEW player where EVERYONE ELSE is
                for other_id, pos in state.players_pos.items():
                    if other_id != client_id:
                        sync_msg = f"UPDATE|{other_id}|{pos}".encode()
                        self._quic.send_stream_data(0, sync_msg, end_stream=False)

                # 3. Tell EVERYONE ELSE that this new player has joined
                self.broadcast_position(client_id, state.players_pos[client_id], False)
                self.transmit()

            elif data_str.startswith("moved to:"):
                state.players_pos[client_id] = data_str.split(":")[1]
                self.broadcast_position(client_id, state.players_pos[client_id], False)
            elif data_str == "Disconnected":
                client_id = self._quic.host_cid.hex()
                if self in state.active_clients:
                    state.active_clients.remove(self)
                self.broadcast_remove(client_id)  # Tell others to delete the square
        elif isinstance(event, ConnectionTerminated):
            print("Client logged out")

    def broadcast_remove(self, client_id):
        message = f"REMOVE|{client_id}".encode("utf-8")
        for client in state.active_clients:
            client._quic.send_stream_data(0, message, end_stream=False)
            client.transmit()

    def broadcast_position(self, sender_id, pos_str, to_yourself):
        message = f"UPDATE|{sender_id}|{pos_str}".encode("utf-8")

        for client in state.active_clients:
            # You can skip sending it back to the person who moved if you want:
            if client == self and not to_yourself: continue

            # Use stream 0 or a dedicated broadcast stream
            client._quic.send_stream_data(0, message, end_stream=False)
            client.transmit()

async def main():
    # 1. Define the QUIC configuration
    configuration = QuicConfiguration(
        is_client=False,
        alpn_protocols=["echo-protocol"] # Custom protocol name
    )

    # 2. Load the SSL certificate and private key
    configuration.load_cert_chain("../cert.pem", "key.pem")

    # 3. Start the server
    print("Starting QUIC server on udp:0.0.0.0:4433")
    await serve(
        host="0.0.0.0",
        port=4433,
        configuration=configuration,
        create_protocol=EchoQuicProtocol,
    )

    # Keep the server running
    await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass