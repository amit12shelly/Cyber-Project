import asyncio
import math
import random
import psutil
import heapq

from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent, ConnectionTerminated

#----------server settings----------
INVENTORY_SIZE = 5
MAX_BULLETS = 1000
TILE_SIZE = 64
TOLERANCE = 70
BULLETS_MOVE_TIME = 0.007
MONSTERS_AMOUNT = 100
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
MAX_WEAPONS = 10000
AMOUNT_TO_DROP_IN_DEATH = 2
ENTITIES_SPEED = 4
WEAPON_LIST = [["gun", 20, TILE_SIZE * 10]]  #-> name,damage,range
WEAPON_NAMES = [w[0] for w in WEAPON_LIST]
WEAPON_DAMAGE = [w[1] for w in WEAPON_LIST]
WEAPON_RANGE = [w[2] for w in WEAPON_LIST]


def load_map():
    with open("map.txt", "r") as f:
        lines = f.readlines()
    return [list(line.strip()) for line in lines]


class GameState:
    #player info
    players_pos = {}  # client_id -> "x,y"
    players_hp = {}  # client_id -> hp
    players_inventory = {}  # client_id -> {slot 1, slot 2, slot 3 ,slot 4 ,slot 5}
    active_clients = set()  # set of EchoQuicProtocol
    active_bullets = {}  # bullet_id -> {x, y, angle}

    #game info
    map_weapons = {}  # weapon_id -> {x, y, type}
    game_map = load_map()

    #monsters info
    monsters = {}  #monster_id -> {x, y, hp}


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
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting Connected command!")
                return

            if len(parts) < 3:
                state.players_pos[client_id] = "0,0"
                state.players_hp[client_id] = "100"
            else:
                state.players_pos[client_id] = parts[1]
                state.players_hp[client_id] = parts[2]

            state.players_inventory[client_id] = {i: "none" for i in range(INVENTORY_SIZE)}

            id_msg = f"SETID|{client_id}\n".encode()
            if self.stream_id is not None:
                self._quic.send_stream_data(self.stream_id, id_msg, end_stream=False)

            # send existing players to new player
            for other_id, pos in state.players_pos.items():
                if other_id == client_id:
                    continue
                hp = state.players_hp.get(other_id, "100")
                msg = f"UPDATE|{other_id}|{pos}|{hp}\n".encode()
                if self.stream_id is not None:
                    self._quic.send_stream_data(self.stream_id, msg, end_stream=False)

            #send all the weapons positions
            for weapon_id, w_data in state.map_weapons.items():
                msg = f"DROPPED|{w_data['x']},{w_data['y']}|{w_data['type']}\n".encode()
                if self.stream_id is not None:
                    self._quic.send_stream_data(self.stream_id, msg, end_stream=False)

            # tell others about new player
            self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], False)
            self.transmit()

        # MOVEMENT
        elif data_str.startswith("UPDATE|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting UPDATE command!")
                return
            if len(parts) < 2:
                return
            new_pos = parts[1]

            if client_id not in state.players_pos:
                return
            for other_id, other_pos in list(state.players_pos.items()):
                if other_id == self._quic.host_cid.hex():
                    continue
                if other_pos == new_pos:
                    self.disconnect()  # kick the player
                    print("player has been kicked! player collision")
                    return

            if check_movement(new_pos, state.players_pos[client_id]):
                state.players_pos[client_id] = new_pos
                self.broadcast_player(client_id, new_pos, state.players_hp[client_id], False)
            else:
                self.disconnect() #kick the player
                print("player has been kicked! movement problem")

        # ATTACK
        elif data_str.startswith("ATTACK|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting ATTACK command!")
                return
            if len(parts) < 3:
                return
            weapon_slot = parts[1]
            weapon = state.players_inventory[client_id][int(weapon_slot)]
            if weapon in WEAPON_NAMES:
                new_id = random.randint(1, MAX_BULLETS)
                while new_id in state.active_bullets:
                    new_id = random.randint(1, MAX_BULLETS)

                pos_str = state.players_pos.get(client_id, "0,0")
                try:
                    x_str, y_str = pos_str.split(",")
                except:
                    print("Error while splitting the pos in the ATTACK command!")
                    return
                angle = float(parts[2])

                state.active_bullets[new_id] = {
                    "x": float(x_str),
                    "y": float(y_str),
                    "angle": angle,
                }

                print("shooting!")
                asyncio.create_task(self.gun_tracking(new_id, weapon))


        elif data_str.startswith("PICKUP|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting the PICKUP command!")
                return

            if len(parts) < 3:
                return

            pickup_pos = parts[1]
            pickup_type = parts[2]
            try:
                px = float(pickup_pos.split(",")[0])
                py = float(pickup_pos.split(",")[1])
            except:
                print("Error while splitting the pos in the PICKUP command!")
                return
            found_weapon_id = None

            if pickup_type in WEAPON_NAMES:
                for w_id, w_data in state.map_weapons.items():  # checks if this weapon in real
                    if w_data["type"] == pickup_type:
                        if abs(w_data["x"] - px) <= TOLERANCE and abs(w_data["y"] - py) <= TOLERANCE:
                            found_weapon_id = w_id
                            break

                if found_weapon_id is not None:  # if its real

                    for slot in range(INVENTORY_SIZE):

                        if state.players_inventory[self._quic.host_cid.hex()][slot] == "none":
                            state.players_inventory[self._quic.host_cid.hex()][slot] = pickup_type
                            pos_str = f"{state.map_weapons[found_weapon_id]['x']},{state.map_weapons[found_weapon_id]['y']}"
                            self.broadcast_undrop(pos_str, state.map_weapons[found_weapon_id]["type"])
                            del state.map_weapons[found_weapon_id]
                            break

                else:  # this weapon does not exist
                    self.disconnect()  # kick the player
                    print("player has been kicked! weapon id = none")

            else:  # this weapon does not exist
                self.disconnect()  # kick the player
                print("player has been kicked! this weapon does not exist")



        elif data_str.startswith("DROP|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting the DROP command!")
                return

            if len(parts) < 3:
                return
            pos_str = parts[1]
            try:
                x_str = pos_str.split(",")[0]
                y_str = pos_str.split(",")[1]
            except:
                print("Error while splitting the pos in the DROP command!")
                return
            weapon_slot = int(parts[2])
            drop = state.players_inventory[self._quic.host_cid.hex()][weapon_slot]
            if drop in WEAPON_NAMES:

                if drop != "none":  # if he has something to drop
                    state.players_inventory[self._quic.host_cid.hex()][weapon_slot] = "none"  # removing the weapon from the player inventory

                    new_id = random.randint(1, 1000000)
                    while new_id in state.map_weapons:
                        new_id = random.randint(1, 1000000)

                    state.map_weapons[new_id] = {  # drop this weapon
                        "x": float(x_str),
                        "y": float(y_str),
                        "type": drop,
                    }
                    # tell everyone about this drop
                    self.broadcast_drop(pos_str, drop)

                else:  # he wants to drop something that he doesn't have
                    self.disconnect()  # kick the player
                    print("player has been kicked! player does not have this weapon")

            else:  # he wants to drop something that the server don't recognize
                self.disconnect()  # kick the player
                print("player has been kicked! the server dont recognize this weapon")


        elif data_str.startswith("CHAT|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting the CHAT command!")
                return
            if len(parts) < 2:
                return

            msg = parts[1]
            client_id = self._quic.host_cid.hex()
            self.broadcast_chat(msg , client_id)


        # DISCONNECT
        elif data_str == "Disconnected":
            self.disconnect()
            print("player has been kicked! player disconnected")

    # ---------- Broadcast helpers ---------- #

    def broadcast_drop(self, pos_str, type_str):
        msg = f"DROPPED|{pos_str}|{type_str}\n".encode()
        for client in list(state.active_clients):
            if client == self:
                continue
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()
        print(msg)


    def broadcast_undrop(self, pos_str, type_str):
        msg = f"UNDROPPED|{pos_str}|{type_str}\n".encode()
        for client in list(state.active_clients):
            if client == self:
                continue
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()
        print(msg)


    def broadcast_chat(self, msg: str , client_id):
        msg = f"CHAT|{client_id}|{msg}\n".encode()
        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

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
        self.broadcast_remove(client_id)

        if client_id in state.players_pos:
            del state.players_pos[client_id]
        if client_id in state.players_hp:
            del state.players_hp[client_id]
        if client_id in state.players_inventory:
            del state.players_inventory[client_id]
        if self in state.active_clients:
            state.active_clients.remove(self)

        print(client_id, "disconnected")

    async def gun_tracking(self, bullet_id: int, gun_type):
        if bullet_id not in state.active_bullets:
            return

        x = state.active_bullets[bullet_id]["x"]
        y = state.active_bullets[bullet_id]["y"]
        angle = state.active_bullets[bullet_id]["angle"]
        gun_range = 0
        gun_damage = 0
        for i in range(len(WEAPON_NAMES)):
            if WEAPON_NAMES[i] == gun_type:
                gun_damage = int(WEAPON_DAMAGE[i])
                gun_range = int(WEAPON_RANGE[i])

        for _ in range(gun_range):
            x, y = get_next_bullet_position(x, y, angle)
            state.active_bullets[bullet_id]["x"] = x
            state.active_bullets[bullet_id]["y"] = y

            pos = f"{x},{y}"
            if not check_if_in_map(x, y):  #checks if the bullet got out of the map
                del state.active_bullets[bullet_id]
                return
            if state.game_map[int(y / TILE_SIZE)][int(x / TILE_SIZE)] == "#":  #checks if the bullet got into wall
                del state.active_bullets[bullet_id]
                return

            self.broadcast_show_bullet(pos)

            for player_id, pos_str in list(state.players_pos.items()):
                try:
                    px, py = map(float, pos_str.split(","))
                except:
                    print("Error while splitting the in the gun_tracking!")
                    return
                if abs(px - x) <= TOLERANCE and abs(py - y) <= TOLERANCE:
                    if player_id != self._quic.host_cid.hex():
                        del state.active_bullets[bullet_id]
                        self.damage(player_id, gun_damage)
                        return

            await asyncio.sleep(BULLETS_MOVE_TIME)

        if bullet_id in state.active_bullets:
            del state.active_bullets[bullet_id]

    def damage(self, client_id: str, damage: int):
        hp = int(state.players_hp.get(client_id))
        if hp - damage <= 0:
            pos = state.players_pos[client_id]
            dropped = 0
            inv_slot = 0
            while dropped < AMOUNT_TO_DROP_IN_DEATH and inv_slot < INVENTORY_SIZE:
                item = state.players_inventory[client_id].get(inv_slot)
                if item != "none":
                    new_id = random.randint(1, 1000000)
                    while new_id in state.map_weapons:
                        new_id = random.randint(1, 1000000)
                    try:
                        x = float(pos.split(",")[0])
                        y = float(pos.split(",")[1])
                    except:
                        print("Error while splitting the in the damage function!")
                        return
                    state.map_weapons[new_id] = {
                        "x": x,
                        "y": y,
                        "type": item
                    }
                    self.broadcast_drop(pos, item)
                    dropped += 1
                inv_slot += 1


            inv_slot = 0
            while inv_slot < INVENTORY_SIZE:
                state.players_inventory[client_id][inv_slot] = "none"
                inv_slot += 1

            self.broadcast_remove(client_id)
            state.players_pos[client_id] = "0,0"
            state.players_hp[client_id] = "100"
            print("player killed!")
            self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], True)
        else:
            state.players_hp[client_id] = hp - damage
            self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], True)


# ---------- Utils ---------- #
class Node:
  def __init__(self, data):
    self.data = data
    self.next = None

def pitagoras(x,y):
    return math.sqrt((x*x)+(y*y))

def check_if_in_map(x, y):
    x = int(float(x)/ TILE_SIZE)
    y = int(float(y) / TILE_SIZE)
    if y >= len(state.game_map):
        return False
    elif y < 0:
        return False
    elif x >= len(state.game_map[0]):
        return False
    elif x < 0:
        return False


    return True

def find_nearest_player(monster_x, monster_y):
    min_x = 10000000
    min_y = 10000000
    for other_id, pos in state.players_pos.items():
        player_x = pos.split(",")[0]
        player_y = pos.split(",")[1]
        if (player_x*player_x + player_y*player_y) < (min_x*min_x + min_y*min_y):
            min_x = player_x
            min_y = player_y
    return min_x, min_y

def find_neighbors(current_node, target):
    neighbor_nodes = []

    cx, cy, g = current_node.data[0], current_node.data[1], current_node.data[2]

    for i in range(3):
        for j in range(3):
            dx = (j-1) * ENTITIES_SPEED
            dy = (i-1) * ENTITIES_SPEED

            if dx == 0 and dy == 0:
                continue

            nx = cx + dx
            ny = cy + dy

            step_cost = pitagoras(dx, dy)
            G_cost = g + step_cost

            H_cost = pitagoras(target[0] - nx, target[1] - ny)
            F_cost = G_cost + H_cost

            neighbor_node = Node((nx, ny, G_cost, H_cost, F_cost))
            neighbor_node.next = current_node

            neighbor_nodes.append(neighbor_node)

    return neighbor_nodes

def A_star_algorythm(start, target):

    open_heap = []
    closed_set = set()

    start_h = pitagoras(target[0]-start[0], target[1]-start[1])
    start_node = Node((start[0], start[1], 0, start_h, start_h))

    heapq.heappush(open_heap, (start_node.data[4], start_node))

    while open_heap:

        _, current_node = heapq.heappop(open_heap)

        cx, cy = current_node.data[0], current_node.data[1]

        if (cx, cy) in closed_set:
            continue

        closed_set.add((cx, cy))

        if current_node.data[3] < TILE_SIZE:
            return current_node

        neighbors = find_neighbors(current_node, target)

        for neighbor in neighbors:

            nx, ny = neighbor.data[0], neighbor.data[1]

            # wall check can go here later
            # if is_wall(nx, ny): continue

            if (nx, ny) in closed_set:
                continue

            heapq.heappush(open_heap, (neighbor.data[4], neighbor))


def get_next_bullet_position(x, y, angle_degrees):
    angle_rad = math.radians(angle_degrees)
    return x + math.cos(angle_rad), y + math.sin(angle_rad)


def check_movement(new_pos, old_pos):
    try:
        new_x, new_y = map(float, new_pos.split(","))
        old_x, old_y = map(float, old_pos.split(","))
    except:
        print("Error while splitting the in the check_movement function!")
        return
    if check_if_in_map(new_x, new_y):
        if state.game_map[int(new_y / TILE_SIZE)][int(new_x / TILE_SIZE)] == ".":
            if abs(new_x - old_x) <= 8 and abs(new_y - old_y) <= 8:
                return True

    return False


def spawn_random_monsters(amount):
    tiles_high = len(state.game_map)
    tiles_wide = len(state.game_map[0])

    spawned = 0

    while spawned < amount:

        tile_x = random.randint(0, tiles_wide - 1)
        tile_y = random.randint(0, tiles_high - 1)

        if state.game_map[tile_y][tile_x] == ".":

            pixel_x = float(tile_x * TILE_SIZE)
            pixel_y = float(tile_y * TILE_SIZE)

            new_id = random.randint(1, 1000000)
            while new_id in state.monsters:
                new_id = random.randint(1, 1000000)

            state.monsters[new_id] = {
                "x": pixel_x,
                "y": pixel_y,
                "hp": 100
            }

            spawned += 1

    print(f"Server initialized with {spawned} monsters on the map.")


def spawn_loot_per_camera_zone(game_map, per_zone=2):
    """
    Spawn loot so that each camera-sized zone has at least per_zone items.
    """
    loot_list = []

    tiles_wide = len(game_map[0])
    tiles_high = len(game_map)

    zone_tiles_x = SCREEN_WIDTH // TILE_SIZE
    zone_tiles_y = SCREEN_HEIGHT // TILE_SIZE

    for win_y in range(0, tiles_high, zone_tiles_y):
        for win_x in range(0, tiles_wide, zone_tiles_x):
            spawned = 0
            attempts = 0
            while spawned < per_zone and attempts < 50:
                attempts += 1
                tile_x = random.randint(win_x, min(win_x + zone_tiles_x - 1, tiles_wide - 1))
                tile_y = random.randint(win_y, min(win_y + zone_tiles_y - 1, tiles_high - 1))

                if game_map[tile_y][tile_x] != "#":  # רק על רצפה
                    x = tile_x * TILE_SIZE
                    y = tile_y * TILE_SIZE
                    name = random.choice(WEAPON_NAMES)
                    loot_list.append((x, y, name))
                    #create an unic id
                    new_id = random.randint(1, int(MAX_WEAPONS))
                    while new_id in state.map_weapons:
                        new_id = random.randint(1, int(MAX_WEAPONS))
                    state.map_weapons[new_id] = {
                        "x": x,
                        "y": y,
                        "type": name
                    }

                    spawned += 1

def monsters_manager():
    while True:
        for i in range(MONSTERS_AMOUNT):
            monster_x = state.monsters[i+1]["x"]
            monster_y = state.monsters[i+1]["y"]
            player_x, player_y = find_nearest_player(monster_x, monster_y)
            monster_pos = monster_x + "," + monster_y
            player_pos = str(player_x) + "," + str(player_y)
            node = A_star_algorythm(monster_pos , player_pos)
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
    asyncio.create_task(serve(
        host="0.0.0.0",
        port=4433,
        configuration=config,
        create_protocol=EchoQuicProtocol,
    ))

    asyncio.create_task(check_cpu())
    await asyncio.Future()


if __name__ == "__main__":
    spawn_loot_per_camera_zone(state.game_map)
    spawn_random_monsters(MONSTERS_AMOUNT)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
