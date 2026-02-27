import asyncio
from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent, ConnectionTerminated
import psutil
import math
import random

class GameState:
    players_pos = {}
    players_hp = {}
    # Track all active client protocols
    active_clients = set()

    active_bullets = {}


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
                parts = data_str.split('|')
                if len(parts) > 1:
                    state.players_pos[client_id] = parts[1]
                    state.players_hp[client_id] = parts[2]
                else:
                    # Fallback if no position is provided
                    state.players_pos[client_id] = "0,0"
                    state.players_hp[client_id] = 100
                if client_id not in state.players_pos:
                    state.players_pos[client_id] = data_str.split('|')[1]
                    state.players_hp[client_id] = data_str.split('|')[2]

                    # 2. Tell the NEW player where EVERYONE ELSE is
                for other_id, pos in state.players_pos.items():
                    if other_id != client_id:
                        hp = state.players_hp.get(other_id)
                        sync_msg = f"UPDATE|{other_id}|{pos}|{hp}".encode()
                        self._quic.send_stream_data(0, sync_msg, end_stream=False)

                # 3. Tell EVERYONE ELSE that this new player has joined
                self.broadcast_player(client_id, state.players_pos[client_id],state.players_hp[client_id] , False)
                self.transmit()

            elif data_str.startswith("UPDATE|"): #tell everyone about player that moved
                new_pos =  data_str.split("|")[1]

                if check_movement(new_pos , state.players_pos[client_id]):
                    state.players_pos[client_id] = new_pos
                    #state.players_hp[client_id] = data_str.split("|")[2] #let the player change his hp
                    self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], False)
                else:
                    self.disconnect() #kick the player

            elif data_str.startswith("ATTACK|"):
                weapon =  data_str.split("|")[1]
                if weapon == "gun":
                    #set a bullet if
                    new_id = random.randint(1, 1000000)
                    while new_id not in state.active_bullets:
                        new_id = random.randint(1, 1000000)
                    state.active_bullets[new_id] = \
                    {
                        "x": data_str.split("|")[1].split(",")[0],
                        "y": data_str.split("|")[1].split(",")[1],
                        "angle": data_str.split("|")[2]
                    }

                    self.gun_tracking(new_id)


            elif data_str == "Disconnected":
                self.disconnect()
        elif isinstance(event, ConnectionTerminated):
            print("Client logged out")






    def broadcast_remove(self, client_id):
        message = f"REMOVE|{client_id}".encode("utf-8")
        for client in list(state.active_clients):
            client._quic.send_stream_data(0, message, end_stream=False)
            client.transmit()


    def  broadcast_player(self, sender_id, pos_str , hp, to_yourself):
        message = f"UPDATE|{sender_id}|{pos_str}|{hp}".encode("utf-8")

        for client in state.active_clients:
            # You can skip sending it back to the person who moved if you want:
            if client == self and not to_yourself: continue

            # Use stream 0 or a dedicated broadcast stream
            client._quic.send_stream_data(0, message, end_stream=False)
            client.transmit()


    def disconnect(self):
        client_id = self._quic.host_cid.hex()

        if client_id in state.players_pos:
            del state.players_pos[client_id]  # Remove from tracking

        if client_id in state.players_hp:
            del state.players_hp[client_id]  # Remove from tracking

        if self in state.active_clients:
            state.active_clients.remove(self)


        self.broadcast_remove(client_id) #tell everyone about the disconnection

    async def gun_tracking(self, bullet_id):

        x = state.active_bullets[bullet_id]["x"]
        y = state.active_bullets[bullet_id]["y"]
        angle = state.active_bullets[bullet_id]["angle"]

        x, y = get_next_bullet_position(x,y,angle)
        state.active_bullets[bullet_id]["x"] = x
        state.active_bullets[bullet_id]["y"] = y
        for player_id, pos_str in state.players_pos.items():
            player_x = float(pos_str.split(",")[0])
            player_y = float(pos_str.split(",")[1])
            if player_x==x and player_y==y:
                del state.active_bullets[bullet_id]
                self.damage(20)
    def damage(self, damage):
        client_id = self._quic.host_cid.hex()
        hp = state.players_hp[client_id]
        if hp - damage <= 0: #kill player
            self.broadcast_remove(client_id)
        else: #do the damage to the player
            state.players_hp[client_id] = hp - damage
            self.broadcast_player(client_id ,state.players_pos[client_id], state.players_hp[client_id], True)


def get_next_bullet_position(x, y, angle_degrees): #גמיני הגבר כתב
    # 1. המרה של הזווית ממעלות לרדיאנים (כי ככה פייתון עובד)
    angle_rad = math.radians(angle_degrees)

    # 2. חישוב כמה הכדור צריך לזוז בכל ציר
    delta_x = math.cos(angle_rad)
    delta_y = math.sin(angle_rad)

    # 3. חיבור התזוזה למיקום הנוכחי
    new_x = x + delta_x
    new_y = y + delta_y

    return new_x, new_y


def check_movement(new_pos , old_pos):
        new_x = new_pos.split(",")[0]
        new_y = new_pos.split(",")[1]
        old_x = old_pos.split(",")[0]
        old_y = old_pos.split(",")[1]


        if abs(new_x - old_x) <= 2: #the x movement was less than 3 blocks
            if abs(new_y - old_y) <= 2:#the y movement was less than 3 blocks
                return True


        return False #the movement isn't correct

async def main():
    # 1. Define the QUIC configuration
    configuration = QuicConfiguration(
        is_client=False,
        alpn_protocols=["echo-protocol"],# Custom protocol name
        verify_mode = False,
    )

    # 2. Load the SSL certificate and private key
    #configuration.load_cert_chain("../cert.pem", "key.pem")

    # 3. Start the server
    print("Starting QUIC server on udp:0.0.0.0:4433")
    await serve(
        host="0.0.0.0",
        port=4433,
        configuration=configuration,
        create_protocol=EchoQuicProtocol,
    )
    asyncio.create_task(check_cpu())
    # Keep the server running
    await asyncio.Future()

async def check_cpu():
    while True:
        cpu_usage = psutil.cpu_percent(interval=1.0)
        print(cpu_usage)

        await asyncio.sleep(20)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass