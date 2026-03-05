import asyncio
import math
import random
import psutil

from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent, ConnectionTerminated


class GameState:
    players_pos = {}        # client_id -> "x,y"
    players_hp = {}         # client_id -> hp
    active_clients = set()  # set of EchoQuicProtocol
    active_bullets = {}     # bullet_id -> {x, y, angle}


state = GameState()


class EchoQuicProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        state.active_clients.add(self)
        self.stream_id = None
        self.recv_buffer = ""  # for newline-delimited messages

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            if self.stream_id is None:
                self.stream_id = event.stream_id

            self.recv_buffer += event.data.decode("utf-8")

            while "\n" in self.recv_buffer:
                line, self.recv_buffer = self.recv_buffer.split("\n", 1)
                line = line.strip()
                if line:
                    self.handle_message(line)

        elif isinstance(event, ConnectionTerminated):
            print("Client logged out")
            self.disconnect()

    def handle_message(self, data_str: str):
        client_id = self._quic.host_cid.hex()

        # CONNECTED
        print(data_str)
        if data_str.startswith("Connected"):
            print(client_id, "connected!")
            parts = data_str.split("|")

            if len(parts) >= 3:
                state.players_pos[client_id] = parts[1]
                state.players_hp[client_id] = parts[2]
            else:
                state.players_pos[client_id] = "0,0"
                state.players_hp[client_id] = "100"

            id_msg = f"{client_id}".encode()
            self._quic.send_stream_data(0, id_msg, end_stream=False)

            # send existing players to new player
            for other_id, pos in state.players_pos.items():
                if other_id == client_id:
                    continue
                hp = state.players_hp.get(other_id, "100")
                msg = f"UPDATE|{other_id}|{pos}|{hp}\n".encode()
                if self.stream_id is not None:
                    self._quic.send_stream_data(self.stream_id, msg, end_stream=False)

            # tell others about new player
            self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], False)
            self.transmit()

        # MOVEMENT
        elif data_str.startswith("UPDATE|"):
            parts = data_str.split("|")
            if len(parts) < 2:
                return
            new_pos = parts[1]

            if client_id not in state.players_pos:
                return

            if check_movement(new_pos, state.players_pos[client_id]):
                state.players_pos[client_id] = new_pos
                self.broadcast_player(client_id, new_pos, state.players_hp[client_id], False)
            else:
                self.disconnect()

        # ATTACK
        elif data_str.startswith("ATTACK|"):
            parts = data_str.split("|")
            if len(parts) < 3:
                return
            weapon = parts[1]
            if weapon == "gun":
                new_id = random.randint(1, 1000000)
                while new_id in state.active_bullets:
                    new_id = random.randint(1, 1000000)

                pos_str = state.players_pos.get(client_id, "0,0")
                x_str, y_str = pos_str.split(",")
                angle = float(parts[2])

                state.active_bullets[new_id] = {
                    "x": float(x_str),
                    "y": float(y_str),
                    "angle": angle,
                }

                print("shooting!")
                asyncio.create_task(self.gun_tracking(new_id))

        # DISCONNECT
        elif data_str == "Disconnected":
            self.disconnect()

    # ---------- Broadcast helpers ---------- #

    def broadcast_show_bullet(self, pos: str):
        msg = f"SHOWBULLET|{pos}\n".encode()
        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

    def broadcast_remove(self, client_id: str):
        msg = f"REMOVE|{client_id}\n".encode()
        print("sent remove!")
        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()


    def broadcast_player(self, sender_id: str, pos_str: str, hp, to_yourself: bool):
        msg = f"UPDATE|{sender_id}|{pos_str}|{hp}\n".encode()
        for client in list(state.active_clients):
            if client == self and not to_yourself:
                continue
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()
        print("changed! -", msg)

    # ---------- Game logic ---------- #

    def disconnect(self):
        client_id = self._quic.host_cid.hex()

        if client_id in state.players_pos:
            del state.players_pos[client_id]
        if client_id in state.players_hp:
            del state.players_hp[client_id]
        if self in state.active_clients:
            state.active_clients.remove(self)

        self.broadcast_remove(client_id)
        print(client_id, "disconnected")

    async def gun_tracking(self, bullet_id: int):
        if bullet_id not in state.active_bullets:
            return

        x = state.active_bullets[bullet_id]["x"]
        y = state.active_bullets[bullet_id]["y"]
        angle = state.active_bullets[bullet_id]["angle"]

        for _ in range(20):
            x, y = get_next_bullet_position(x, y, angle)
            state.active_bullets[bullet_id]["x"] = x
            state.active_bullets[bullet_id]["y"] = y

            pos = f"{x},{y}"
            self.broadcast_show_bullet(pos)

            for player_id, pos_str in list(state.players_pos.items()):
                px, py = map(float, pos_str.split(","))
                if abs(px - x) <= 1.0 and abs(py - y) <= 1.0:
                    if player_id != self._quic.host_cid.hex():
                        del state.active_bullets[bullet_id]
                        self.damage(player_id, 20)
                        return

            await asyncio.sleep(0.2)

        if bullet_id in state.active_bullets:
            del state.active_bullets[bullet_id]

    def damage(self, client_id: str, damage: int):
        hp = int(state.players_hp.get(client_id, "100"))
        if hp - damage <= 0:
            print("player killed!")
            self.broadcast_remove(client_id)
        else:
            state.players_hp[client_id] = hp - damage
            self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], True)


# ---------- Utils ---------- #

def get_next_bullet_position(x, y, angle_degrees):
    angle_rad = math.radians(angle_degrees)
    return x + math.cos(angle_rad), y + math.sin(angle_rad)


def check_movement(new_pos, old_pos):
    new_x, new_y = map(float, new_pos.split(","))
    old_x, old_y = map(float, old_pos.split(","))

    if abs(new_x - old_x) <= 8 and abs(new_y - old_y) <= 8:
        return True

    print("player has been kicked!")
    return False


# ---------- Server entry ---------- #

async def check_cpu():
    while True:
        print("CPU:", psutil.cpu_percent(interval=1.0))
        await asyncio.sleep(20)


async def main():
    config = QuicConfiguration(
        is_client=False,
        alpn_protocols=["echo-protocol"],
        verify_mode=False,
    )

    config.load_cert_chain("cert.pem", "key.pem")

    print("Starting QUIC server on udp:0.0.0.0:4433")
    await serve(
        host="0.0.0.0",
        port=4433,
        configuration=config,
        create_protocol=EchoQuicProtocol,
    )

    asyncio.create_task(check_cpu())
    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass