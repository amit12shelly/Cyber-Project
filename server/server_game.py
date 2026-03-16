import asyncio
import math
import random
import psutil
import heapq
import time

from itertools import count
from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent, ConnectionTerminated

#----------server settings----------
INVENTORY_SIZE = 5
UP_HP = 40
MAX_BULLETS = 1000
TILE_SIZE = 64
TOLERANCE = 70
RADIUS = 300
BULLETS_MOVE_TIME = 0.01
MONSTERS_AMOUNT = 3500
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
MAX_WEAPONS = 9000
AMOUNT_TO_DROP_IN_DEATH = 2
ENTITIES_SPEED = 4
WEAPON_LIST = [["gun", 20, TILE_SIZE * 10],["rifle" ,10 , TILE_SIZE * 20],["rpg",30,TILE_SIZE*25]] #-> name,damage,range
WEAPON_NAMES = [w[0] for w in WEAPON_LIST]
WEAPON_DAMAGE = [w[1] for w in WEAPON_LIST]
WEAPON_RANGE = [w[2] for w in WEAPON_LIST]
MONSTER_CHANGE_PATH_EVERY_SET_SECONDS = 3
MONSTER_ACCURACY = 65  # 1-100
MAX_POTION = 9000
POTION_LIST = [["Potion", 40],["Poison",5]] #-> name,hp++
counter = count()
monsters_list = []
SERVER_FPS = 0

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
    players_potions ={}

    #game info
    map_weapons = {}  # weapon_id -> {x, y, type}
    game_map = load_map()

    #monsters info
    monsters = {}  #monster_id -> {x, y, hp, path(A*), last_path_time(last time called A* for this monster)}
    map_potion = {}


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
        # CONNECTED
        client_id = self._quic.host_cid.hex()
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

            state.players_inventory[client_id] = {int(i): "none" for i in range(INVENTORY_SIZE)}
            state.players_potions[client_id] = 0

            id_msg = f"SETID|{client_id}\n".encode()
            if self.stream_id is not None:
                self._quic.send_stream_data(self.stream_id, id_msg, end_stream=False)

            # send existing players to new player
            for other_id, pos in state.players_pos.items():
                if other_id == self._quic.host_cid.hex():
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
            for potion_id,p_data in state.map_potion.items():
                msg = f"POTIONS|{p_data['x']},{p_data['y']}|{p_data['type']}\n".encode()
                if self.stream_id is not None:
                    self._quic.send_stream_data(self.stream_id, msg, end_stream=False)

            # tell others about new player
            self.broadcast_player(self._quic.host_cid.hex(), state.players_pos[self._quic.host_cid.hex()],
                                  state.players_hp[
                                      self._quic.host_cid.hex()], False)
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

            if self._quic.host_cid.hex() not in state.players_pos:
                return
            for other_id, other_pos in list(state.players_pos.items()):
                if other_id == self._quic.host_cid.hex():
                    continue
                if other_pos == new_pos:
                    self.disconnect()  # kick the player
                    print("player has been kicked! player collision")
                    return

            if check_movement(new_pos, state.players_pos[self._quic.host_cid.hex()]):
                state.players_pos[self._quic.host_cid.hex()] = new_pos
                self.broadcast_player(self._quic.host_cid.hex(), new_pos, state.players_hp[self._quic.host_cid.hex()],
                                      False)
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

                center_x = float(x_str) + 32
                center_y = float(y_str) + 32

                state.active_bullets[new_id] = {
                    "x": center_x+28,
                    "y": center_y-8,
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

        elif data_str.startswith("PPICKUP|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting the PPICKUP command!")
                return
            if len(parts) < 3:
                return
            pickup_pos = parts[1]
            pickup_type = parts[2]
            print(pickup_type)
            try:
                px = float(pickup_pos.split(",")[0])
                py = float(pickup_pos.split(",")[1])
            except:
                print("Error while splitting the pos in the PICKUP command!")
                return
            found_potion_id = None

            for p_id, p_data in state.map_potion.items():  # checks if this POTION IS  real
                    if abs(p_data["x"] - px) <= TOLERANCE and abs(p_data["y"] - py) <= TOLERANCE:
                        print(p_data["type"])
                        if p_data["type"] == pickup_type:
                            print("sup dog up the hp")
                            client_id = self._quic.host_cid.hex()
                            state.players_potions[client_id] += 1
                            # state.players_hp[client_id] = pickup_hp
                            found_potion_id = p_id
                            break
            if found_potion_id is not None:  # if its real
                pos_str = f"{state.map_potion[found_potion_id]['x']},{state.map_potion[found_potion_id]['y']}"
                self.broadcast_undrop(pos_str,pickup_type)
                self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id],False)
                del state.map_potion[found_potion_id]
            else:  # this weapon does not exist
                self.disconnect()  # kick the player
                print("player has been kicked! weapon id = none")

        elif data_str.startswith("USE|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting the USE command!")
                return
            if len(parts) < 2:
                return

            item_name = parts[1]
            client_id = self._quic.host_cid.hex()

            if client_id not in state.players_hp:
                return
            if state.players_potions[client_id] <= 0:
                return
            if item_name =="Potion":
                state.players_hp[client_id] += UP_HP

                if state.players_hp[client_id] > 100:
                    state.players_hp[client_id] = 100
                self.broadcast_player(client_id,state.players_pos[client_id],state.players_hp[client_id],True)
            elif item_name == "Poison":
                if len(parts) < 3:
                    return

                pos = parts[2]
                poison_x,poison_y = map(float,pos.split(","))

                self.broadcast_poison(poison_x, poison_y)

                async def poison_effect():
                    for _ in range(5):  # חמש פעמים, למשל 5 שניות בסך הכל
                        for p_id, p_pos in state.players_pos.items():
                            if p_id != client_id:
                                px, py = map(float, p_pos.split(","))
                                dx = px - poison_x
                                dy = py - poison_y
                                distance = (dx ** 2 + dy ** 2) ** 0.5
                                if distance <= RADIUS:
                                    self.damage(p_id, 5)
                        await asyncio.sleep(0.5)

                asyncio.create_task(poison_effect())  # מריצים את זה ברקע

            else:  # this weapon does not exist
                self.disconnect()  # kick the player
                print("player has been kicked! item name = none")


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
                    client_hex = self._quic.host_cid.hex()

                    # 1. במקום סתם לרוקן את הסלוט, מזיזים את כל הנשקים שאחריו מקום אחד שמאלה (כדי לסנכרן עם ה-pop בקליינט)
                    for i in range(weapon_slot, INVENTORY_SIZE - 1):
                        state.players_inventory[client_hex][i] = state.players_inventory[client_hex][i + 1]

                    # 2. מרוקנים את הסלוט האחרון לגמרי
                    state.players_inventory[client_hex][INVENTORY_SIZE - 1] = "none"

                    new_id = random.randint(1, 1000000)
                    while new_id in state.map_weapons:
                        new_id = random.randint(1, 1000000)

                    state.map_weapons[new_id] = {  # drop this weapon
                        "x": float(x_str),
                        "y": float(y_str),
                        "type": drop,
                    }
                    # tell everyone about this drop
                    self.broadcast_drop(pos_str, drop, False)

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

    def broadcast_drop(self, pos_str, type_str, to_yourself):
        msg = f"DROPPED|{pos_str}|{type_str}\n".encode()
        for client in list(state.active_clients):
            if client == self and to_yourself == False:
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

    def broadcast_show_bullet(self, pos: str ,angle: str, bullet_id: str):
        msg = f"SHOW-BULLET|{pos}|{angle}|{bullet_id}\n".encode()
        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

    def broadcast_del_bullet(self, id: str):
        msg = f"DEL-BULLET|{id}\n".encode()
        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

    def broadcast_poison(self, x, y):
        msg = f"POISON|{x},{y}\n".encode()
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
        if client_id in state.players_potions:
            del state.players_potions[client_id]
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
        pos = f"{x},{y}"
        self.broadcast_show_bullet(pos , angle , str(bullet_id))
        for _ in range(gun_range):
            x, y = get_next_bullet_position(x, y, angle)
            state.active_bullets[bullet_id]["x"] = x
            state.active_bullets[bullet_id]["y"] = y

            pos = f"{x},{y}"
            if not check_if_in_map(x, y):  #checks if the bullet got out of the map
                del state.active_bullets[bullet_id]
                self.broadcast_del_bullet(str(bullet_id))
                return
            if state.game_map[int(y / TILE_SIZE)][int(x / TILE_SIZE)] == "#":  #checks if the bullet got into wall
                del state.active_bullets[bullet_id]
                self.broadcast_del_bullet(str(bullet_id))
                return



            for player_id, pos_str in list(state.players_pos.items()):
                try:
                    px, py = map(float, pos_str.split(","))
                except:
                    print("Error while splitting the in the gun_tracking!")
                    return
                if abs(px - x) <= TOLERANCE and abs(py - y) <= TOLERANCE:
                    if player_id != self._quic.host_cid.hex():
                        del state.active_bullets[bullet_id]
                        self.broadcast_del_bullet(str(bullet_id))
                        self.damage(player_id, gun_damage)
                        return


            for monster in monsters_list:
                try:
                    px = monster.x
                    py = monster.y
                except:
                    print("Error while splitting the in the gun_tracking!")
                    return
                if abs(px - x) <= TOLERANCE and abs(py - y) <= TOLERANCE:
                    del state.active_bullets[bullet_id]
                    self.broadcast_del_bullet(str(bullet_id))
                    monster.take_damage(gun_damage)
                    return

            await asyncio.sleep(BULLETS_MOVE_TIME)

        if bullet_id in state.active_bullets:
            del state.active_bullets[bullet_id]
            self.broadcast_del_bullet(str(bullet_id))

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
                    self.broadcast_drop(pos, item, True)
                    dropped += 1
                inv_slot += 1

            self.broadcast_remove(client_id)

            if client_id in state.players_pos:
                del state.players_pos[client_id]
            if client_id in state.players_hp:
                del state.players_hp[client_id]
            if client_id in state.players_inventory:
                del state.players_inventory[client_id]
            client_to_remove = None
            for client in state.active_clients:
                if client._quic.host_cid.hex() == client_id:
                    client_to_remove = client
                    break

            if client_to_remove:
                state.active_clients.remove(client_to_remove)
            print("player killed!")
        else:
            state.players_hp[client_id] = hp - damage
            self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], True)


# ---------- Utils ---------- #
class Node:
  def __init__(self, data):
    self.data = data
    self.next = None


class Monster:
    def __init__(self, x, y, hp):
        self.hp = hp
        self.weapon = random.choice(WEAPON_LIST)
        self.x = x
        self.y = y
        self.nearest_player = find_nearest_player(self.x, self.y)

        if self.nearest_player:
            self.path = A_star_algorythm((self.x, self.y), self.nearest_player, TILE_SIZE)
        else:
            self.path = None

        self.last_path_time = time.time()
        # מונע מצב שכל המפלצות יורות באותה אלפית שנייה כשהן נוצרות
        self.last_shot_time = time.time() - random.uniform(0, 2)

    def take_damage(self, damage):
        self.hp -= damage
        if self.hp <= 0:
            death_x = self.x
            death_y = self.y

            tiles_high = len(state.game_map)
            tiles_wide = len(state.game_map[0])
            tile_x = random.randint(0, tiles_wide - 1)
            tile_y = random.randint(0, tiles_high - 1)
            pixel_x = float(tile_x * TILE_SIZE)
            pixel_y = float(tile_y * TILE_SIZE)

            self.x = pixel_x
            self.y = pixel_y

            while state.game_map[tile_y][tile_x] != ".":
                tile_x = random.randint(0, tiles_wide - 1)
                tile_y = random.randint(0, tiles_high - 1)
                pixel_x = float(tile_x * TILE_SIZE)
                pixel_y = float(tile_y * TILE_SIZE)
                self.x = pixel_x
                self.y = pixel_y

            self.hp = 100
            self.weapon = random.choice(WEAPON_LIST)
            self.nearest_player = find_nearest_player(self.x, self.y)

            if self.nearest_player:
                self.path = A_star_algorythm((self.x, self.y), self.nearest_player, TILE_SIZE)
            else:
                self.path = None

            self.last_path_time = time.time()
            self.last_shot_time = time.time()

            #drop 2 items when monster die
            for i in range(1):
                item = random.choice(POTION_LIST)
                new_id = random.randint(1, int(MAX_POTION))
                while new_id in state.map_potion:
                    new_id = random.randint(1, int(MAX_POTION))
                state.map_potion[new_id] = {"x": death_x,"y": death_y,"type": item[0]}

                for client in list(state.active_clients):
                    if client.stream_id is not None:
                        item_type = item[0]
                        msg = f"ITEMS|{death_x},{death_y}|{item_type}\n".encode()
                        client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
                        client.transmit()

async def monster_gun_tracking(bullet_id: int, gun_type: str, start_x: float, start_y: float, angle: float):
    if bullet_id not in state.active_bullets:
        return

    gun_range = 0
    gun_damage = 0
    for i in range(len(WEAPON_NAMES)):
        if WEAPON_NAMES[i] == gun_type:
            gun_damage = int(WEAPON_DAMAGE[i])
            gun_range = int(WEAPON_RANGE[i])

    x = start_x
    y = start_y
    pos = f"{x},{y}"

    # משדרים לכולם שנוצר כדור חדש
    msg_show = f"SHOW-BULLET|{pos}|{angle}|{bullet_id}\n".encode()
    for client in list(state.active_clients):
        if client.stream_id is not None:
            client._quic.send_stream_data(client.stream_id, msg_show, end_stream=False)
            client.transmit()

    for _ in range(gun_range):
        x, y = get_next_bullet_position(x, y, angle)
        if bullet_id in state.active_bullets:
            state.active_bullets[bullet_id]["x"] = x
            state.active_bullets[bullet_id]["y"] = y

        # עצירה כשהכדור פוגע בקיר או יוצא מהמפה
        if not check_if_in_map(x, y):
            break
        if state.game_map[int(y / TILE_SIZE)][int(x / TILE_SIZE)] == "#":
            break

        hit_player = False

        # בדיקת פגיעה בשחקנים
        for player_id, pos_str in list(state.players_pos.items()):
            try:
                px, py = map(float, pos_str.split(","))
            except:
                continue

            if abs(px - x) <= TOLERANCE and abs(py - y) <= TOLERANCE:
                hit_player = True
                # מחפשים את החיבור של השחקן כדי להוריד לו חיים בעזרת מערכת הנזק הקיימת
                for client in list(state.active_clients):
                    if client._quic.host_cid.hex() == player_id:
                        client.damage(player_id, gun_damage)
                        break
                break

        if hit_player:
            break

        await asyncio.sleep(BULLETS_MOVE_TIME)

    # מוחקים את הכדור מהרשימה ומשדרים מחיקה לכולם
    if bullet_id in state.active_bullets:
        del state.active_bullets[bullet_id]

    msg_del = f"DEL-BULLET|{bullet_id}\n".encode()
    for client in list(state.active_clients):
        if client.stream_id is not None:
            client._quic.send_stream_data(client.stream_id, msg_del, end_stream=False)
            client.transmit()


def pitagoras(x,y):
    return math.sqrt((x*x)+(y*y))

def reverse_node_chain(node):
    prev = None
    current = node

    while current:
        nxt = current.next
        current.next = prev
        prev = current
        current = nxt

    return prev

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
    # אם אין שחקנים מחוברים, אין את מי לחפש
    if not state.players_pos:
        return None

    min_dist = float('inf')
    closest_player = None

    for other_id, pos in state.players_pos.items():
        try:
            player_x = float(pos.split(",")[0])
            player_y = float(pos.split(",")[1])
        except:
            continue

        # חישוב מרחק מהמפלצת (ולא מ-0,0)
        dist = (player_x - monster_x) ** 2 + (player_y - monster_y) ** 2

        if dist < min_dist:
            min_dist = dist
            closest_player = (player_x, player_y)

    return closest_player

def check_if_in_map_for_monster(x, y):
    """Return True if monster's position is inside map bounds."""
    x_tile = int(x / TILE_SIZE)
    y_tile = int(y / TILE_SIZE)
    return 0 <= y_tile < len(state.game_map) and 0 <= x_tile < len(state.game_map[0])



def A_star_algorythm(start, target, desired_range):
    # OPEN //the set of nodes to be evaluated
    open_heap = []
    open_dict = {}  # Keeps track of the best g_cost for nodes in OPEN: { (x,y): g_cost }

    # CLOSED //the set of nodes already evaluated
    closed_set = set()

    start_h = pitagoras(target[0] - start[0], target[1] - start[1])
    # Node data structure: (x, y, g_cost, h_cost, f_cost)
    start_node = Node((start[0], start[1], 0, start_h, start_h))

    # add the start node to OPEN
    heapq.heappush(open_heap, (start_node.data[4], next(counter), start_node))
    open_dict[(start[0], start[1])] = 0

    iterations = 0
    MAX_ITERATIONS = 400

    # loop
    while open_heap and iterations < MAX_ITERATIONS:
        iterations += 1
        # current = node in OPEN with the lowest f_cost
        _, _, current_node = heapq.heappop(open_heap)
        cx, cy, cg = current_node.data[0], current_node.data[1], current_node.data[2]

        # remove current from OPEN
        if (cx, cy) in closed_set:
            continue

        # add current to CLOSED
        closed_set.add((cx, cy))

        # התיקון הקריטי: desired_range מגיע כבר בפיקסלים מהנשק, אז לא צריך להכפיל שוב
        if current_node.data[3] <= desired_range:
            path = reverse_node_chain(current_node)
            return path.next if path and path.next else current_node

        # foreach neighbour of the current node
        for dx in [-TILE_SIZE, 0, TILE_SIZE]:
            for dy in [-TILE_SIZE, 0, TILE_SIZE]:
                if dx == 0 and dy == 0:
                    continue

                nx, ny = cx + dx, cy + dy

                # if neighbour is not traversable or neighbour is in CLOSED
                if not check_if_in_map_for_monster(nx, ny):
                    continue
                row, col = int(ny / TILE_SIZE), int(nx / TILE_SIZE)
                if state.game_map[row][col] == "#":
                    continue
                if (nx, ny) in closed_set:
                    continue

                # Calculate distances and costs
                step_cost = pitagoras(dx, dy)
                new_g = cg + step_cost
                h_cost = pitagoras(target[0] - nx, target[1] - ny)
                new_f = new_g + h_cost

                # if new path to neighbour is shorter OR neighbour is not in OPEN
                if (nx, ny) not in open_dict or new_g < open_dict[(nx, ny)]:
                    open_dict[(nx, ny)] = new_g

                    neighbor_node = Node((nx, ny, new_g, h_cost, new_f))
                    neighbor_node.next = current_node

                    heapq.heappush(open_heap, (new_f, next(counter), neighbor_node))

    return None

def get_next_bullet_position(x, y, angle_degrees):
    angle_rad = math.radians(angle_degrees)
    return x + math.cos(angle_rad)*15 , y + math.sin(angle_rad)*15


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
    global monsters_list
    monsters_list = []

    spawned = 0

    while spawned < amount:

        tile_x = random.randint(0, tiles_wide - 1)
        tile_y = random.randint(0, tiles_high - 1)

        if state.game_map[tile_y][tile_x] == ".":

            pixel_x = float(tile_x * TILE_SIZE)
            pixel_y = float(tile_y * TILE_SIZE)

            monster = Monster(pixel_x, pixel_y, 100)
            monsters_list.append(monster)

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

def spawn_potions_per_camera_zone(game_map, per_zone=2):
    """
    Spawn items so that each camera-sized zone has at least `per_zone` items.
    מוסיף ישר ל-state.map_items עם ID ייחודי ומיקום.
    """
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

                # רק על רצפה
                if game_map[tile_y][tile_x] != "#":
                    x = tile_x * TILE_SIZE
                    y = tile_y * TILE_SIZE

                    # צור מזהה ייחודי
                    new_id = random.randint(1, int(MAX_POTION))
                    while new_id in state.map_potion:
                        new_id = random.randint(1, int(MAX_POTION))

                    item = POTION_LIST[0]
                    # הכנס למפה
                    state.map_potion[new_id] = {
                        "x": x,
                        "y": y,
                        "type":item[0]
                    }

                    spawned += 1
async def monsters_manager():
    """Continuously update monsters' positions efficiently and handle shooting."""
    global monsters_list
    if not monsters_list:
        return

    while True:
        now = time.time()

        for i, monster in enumerate(monsters_list):
            if monster is None:
                continue

            monster.nearest_player = find_nearest_player(monster.x, monster.y)

            if not monster.nearest_player:
                monster.path = None
                continue

            dist_to_player = pitagoras(monster.x - monster.nearest_player[0], monster.y - monster.nearest_player[1])

            if dist_to_player > 1500:
                monster.path = None
                continue

            # --- הגיון הלחימה של המפלצת ---
            # אם השחקן בטווח הנשק של המפלצת
            if dist_to_player <= monster.weapon[2]:

                # המפלצת יורה רק כל 3.5 עד 5.5 שניות (זמן אקראי)
                if now - monster.last_shot_time >= random.uniform(3.5, 5.5):

                    # מחשבים את הזווית המדויקת אל השחקן
                    angle = math.degrees(
                        math.atan2(monster.nearest_player[1] - monster.y, monster.nearest_player[0] - monster.x))

                    # --- יישום הדיוק לפי המשתנה הגלובלי ---
                    # מחשבים את זווית הסטייה המקסימלית:
                    # אם הדיוק הוא 100, הסטייה היא 0. אם הדיוק 65, הסטייה היא 14 מעלות.
                    max_deviation = (100 - MONSTER_ACCURACY) * 0.4
                    angle += random.uniform(-max_deviation, max_deviation)

                    new_id = random.randint(1, MAX_BULLETS)
                    while new_id in state.active_bullets:
                        new_id = random.randint(1, MAX_BULLETS)

                    state.active_bullets[new_id] = {
                        "x": monster.x,
                        "y": monster.y,
                        "angle": angle,
                    }

                    # משגרים את הכדור
                    asyncio.create_task(monster_gun_tracking(new_id, monster.weapon[0], monster.x, monster.y, angle))
                    monster.last_shot_time = now

            # --- הגיון התזוזה של המפלצת ---
            if (
                    monster.path is None
                    or now - monster.last_path_time >= MONSTER_CHANGE_PATH_EVERY_SET_SECONDS
            ):
                new_path = A_star_algorythm((monster.x, monster.y), monster.nearest_player, TILE_SIZE)
                monster.path = new_path
                monster.last_path_time = now

            if monster.path:
                monster.x = monster.path.data[0]
                monster.y = monster.path.data[1]
                monster.path = monster.path.next

            if i % 50 == 0:
                await asyncio.sleep(0)

        broadcast_visible_monsters()
        await asyncio.sleep(0.5)

def broadcast_visible_monsters():
    half_width = (SCREEN_WIDTH / 2) + TILE_SIZE
    half_height = (SCREEN_HEIGHT / 2) + TILE_SIZE

    for client in list(state.active_clients):
        if client.stream_id is None:
            continue

        client_id = client._quic.host_cid.hex()
        if client_id not in state.players_pos:
            continue

        try:
            px, py = map(float, state.players_pos[client_id].split(","))
        except:
            continue

        client_monster_msg = ""
        for monster in monsters_list:
            if monster is None:
                continue

            # בודקים אם המפלצת נמצאת בתוך טווח המצלמה של השחקן הזה
            if abs(monster.x - px) <= half_width and abs(monster.y - py) <= half_height:
                client_monster_msg += f"|{monster.x},{monster.y},{monster.hp}"

        # שולחים רק למחשב הספציפי הזה.
        # (אם אין מפלצות סביבו, הוא יקבל "MONSTERS" נקי, מה שיאמר לקליינט למחוק מפלצות מהמסך)
        msg = f"MONSTERS{client_monster_msg}\n".encode()
        client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
        client.transmit()
# ---------- Server entry ---------- #

async def check_cpu():
    while True:
        print("CPU:", psutil.cpu_percent(interval=1.0))
        await asyncio.sleep(20)


async def track_server_fps():
    global SERVER_FPS
    fps_counter = 0
    loop_counter = 0
    last_time = time.time()

    while True:
        while loop_counter < 30:
            fps_counter += 1
            loop_counter += 1
            now = time.time()

            if now - last_time >= 1.0:
                SERVER_FPS = fps_counter

                print(f"[Server Health] FPS/FPS: {SERVER_FPS} / 60")
                fps_counter = 0
                last_time = now

            await asyncio.sleep(1 / 60)
        loop_counter = 0
        broadcast_fps()

def broadcast_fps():
    msg = f"FPS|{SERVER_FPS}\n".encode()
    for client in list(state.active_clients):
        if client.stream_id is None:
            continue
        client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
        client.transmit()

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
    asyncio.create_task(monsters_manager())
    asyncio.create_task(track_server_fps())
    await asyncio.Future()


if __name__ == "__main__":
    spawn_loot_per_camera_zone(state.game_map)
    spawn_random_monsters(MONSTERS_AMOUNT)
    spawn_potions_per_camera_zone(state.game_map)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass