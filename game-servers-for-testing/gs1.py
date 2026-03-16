import asyncio
import math
import random
import psutil
import heapq
import time

import pygame

from server import gs_and_lb_helper_functions
from itertools import count
from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, QuicEvent, ConnectionTerminated

# ----------server settings----------
INVENTORY_SIZE = 5
MAX_BULLETS = 1000
TILE_SIZE = 64
TOLERANCE = 70
BULLETS_MOVE_TIME = 0.01
MONSTERS_AMOUNT = 2000
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
MAX_WEAPONS = 9000
AMOUNT_TO_DROP_IN_DEATH = 2
ENTITIES_SPEED = 4
WEAPON_LIST = [["gun", 20, TILE_SIZE * 10], ["rifle", 10, TILE_SIZE * 20], ["rpg", 30, TILE_SIZE * 25],
               ["knife", 35, 5]]  # -> name,damage,range
WEAPON_NAMES = [w[0] for w in WEAPON_LIST]
WEAPON_DAMAGE = [w[1] for w in WEAPON_LIST]
WEAPON_RANGE = [w[2] for w in WEAPON_LIST]
BOMB_WEAPON = ["bomb", 35, 15]
MONSTER_CHANGE_PATH_EVERY_SET_SECONDS = 3
MONSTER_ACCURACY = 65  # 1-100
MAX_POTION = 9000
POTION_LIST = [["potion", 40]]  # -> name,hp++
counter = count()
monsters_list = []
SERVER_FPS = 0
SKILL_COOL_TIME = 12

LB_PORT = 8080

MY_IP = gs_and_lb_helper_functions.get_local_ip()
MY_PORT = 4434

P2P_PORT_OFFSET = 4000


def load_map():
    with open("map.txt", "r") as f:
        lines = f.readlines()
    return [list(line.strip()) for line in lines]


class GameState:
    def __init__(self):
        # ----- Load balancer info -----
        self.lb_host = None
        self.lb_port = LB_PORT
        self.lb_writer = None

        self.server_id = None
        self.server_area = None
        self.neighbor_conns = {}

        # ------ Game server neighbors -----
        self.neighbor = {}  # left -> x,ip,port /right -> x,ip,port

        # ----- players info -----
        self.ghost_players = {}
        self.players_pos = {}  # client_id -> "x,y"
        self.players_hp = {}  # client_id -> hp
        self.players_inventory = {}  # client_id -> {slot1..slot5}
        self.active_clients = set()  # set of EchoQuicProtocol
        self.active_bullets = {}  # bullet_id -> {x, y, angle}
        self.players_skills = {}

        # ----- game info -----
        self.map_weapons = {}  # weapon_id -> {x, y, type}
        self.game_map = load_map()

        # ----- monsters info -----
        self.monsters = {}  # monster_id -> {x, y, hp, path, last_path_time}
        self.map_potion = {}


state = GameState()


class EchoQuicProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        state.active_clients.add(self)
        self.stream_id = None
        self.recv_buffer = ""  # for newline-delimited messages

    def broadcast_remove_player(self, client_id):
        msg = f"REMOVE_PLAYER|{client_id}\n".encode()
        for client in state.active_clients:
            try:
                client._quic.send_stream_data(client.stream_id, msg)
                client.transmit()
            except:
                pass

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
        if data_str.startswith("Connected"):
            print(client_id, "connected!")
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting Connected command!")
                return

            current_skill = Skill("Speed Boost", 5, 0, False)

            state.players_skills[client_id] = current_skill
            if len(parts) < 3:
                state.players_pos[client_id] = "0,0"
                state.players_hp[client_id] = "100"
            else:
                state.players_pos[client_id] = parts[1]
                state.players_hp[client_id] = parts[2]

            state.players_inventory[client_id] = {int(i): "none" for i in range(INVENTORY_SIZE)}

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

            # send all the weapons positions
            for weapon_id, w_data in state.map_weapons.items():
                msg = f"DROPPED|{w_data['x']},{w_data['y']}|{w_data['type']}\n".encode()
                if self.stream_id is not None:
                    self._quic.send_stream_data(self.stream_id, msg, end_stream=False)
            for potion_id, p_data in state.map_potion.items():
                msg = f"POTIONS|{p_data['x']},{p_data['y']}\n".encode()
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
                if len(parts) < 2: return

                new_pos = parts[1]
                client_id = self._quic.host_cid.hex()

                # 1. אימות בסיסי
                if client_id not in state.players_pos: return

                if check_movement(new_pos, state.players_pos[self._quic.host_cid.hex()],
                                  state.players_skills[self._quic.host_cid.hex()]):
                    state.players_pos[self._quic.host_cid.hex()] = new_pos
                    self.broadcast_player(self._quic.host_cid.hex(), new_pos,
                                          state.players_hp[self._quic.host_cid.hex()],
                                          False)
                else:
                    self.disconnect()  # kick the player
                    print("player has been kicked! movement problem")
                    return

                # 2. עדכון המיקום בשרת המקומי
                state.players_pos[client_id] = new_pos
                px, _ = map(float, new_pos.split(","))

                # 3. בדיקת תחומי אחריות
                if state.server_area:
                    core_min = state.server_area["t-l"][0]
                    core_max = state.server_area["t-r"][0]
                    overlap = 500

                    # --- לוגיקת Handoff (מעבר שרת) ---
                    if px < core_min or px > core_max:
                        direction = "left" if px < core_min else "right"
                        neighbor = state.neighbor.get(direction)

                        if neighbor:
                            # 1. שלח הודעת ניקוי לשכנים
                            for side in ["left", "right"]:
                                n = state.neighbor.get(side)
                                if n:
                                    asyncio.create_task(send_to_neighbor(n['id'], f"REMOVE_GHOST|{client_id}\n"))

                            # 2. בצע את ה-SWITCH
                            switch_msg = f"SWITCH|{neighbor['ip']}|{neighbor['port']}\n".encode()
                            self._quic.send_stream_data(self.stream_id, switch_msg)
                            self.transmit()

                            # 3. ניקוי מקומי וניתוק
                            self.disconnect()
                            return

                    in_left_zone = px < (core_min + overlap)
                    in_right_zone = px > (core_max - overlap)

                    if in_left_zone or in_right_zone:
                        side = "left" if in_left_zone else "right"
                        neighbor = state.neighbor.get(side)
                        if neighbor:
                            ghost_msg = f"GHOST_UPDATE|{client_id}|{new_pos}|{state.players_hp[client_id]}\n"
                            asyncio.create_task(send_to_neighbor(neighbor['id'], ghost_msg))
                    else:
                        for side in ["left", "right"]:
                            neighbor = state.neighbor.get(side)
                            if neighbor:
                                remove_ghost_msg = f"REMOVE_GHOST|{client_id}\n"
                                asyncio.create_task(send_to_neighbor(neighbor['id'], remove_ghost_msg))

                self.broadcast_player(client_id, new_pos, state.players_hp[client_id], False)

            except Exception as e:
                print(f"Error in UPDATE logic: {e}")

        # ATTACK
        elif data_str.startswith("ATTACK|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting ATTACK command!")
                return
            if len(parts) < 3:
                return

            can_use_bombs = False

            if state.players_skills[client_id].name == "Bombs" and state.players_skills[client_id].is_active == True:
                weapon = "bomb"
                can_use_bombs = True
                print("bomb throw")
            else:
                weapon_slot = parts[1]
                weapon = state.players_inventory[client_id][int(weapon_slot)]

            if weapon in WEAPON_NAMES or can_use_bombs:
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
                    "x": center_x + 28,
                    "y": center_y - 8,
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
                for w_id, w_data in state.map_weapons.items():
                    if w_data["type"] == pickup_type:
                        if abs(w_data["x"] - px) <= TOLERANCE and abs(w_data["y"] - py) <= TOLERANCE:
                            found_weapon_id = w_id
                            break

                if found_weapon_id is not None:

                    for slot in range(INVENTORY_SIZE):

                        if state.players_inventory[self._quic.host_cid.hex()][slot] == "none":
                            state.players_inventory[self._quic.host_cid.hex()][slot] = pickup_type
                            pos_str = f"{state.map_weapons[found_weapon_id]['x']},{state.map_weapons[found_weapon_id]['y']}"
                            self.broadcast_undrop(pos_str, state.map_weapons[found_weapon_id]["type"])
                            del state.map_weapons[found_weapon_id]
                            break
                else:
                    self.disconnect()
                    print("player has been kicked! weapon id = none")

            else:
                self.disconnect()
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
            pickup_hp = parts[2]
            try:
                px = float(pickup_pos.split(",")[0])
                py = float(pickup_pos.split(",")[1])
            except (ValueError, IndexError):
                print("Error while splitting the pos in the PICKUP command!")
                return
            found_potion_id = None

            for p_id, p_data in state.map_potion.items():
                if abs(p_data["x"] - px) <= TOLERANCE and abs(p_data["y"] - py) <= TOLERANCE:
                    print("sup dog up the hp")
                    client_id = self._quic.host_cid.hex()
                    state.players_hp[client_id] = pickup_hp
                    found_potion_id = p_id
                    break
            if found_potion_id is not None:
                pos_str = f"{state.map_potion[found_potion_id]['x']},{state.map_potion[found_potion_id]['y']}"
                self.broadcast_undrop(pos_str, "potion")
                self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id])
                del state.map_potion[found_potion_id]
            else:
                self.disconnect()
                print("player has been kicked! weapon id = none")


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

                if drop != "none":
                    client_hex = self._quic.host_cid.hex()

                    for i in range(weapon_slot, INVENTORY_SIZE - 1):
                        state.players_inventory[client_hex][i] = state.players_inventory[client_hex][i + 1]

                    state.players_inventory[client_hex][INVENTORY_SIZE - 1] = "none"

                    new_id = random.randint(1, 1000000)
                    while new_id in state.map_weapons:
                        new_id = random.randint(1, 1000000)

                    state.map_weapons[new_id] = {
                        "x": float(x_str),
                        "y": float(y_str),
                        "type": drop,
                    }
                    self.broadcast_drop(pos_str, drop, False)

                else:
                    self.disconnect()
                    print("player has been kicked! player does not have this weapon")

            else:
                self.disconnect()
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
            self.broadcast_chat(msg, client_id)

        elif data_str.startswith("SKILL|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting the SKILL command!")
                return
            if len(parts) < 3:
                return

            try:
                sent_skill = skills_dict[parts[1]]
            except:
                self.disconnect()
                return
            click_time = float(parts[2])
            elapsed_since_last_press = click_time - state.players_skills[client_id].last_action_time
            required_time = state.players_skills[client_id].duration_time + SKILL_COOL_TIME

            if elapsed_since_last_press >= required_time:
                state.players_skills[client_id] = sent_skill
                state.players_skills[client_id].last_action_time = click_time
                state.players_skills[client_id].is_active = True
                print("Skill Activated!")
                self.broadcast_skill(client_id, state.players_skills[client_id], False)
                asyncio.create_task(state.players_skills[client_id].timer(client_id, self.broadcast_skill))
            else:
                print("Skill issue!")

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

    def broadcast_undrop(self, pos_str, type_str):
        msg = f"UNDROPPED|{pos_str}|{type_str}\n".encode()
        for client in list(state.active_clients):
            if client == self:
                continue
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

    def broadcast_chat(self, msg: str, client_id):
        msg = f"CHAT|{client_id}|{msg}\n".encode()
        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

    def broadcast_show_bullet(self, pos: str, angle: str, bullet_id: str, bullet_type: str):
        msg = f"SHOW-BULLET|{pos}|{angle}|{bullet_id}|{bullet_type}\n".encode()
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

    def broadcast_remove(self, client_id: str):
        msg = f"REMOVE|{client_id}\n".encode()
        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

    def broadcast_player(self, client_id, pos, hp, is_dead=False):
        msg = f"PLAYER_UPDATE|{client_id}|{pos}|{hp}|{is_dead}\n".encode()
        for client in list(state.active_clients):
            if client.stream_id is not None:
                try:
                    client._quic.send_stream_data(client.stream_id, msg)
                    client.transmit()
                except:
                    continue

    def broadcast_ghosts(self):
        for g_id, g_data in state.ghost_players.items():
            g_msg = f"PLAYER_UPDATE|{g_id}|{g_data['pos']}|{g_data['hp']}|False\n".encode()
            for client in list(state.active_clients):
                if client.stream_id is not None:
                    try:
                        client._quic.send_stream_data(client.stream_id, g_msg)
                        client.transmit()
                    except:
                        continue

    def broadcast_skill(self, sender_id: str, skill, to_yourself: bool):
        msg = f"SKILL|{sender_id}|{skill.name}|{skill.is_active}\n".encode()
        for client in list(state.active_clients):
            if client == self and not to_yourself:
                continue
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

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
        if client_id in state.players_skills:
            del state.players_skills[client_id]
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
        if gun_type == "bomb":
            gun_damage = BOMB_WEAPON[1]
            gun_range = BOMB_WEAPON[2]
        else:
            for i in range(len(WEAPON_NAMES)):
                if WEAPON_NAMES[i] == gun_type:
                    gun_damage = int(WEAPON_DAMAGE[i])
                    gun_range = int(WEAPON_RANGE[i])
                    break
        pos = f"{x},{y}"
        self.broadcast_show_bullet(pos, angle, str(bullet_id), "bomb" if gun_type == "bomb" else "bullet")

        # תיקון מהירות התנועה - פצצה זזה לאט, נשק רגיל זז מהר
        speed = 8 if gun_type == "bomb" else 15

        for _ in range(gun_range):
            x, y = get_next_bullet_position(x, y, angle, speed)
            state.active_bullets[bullet_id]["x"] = x
            state.active_bullets[bullet_id]["y"] = y

            pos = f"{x},{y}"
            if not check_if_in_map(x, y):
                del state.active_bullets[bullet_id]
                self.broadcast_del_bullet(str(bullet_id))
                return
            if state.game_map[int(y / TILE_SIZE)][int(x / TILE_SIZE)] == "#":
                del state.active_bullets[bullet_id]
                self.broadcast_del_bullet(str(bullet_id))
                return

            for player_id, pos_str in list(state.players_pos.items()):
                try:
                    px, py = map(float, pos_str.split(","))
                except:
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
        if state.players_skills[client_id].name == 'Shield' and state.players_skills[client_id].is_active:
            print("shield protection")
            return
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
            if client_id in state.players_skills:
                del state.players_skills[client_id]
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
            self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], False)


# ---------- Utils ---------- #
class Node:
    def __init__(self, data):
        self.data = data
        self.next = None


class Skill:
    def __init__(self, name, duration_time, last_action_time, is_active):
        self.name = name
        self.duration_time = duration_time
        self.last_action_time = last_action_time
        self.is_active = is_active

    async def timer(self, client_id, broadcast_skill):
        await asyncio.sleep(self.duration_time)
        self.is_active = False
        state.players_skills[client_id] = self
        broadcast_skill(client_id, self, False)
        print(f"{self.name} duration finished!")


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
        self.last_shot_time = time.time() - random.uniform(0, 2)

    def take_damage(self, damage):
        self.hp -= damage
        if self.hp <= 0:
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

    msg_show = f"SHOW-BULLET|{pos}|{angle}|{bullet_id}\n".encode()
    for client in list(state.active_clients):
        if client.stream_id is not None:
            client._quic.send_stream_data(client.stream_id, msg_show, end_stream=False)
            client.transmit()

    for _ in range(gun_range):
        x, y = get_next_bullet_position(x, y, angle, 15)
        if bullet_id in state.active_bullets:
            state.active_bullets[bullet_id]["x"] = x
            state.active_bullets[bullet_id]["y"] = y

        if not check_if_in_map(x, y):
            break
        if state.game_map[int(y / TILE_SIZE)][int(x / TILE_SIZE)] == "#":
            break

        hit_player = False

        for player_id, pos_str in list(state.players_pos.items()):
            try:
                px, py = map(float, pos_str.split(","))
            except:
                continue

            if abs(px - x) <= TOLERANCE and abs(py - y) <= TOLERANCE:
                hit_player = True
                for client in list(state.active_clients):
                    if client._quic.host_cid.hex() == player_id:
                        client.damage(player_id, gun_damage)
                        break
                break

        if hit_player:
            break

        await asyncio.sleep(BULLETS_MOVE_TIME)

    if bullet_id in state.active_bullets:
        del state.active_bullets[bullet_id]

    msg_del = f"DEL-BULLET|{bullet_id}\n".encode()
    for client in list(state.active_clients):
        if client.stream_id is not None:
            client._quic.send_stream_data(client.stream_id, msg_del, end_stream=False)
            client.transmit()


def pitagoras(x, y):
    return math.sqrt((x * x) + (y * y))


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
    x = int(float(x) / TILE_SIZE)
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

        dist = (player_x - monster_x) ** 2 + (player_y - monster_y) ** 2

        if dist < min_dist:
            min_dist = dist
            closest_player = (player_x, player_y)

    return closest_player


def check_if_in_map_for_monster(x, y):
    x_tile = int(x / TILE_SIZE)
    y_tile = int(y / TILE_SIZE)
    return 0 <= y_tile < len(state.game_map) and 0 <= x_tile < len(state.game_map[0])


def A_star_algorythm(start, target, desired_range):
    open_heap = []
    open_dict = {}

    closed_set = set()

    start_h = pitagoras(target[0] - start[0], target[1] - start[1])
    start_node = Node((start[0], start[1], 0, start_h, start_h))

    heapq.heappush(open_heap, (start_node.data[4], next(counter), start_node))
    open_dict[(start[0], start[1])] = 0

    iterations = 0
    MAX_ITERATIONS = 400

    while open_heap and iterations < MAX_ITERATIONS:
        iterations += 1
        _, _, current_node = heapq.heappop(open_heap)
        cx, cy, cg = current_node.data[0], current_node.data[1], current_node.data[2]

        if (cx, cy) in closed_set:
            continue

        closed_set.add((cx, cy))

        if current_node.data[3] <= desired_range:
            path = reverse_node_chain(current_node)
            return path.next if path and path.next else current_node

        for dx in [-TILE_SIZE, 0, TILE_SIZE]:
            for dy in [-TILE_SIZE, 0, TILE_SIZE]:
                if dx == 0 and dy == 0:
                    continue

                nx, ny = cx + dx, cy + dy

                if not check_if_in_map_for_monster(nx, ny):
                    continue
                row, col = int(ny / TILE_SIZE), int(nx / TILE_SIZE)
                if state.game_map[row][col] == "#":
                    continue
                if (nx, ny) in closed_set:
                    continue

                step_cost = pitagoras(dx, dy)
                new_g = cg + step_cost
                h_cost = pitagoras(target[0] - nx, target[1] - ny)
                new_f = new_g + h_cost

                if (nx, ny) not in open_dict or new_g < open_dict[(nx, ny)]:
                    open_dict[(nx, ny)] = new_g
                    neighbor_node = Node((nx, ny, new_g, h_cost, new_f))
                    neighbor_node.next = current_node
                    heapq.heappush(open_heap, (new_f, next(counter), neighbor_node))

    return None


def get_next_bullet_position(x, y, angle_degrees, speed):
    angle_rad = math.radians(angle_degrees)
    return x + math.cos(angle_rad) * speed, y + math.sin(angle_rad) * speed


def check_movement(new_pos, old_pos, skill):
    try:
        new_x, new_y = map(float, new_pos.split(","))
        old_x, old_y = map(float, old_pos.split(","))
    except:
        print("Error while splitting the in the check_movement function!")
        return
    if check_if_in_map(new_x, new_y):
        if state.game_map[int(new_y / TILE_SIZE)][int(new_x / TILE_SIZE)] == ".":
            current_time = pygame.time.get_ticks() / 1000
            if (abs(new_x - old_x) <= 6 and abs(new_y - old_y) <= 6) or (
                    skill.name == "Speed Boost" and current_time - skill.last_action_time - skill.duration_time <= 2):
                return True
            elif abs(new_x - old_x) <= 10 and abs(
                    new_y - old_y) <= 10 and skill.name == "Speed Boost" and skill.is_active:
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

                if game_map[tile_y][tile_x] != "#":
                    x = tile_x * TILE_SIZE
                    y = tile_y * TILE_SIZE
                    name = random.choice(WEAPON_NAMES)
                    loot_list.append((x, y, name))

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

                if game_map[tile_y][tile_x] != "#":
                    x = tile_x * TILE_SIZE
                    y = tile_y * TILE_SIZE

                    new_id = random.randint(1, int(MAX_POTION))
                    while new_id in state.map_potion:
                        new_id = random.randint(1, int(MAX_POTION))

                    state.map_potion[new_id] = {
                        "x": x,
                        "y": y
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

            if state.server_area:
                if monster.x < state.server_area["t-l"][0] or monster.x > state.server_area["t-r"][0]:
                    msg = f"CHANGE-MONSTER|{monster.x}|{monster.y}|{monster.weapon}"
                    await send_to_lb(msg)
                    # Cannot del monster directly, better to remove from list but handled gracefully in real scenario
                    continue

            # --- הגיון הלחימה של המפלצת ---
            if dist_to_player <= monster.weapon[2]:
                if now - monster.last_shot_time >= random.uniform(3.5, 5.5):
                    angle = math.degrees(
                        math.atan2(monster.nearest_player[1] - monster.y, monster.nearest_player[0] - monster.x))

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

                    asyncio.create_task(monster_gun_tracking(new_id, monster.weapon[0], monster.x, monster.y, angle))
                    monster.last_shot_time = now

            # --- הגיון התזוזה של המפלצת ---
            if (monster.path is None or now - monster.last_path_time >= MONSTER_CHANGE_PATH_EVERY_SET_SECONDS):
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


async def send_to_lb(message: str):
    if state.lb_writer is not None:
        try:
            if not message.endswith("\n"):
                message += "\n"

            state.lb_writer.write(message.encode())
            await state.lb_writer.drain()
        except Exception as e:
            print(f"Error sending to LB: {e}")
            state.lb_writer = None
    else:
        print("LB connection not available.")


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

            if abs(monster.x - px) <= half_width and abs(monster.y - py) <= half_height:
                client_monster_msg += f"|{monster.x},{monster.y},{monster.hp}"

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


async def handle_p2p_connection(reader, writer):
    try:
        while True:
            line = await reader.readline()
            if not line: break

            data = line.decode().strip()
            parts = data.split("|")

            if parts[0] == "GHOST_UPDATE":
                cid = parts[1]
                pos = parts[2]
                hp = int(parts[3])
                state.ghost_players[cid] = {"pos": pos, "hp": hp}

                if state.active_clients:
                    any_client = next(iter(state.active_clients))
                    any_client.broadcast_ghosts()


            elif parts[0] == "REMOVE_GHOST":
                cid = parts[1]
                state.ghost_players.pop(cid, None)

                remove_msg = f"REMOVE_PLAYER|{cid}\n".encode()
                for client in list(state.active_clients):
                    try:
                        if client.stream_id is not None:
                            client._quic.send_stream_data(client.stream_id, remove_msg)
                            client.transmit()
                    except:
                        continue

    except Exception as e:
        print(f"[P2P] Error: {e}")


async def connect_to_neighbor(neighbor_id, host, port):
    if neighbor_id not in state.neighbor_conns:
        try:
            p2p_port = port + P2P_PORT_OFFSET
            reader, writer = await asyncio.open_connection(host, p2p_port)
            state.neighbor_conns[neighbor_id] = (reader, writer)
            print(f"[*] Connected P2P to GS-{neighbor_id} at {host}:{p2p_port}")
        except Exception as e:
            print(f"[!] Failed to connect to GS-{neighbor_id}: {e}")


async def send_to_neighbor(neighbor_id, message):
    neighbor = None
    for side, n in state.neighbor.items():
        if n and n.get('id') == neighbor_id:
            neighbor = n
            break

    if neighbor:
        await connect_to_neighbor(neighbor['id'], neighbor['ip'], neighbor['port'])

        if neighbor_id in state.neighbor_conns:
            _, writer = state.neighbor_conns[neighbor_id]
            try:
                writer.write(message.encode())
                await writer.drain()
            except:
                print(f"[!] Lost P2P connection to GS-{neighbor_id}")
                del state.neighbor_conns[neighbor_id]


async def connect_to_lb():
    while True:
        try:
            print(f"[*] Attempting to connect to LB at {state.lb_host}:{state.lb_port}...")
            reader, writer = await asyncio.open_connection(state.lb_host, state.lb_port)

            auth_type = "RECONNECT" if state.server_id is not None else "REGISTER"
            payload = f"{auth_type}|{state.server_id if state.server_id is not None else f'{MY_IP}|{MY_PORT}'}\n"

            writer.write(payload.encode())
            await writer.drain()

            asyncio.create_task(send_heartbeats_to_lb(writer))

            while True:
                line = await reader.readline()
                if not line:
                    break

                data = line.decode().strip()
                if data.startswith("Connected|"):
                    state.server_id = int(data.split("|")[1])
                    print(f"[LB] Assigned ID: {state.server_id}")

                elif data.startswith("UpdateStats|"):
                    try:
                        parts = data.split("|")
                        state.server_area = {
                            "t-l": [float(parts[1]), 0],
                            "t-r": [float(parts[2]), 0]
                        }
                        print(
                            f"[LB] Area Updated (X-Range): {state.server_area['t-l'][0]} to {state.server_area['t-r'][0]}")
                    except Exception as e:
                        print(f"Error while parsing UpdateStats in connect_to_lb: {e}")

                elif data.startswith("GET-WEAPON"):
                    try:
                        parts = data.split("|")[1:]
                        for weapons in parts:
                            x_str = weapons.split(",")[0]
                            y_str = weapons.split(",")[0]
                            w_type = weapons.split(",")[0]
                            new_id = random.randint(1, 1000000)
                            while new_id in state.map_weapons:
                                new_id = random.randint(1, 1000000)

                            state.map_weapons[new_id] = {
                                "x": float(x_str),
                                "y": float(y_str),
                                "type": w_type,
                            }
                    except:
                        print("Error while getting weapons from lb")

                elif data.startswith("GET-MONSTER"):
                    try:
                        parts = data.split("|")[1:]
                        for monsters in parts:
                            pixel_x = monsters.split(",")[0]
                            pixel_y = monsters.split(",")[1]
                            hp = monsters.split(",")[2]
                            monster = Monster(pixel_x, pixel_y, hp)
                            monsters_list.append(monster)
                    except:
                        print("Error while getting monsters from lb")

                elif data.startswith("GET-POTION"):
                    try:
                        parts = data.split("|")[1:]
                        for potions in parts:
                            x_str = potions.split(",")[0]
                            y_str = potions.split(",")[0]
                            p_type = potions.split(",")[0]
                            new_id = random.randint(1, 1000000)
                            while new_id in state.map_potion:
                                new_id = random.randint(1, 1000000)

                            state.map_potion[new_id] = {
                                "x": float(x_str),
                                "y": float(y_str),
                                "type": p_type,
                            }
                    except:
                        print("Error while getting potion from lb")

                elif data.startswith("TransferClient|"):
                    _, c_id, n_ip, n_port = data.split("|")

                    for client in list(state.active_clients):
                        if client._quic.host_cid.hex() == c_id:
                            print(f"[LB] Sending SWITCH to client {c_id} -> {n_ip}:{n_port}")

                            switch_msg = f"SWITCH|{n_ip}|{n_port}\n".encode()
                            client._quic.send_stream_data(client.stream_id, switch_msg)
                            client.transmit()

            writer.close()
            await writer.wait_closed()

        except Exception as e:
            print(f"[LB] Connection error: {e}. Retrying in 5 seconds...")

        await asyncio.sleep(5)


async def register_with_lb_once(lb_ip: str, timeout: float = 5.0) -> bool:
    try:
        print(f"[*] Trying one-shot registration to LB {lb_ip}:{LB_PORT} ...")
        reader, writer = await asyncio.open_connection(lb_ip, LB_PORT)

        connect_msg = f"Server connect|{MY_IP}|{psutil.cpu_percent()}|{MY_PORT}\n"
        writer.write(connect_msg.encode())
        await writer.drain()

        end_time = time.time() + timeout

        while time.time() < end_time:
            try:
                remaining = max(0.1, end_time - time.time())
                line = await asyncio.wait_for(reader.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            if not line:
                break

            msg = line.decode().strip()

            if msg.startswith("Connected|"):
                try:
                    state.server_id = int(msg.split("|")[1])
                    print(f"[LB] Assigned temporary ID: {state.server_id}")
                except:
                    pass

            elif msg.startswith("UpdateStats|"):
                try:
                    parts = msg.split("|")

                    state.server_area = {
                        "t-l": [float(parts[1]), 0],
                        "t-r": [float(parts[2]), 0]
                    }

                    if len(parts) > 3 and parts[3]:
                        weapons = parts[3].split(";")
                        for weapon in weapons:
                            if not weapon: continue
                            w_parts = weapon.split(",")
                            if len(w_parts) >= 4:
                                x_str, y_str, w_type = w_parts[1], w_parts[2], w_parts[3]
                                new_id = random.randint(1, 1000000)
                                while new_id in state.map_weapons:
                                    new_id = random.randint(1, 1000000)

                                state.map_weapons[new_id] = {
                                    "x": float(x_str),
                                    "y": float(y_str),
                                    "type": w_type,
                                }

                    if len(parts) > 4 and parts[4]:
                        potions = parts[4].split(";")
                        for potion in potions:
                            if not potion: continue
                            p_parts = potion.split(",")
                            if len(p_parts) >= 4:
                                x_str, y_str, p_type = p_parts[1], p_parts[2], p_parts[3]
                                new_id = random.randint(1, 1000000)
                                while new_id in state.map_potion:
                                    new_id = random.randint(1, 1000000)

                                state.map_potion[new_id] = {
                                    "x": float(x_str),
                                    "y": float(y_str),
                                    "type": p_type,
                                }

                    print(f"[LB] Received initial area: {state.server_area}")

                    writer.close()
                    await writer.wait_closed()
                    return True

                except Exception as e:
                    print("[LB] Failed parsing UpdateArea:", e)
                    break

        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass

        print("[LB] One-shot registration failed or timed out.")
        return False

    except Exception as e:
        print(f"[LB] Connection error in one-shot registration: {e}")
        return False


def broadcast_all_states(self):
    for cid, pos in state.players_pos.items():
        self.send_to_all(f"PLAYER_UPDATE|{cid}|{pos}|{state.players_hp[cid]}")

    for cid, data in state.ghost_players.items():
        self.send_to_all(f"PLAYER_UPDATE|{cid}|{data['pos']}|{data['hp']}")


async def send_heartbeats_to_lb(writer):
    try:
        while True:
            if state.server_id is not None:
                msg = f"Server heartbeat|{state.server_id}|{psutil.cpu_percent()}\n"
                writer.write(msg.encode())
                await writer.drain()

            await asyncio.sleep(5)

    except Exception as e:
        print("[LB] Heartbeat stopped:", e)


skills_dict = {
    "Speed Boost": Skill("Speed Boost", 10, 0, False),
    "Shield": Skill("Shield", 6, 0, False),
    "Bombs": Skill("Bombs", 7, 0, False)
}


async def main():
    while True:
        lb_ip = await asyncio.to_thread(input, "Enter Load Balancer IP (default 127.0.0.1): ")
        lb_ip = lb_ip.strip() or "127.0.0.1"

        ok = await register_with_lb_once(lb_ip, timeout=5.0)
        if ok:
            state.lb_host = lb_ip
            state.lb_port = LB_PORT
            print(f"[+] Registered with LB at {lb_ip}:{LB_PORT}")
            break
        else:
            print("[!] Could not register with LB. Try another IP or check the LB is running.\n")

    config = QuicConfiguration(
        is_client=False,
        alpn_protocols=["echo-protocol"],
        verify_mode=False,
    )

    config.load_cert_chain("cert.pem", "key.pem")

    asyncio.create_task(serve(
        host=MY_IP,
        port=MY_PORT,
        configuration=config,
        create_protocol=EchoQuicProtocol,
    ))
    print(f"[*] Game Server (QUIC) running on {MY_IP}:{MY_PORT}")

    p2p_port = MY_PORT + P2P_PORT_OFFSET
    p2p_server = await asyncio.start_server(handle_p2p_connection, MY_IP, p2p_port)
    print(f"[*] P2P Sync Server running on {MY_IP}:{p2p_port}")

    tasks = [
        asyncio.create_task(check_cpu()),
        asyncio.create_task(monsters_manager()),
        asyncio.create_task(track_server_fps()),
    ]

    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        print(f"[CRITICAL] A core task crashed: {e}")
    finally:
        p2p_server.close()
        await p2p_server.wait_closed()
        print("[*] Server shutting down...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass