import asyncio
import math
import random
import psutil
import heapq
import time
import os
from itertools import count

import gs_and_lb_helper_functions
import pygame
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
WEAPON_LIST = [["gun", 30, TILE_SIZE],["rifle" ,10 , TILE_SIZE * 20],["rpg",30,TILE_SIZE*25]]
WEAPON_NAMES = [w[0] for w in WEAPON_LIST]
WEAPON_DAMAGE = [w[1] for w in WEAPON_LIST]
WEAPON_RANGE = [w[2] for w in WEAPON_LIST]
BOMB_WEAPON = ["bomb", 35, 25]

WEAPON_AMMO = {"gun": 30, "rifle": 20, "rpg": 5}
MONSTER_CHANGE_PATH_EVERY_SET_SECONDS = 3
MONSTER_ACCURACY = 65
MAX_POTION = 9000
POTION_LIST = [["Potion", 40],["Poison",5]]
counter = count()
monsters_list = []
SERVER_FPS = 0
SKILL_COOL_TIME = 12
LB_PORT = 8080
lb_ip = os.getenv('LB_IP')

MY_IP = gs_and_lb_helper_functions.get_local_ip()
MY_PUBLIC_IP = os.getenv('MY_PUBLIC_IP', MY_IP)
MY_PORT = int(os.getenv('MY_PORT'))

MAP_FILENAME = "map.txt"

def load_map():
    with open("map.txt", "r") as f:
        lines = f.readlines()
    return [list(line.strip()) for line in lines]


def get_random_valid_position() -> tuple[int, int]:
    valid_tiles = []

    if os.path.exists(MAP_FILENAME):
        try:
            with open(MAP_FILENAME, "r") as f:
                game_map = [line.strip() for line in f.readlines()]

            for row_idx, row in enumerate(game_map):
                for col_idx, tile in enumerate(row):
                    if tile != "#":
                        valid_tiles.append((col_idx, row_idx))
        except Exception as e:
            print(f"Error reading map file: {e}")

    if valid_tiles:
        tile_x, tile_y = random.choice(valid_tiles)
        return tile_x * TILE_SIZE, tile_y * TILE_SIZE

    return TILE_SIZE, TILE_SIZE


class GameState:
    #player info
    players_pos = {}  # client_id -> "x,y"
    players_hp = {}  # client_id -> hp
    players_inventory = {}  # client_id -> {slot 1, slot 2, slot 3 ,slot 4 ,slot 5}
    active_clients = set()  # set of EchoQuicProtocol
    active_bullets = {}  # bullet_id -> {x, y, angle}
    players_skills = {}  #client_id -> {skill name, is active, last activation time}
    players_potions = {}
    player_real_id = {} #client_id -> real_id
    players_control = {} #client_id -> True-this server control this client/False - the opposite
    expected_players = {} #fake_id -> {id,x,y,hp,inv}
    player_name = {} #client_id -> name

    #lb info
    neighbor = {}  # left -> x,ip,port /right -> x,ip,port
    lb_host = None
    lb_port = LB_PORT
    lb_writer = None
    server_id = None
    server_area_left = None
    server_area_right = None
    left_common_zone = []
    right_common_zone = []
    players_handoff_pending = set()
    pending_lb_updates = []

    #game info
    map_weapons = {}  # weapon_id -> {x, y, type}
    game_map = load_map()
    map_potion = {}


state = GameState()


class EchoQuicProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        state.active_clients.add(self)
        self.stream_id = None
        self.recv_buffer = ""
        self.player_id = ""

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
        print(data_str)
        client_id = self.player_id
        # CONNECTED
        if data_str.startswith("Connected|"):
            asyncio.create_task(self.process_connected(data_str))
            return

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

            if client_id not in state.players_pos or client_id not in state.players_skills:
                return
            for other_id, other_pos in list(state.players_pos.items()):
                if other_id == client_id:
                    continue
                if other_pos == new_pos:
                    self.disconnect()
                    print("player has been kicked! player collision")
                    return

            if check_movement(new_pos, state.players_pos[client_id], state.players_skills[client_id]):
                state.players_pos[client_id] = new_pos
                new_x = float(new_pos.split(",")[0])

                if client_id not in state.players_control:
                    state.players_control[client_id] = True

                if state.players_control[client_id]:

                    # ------------------ מעבר שמאלה ------------------
                    if state.server_area_left is not None and new_x < (
                            float(state.server_area_left) - 50) and state.neighbor.get('left') is not None:
                        nei_ip = state.neighbor['left'].split(':')[0]
                        nei_port = state.neighbor['left'].split(':')[1]

                        if client_id not in state.left_common_zone:
                            state.left_common_zone.append(client_id)

                            # -------create a connection between the client and the other gs-------
                            real_id = state.player_real_id.get(client_id)
                            p_name = state.player_name.get(client_id)
                            pos = state.players_pos[client_id]
                            px, py = pos.split(",")
                            inv = state.players_inventory[client_id]
                            inv_str = ";".join(
                                [f"{i},{inv[i]['type']},{inv[i]['ammo']}" for i in range(INVENTORY_SIZE)])
                            hp = state.players_hp[client_id]
                            potions_list = state.players_potions.get(client_id, [])
                            potions = ",".join(potions_list) if potions_list else "None"
                            try:
                                skill = state.players_skills[client_id]
                                skill_str = f"{skill.name},{skill.duration_time},{skill.last_action_time},{skill.is_active}"
                            except:
                                skill_str = "Speed Boost,5,0,False"

                            msg = f"TRANSFER_PLAYER|{real_id}|{client_id}|{p_name}|{px}|{py}|{hp}|{inv_str}|{potions}|{skill_str}|{MY_PORT}"

                            async def safe_transfer_left(c=self, nip=nei_ip, nport=nei_port, m=msg, pname=p_name,cid=client_id):
                                await send_one_off_message(nip, nport, m)
                                state.players_handoff_pending.add(cid)  # מסמן: SWITCHED נשלח, Transfer בדרך
                                msg_switch = f"SWITCHED|{nip}|{nport}|False\n".encode()
                                if c.stream_id is not None:
                                    c._quic.send_stream_data(c.stream_id, msg_switch, end_stream=False)
                                    c.transmit()
                                print(f"{pname} has been asked to switch to {nip}:{nport}")

                            asyncio.create_task(safe_transfer_left())

                    # ------------------ מעבר ימינה ------------------
                    elif state.server_area_right is not None and new_x > (
                            float(state.server_area_right) + 50) and state.neighbor.get('right') is not None:
                        nei_ip = state.neighbor['right'].split(':')[0]
                        nei_port = state.neighbor['right'].split(':')[1]

                        if client_id not in state.right_common_zone:
                            state.right_common_zone.append(client_id)

                            # -------create a connection between the client and the other gs-------
                            real_id = state.player_real_id.get(client_id)
                            p_name = state.player_name.get(client_id)
                            pos = state.players_pos[client_id]
                            px, py = pos.split(",")
                            inv = state.players_inventory[client_id]
                            inv_str = ";".join(
                                [f"{i},{inv[i]['type']},{inv[i]['ammo']}" for i in range(INVENTORY_SIZE)])
                            hp = state.players_hp[client_id]
                            potions_list = state.players_potions.get(client_id, [])
                            potions = ",".join(potions_list) if potions_list else "None"
                            try:
                                skill = state.players_skills[client_id]
                                skill_str = f"{skill.name},{skill.duration_time},{skill.last_action_time},{skill.is_active}"
                            except:
                                skill_str = "Speed Boost,5,0,False"

                            msg = f"TRANSFER_PLAYER|{real_id}|{client_id}|{p_name}|{px}|{py}|{hp}|{inv_str}|{potions}|{skill_str}"

                            async def safe_transfer_right(c=self, nip=nei_ip, nport=nei_port, m=msg, pname=p_name,cid=client_id):
                                await send_one_off_message(nip, nport, m)
                                state.players_handoff_pending.add(cid)  # מסמן: SWITCHED נשלח, Transfer בדרך
                                msg_switch = f"SWITCHED|{nip}|{nport}|False\n".encode()
                                if c.stream_id is not None:
                                    c._quic.send_stream_data(c.stream_id, msg_switch, end_stream=False)
                                    c.transmit()
                                print(f"{pname} has been asked to switch to {nip}:{nport}")

                            asyncio.create_task(safe_transfer_right())
                        else:
                            # מחיקה הדרגתית של שחקנים מהרשימה כדי למנוע חסימות
                            if client_id in state.left_common_zone and state.server_area_left is not None:
                                if float(new_x) > (float(state.server_area_left) + 200):
                                    state.left_common_zone.remove(client_id)
                            elif client_id in state.right_common_zone and state.server_area_right is not None:
                                if float(new_x) < (float(state.server_area_right) - 200):
                                    state.right_common_zone.remove(client_id)

                    self.broadcast_player(client_id, new_pos, state.players_hp[client_id], False)

                else:
                    # השחקן נמצא אצלנו אך סמכות השליטה עברה לשרת החדש.
                    # אנחנו רק נותנים לו להמשיך לנוע אצלנו עד שהשרת הישן יסגור אותו באלגנטיות
                    # בעזרת delayed_close שרץ ב-CLIENT_CONNECTED. לא סוגרים כלום כאן.
                    pass
            else:
                self.disconnect()
                print("player has been kicked! movement problem")


        elif data_str.startswith("CHANGECONTROL|"):
            parts = data_str.split("|")
            if len(parts) == 2:
                state.players_control[client_id] = (parts[1] == "True")

        # ATTACK
        elif data_str.startswith("ATTACK|"):
            if not state.players_control.get(client_id, False): return
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting ATTACK command!")
                return
            if len(parts) < 3:
                return


            if state.players_skills[client_id].name == "Bombs" and state.players_skills[client_id].is_active == True:
                weapon = "bomb"
                print("bomb throw")
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
                angle_rad = math.radians(angle)
                center_x = float(x_str) + 32 + math.cos(angle_rad) * 20
                center_y = float(y_str) + 32 + math.sin(angle_rad) * 20 -8

                state.active_bullets[new_id] = {
                    "x": center_x,
                    "y": center_y,
                    "angle": angle,
                }

                print("shooting!")
                asyncio.create_task(self.gun_tracking(new_id, weapon))
                return

            weapon_slot = int(parts[1])
            slot_data = state.players_inventory[client_id][weapon_slot]
            weapon = slot_data["type"]

            if weapon not in WEAPON_NAMES:
                return

            # Server-side ammo check
            if slot_data["ammo"] <= 0:
                self.disconnect()
                print("player has been kicked! no ammo")
                return

            slot_data["ammo"] -= 1

            # Broadcast updated ammo count to the shooter
            ammo_msg = f"AMMO|{weapon_slot}|{slot_data['ammo']}\n".encode()
            if self.stream_id is not None:
                self._quic.send_stream_data(self.stream_id, ammo_msg, end_stream=False)
                self.transmit()

            # Out of ammo — remove weapon, shift inventory, tell client to remove it
            if slot_data["ammo"] <= 0:
                for i in range(weapon_slot, INVENTORY_SIZE - 1):
                    state.players_inventory[client_id][i] = state.players_inventory[client_id][i + 1]
                state.players_inventory[client_id][INVENTORY_SIZE - 1] = {"type": "none", "ammo": 0}

                remove_msg = f"REMOVE_WEAPON|{weapon_slot}\n".encode()
                if self.stream_id is not None:
                    self._quic.send_stream_data(self.stream_id, remove_msg, end_stream=False)
                    self.transmit()

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
            angle_rad = math.radians(angle)
            center_x = float(x_str) + 32 + math.cos(angle_rad) * 20
            center_y = float(y_str) + 32 + math.sin(angle_rad) * 20 -8

            state.active_bullets[new_id] = {
                "x": center_x,
                "y": center_y,
                "angle": angle,
            }
            print("shooting!")
            asyncio.create_task(self.gun_tracking(new_id, weapon))

        # PICKUP
        elif data_str.startswith("PICKUP|"):
            if not state.players_control.get(client_id, False): return
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
            if not check_if_position_in_gs_responsibility(px):
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
                        if state.players_inventory[client_id][slot]["type"] == "none":
                            state.players_inventory[client_id][slot] = {
                                "type": pickup_type,
                                "ammo": WEAPON_AMMO[pickup_type]
                            }
                            pos_str = f"{state.map_weapons[found_weapon_id]['x']},{state.map_weapons[found_weapon_id]['y']}"
                            self.broadcast_undrop(pos_str, state.map_weapons[found_weapon_id]["type"])
                            state.pending_lb_updates.append(f"REMOVE:{pos_str},{state.map_weapons[found_weapon_id]["type"]}")
                            del state.map_weapons[found_weapon_id]
                            break
                else:
                    self.disconnect()
                    print("player has been kicked! weapon id = none")
            else:
                self.disconnect()
                print("player has been kicked! this weapon does not exist")

        # PPICKUP
        elif data_str.startswith("PPICKUP|"):
            if not state.players_control.get(client_id, False): return
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
                print("Error while splitting the pos in the PPICKUP command!")
                return
            if not check_if_position_in_gs_responsibility(px):
                return
            found_potion_id = None

            for p_id, p_data in state.map_potion.items():
                if abs(p_data["x"] - px) <= TOLERANCE and abs(p_data["y"] - py) <= TOLERANCE:
                    print(p_data["type"])
                    if p_data["type"] == pickup_type:
                        print("sup dog up the hp")
                        state.players_potions[client_id].append(pickup_type)
                        found_potion_id = p_id
                        break

            if found_potion_id is not None:
                pos_str = f"{state.map_potion[found_potion_id]['x']},{state.map_potion[found_potion_id]['y']}"
                self.broadcast_undrop(pos_str, pickup_type)
                self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], False)
                state.pending_lb_updates.append(f"REMOVE:{pos_str},{pickup_type}")
                del state.map_potion[found_potion_id]
            else:
                self.disconnect()
                print("player has been kicked! potion id = none")

        # USE
        elif data_str.startswith("USE|"):
            if not state.players_control.get(client_id, False): return
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting the USE command!")
                return
            if len(parts) < 2:
                return

            item_name = parts[1]
            if item_name not in state.players_potions[client_id]:
                return

            if item_name not in state.players_potions[client_id]:
                return

            state.players_potions[client_id].remove(item_name)
            if item_name == "Potion":
                state.players_hp[client_id] += UP_HP
                if state.players_hp[client_id] > 100:
                    state.players_hp[client_id] = 100
                self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], True)

            elif item_name == "Poison":
                if len(parts) < 3:
                    return
                pos = parts[2]
                poison_x, poison_y = map(float, pos.split(","))
                self.broadcast_poison(poison_x, poison_y)

                async def poison_effect():
                    for _ in range(5):
                        for p_id, p_pos in state.players_pos.items():
                            if p_id != client_id:
                                px, py = map(float, p_pos.split(","))
                                dx = px - poison_x
                                dy = py - poison_y
                                distance = (dx ** 2 + dy ** 2) ** 0.5
                                if distance <= RADIUS:
                                    self.damage(p_id, 5)
                        await asyncio.sleep(0.5)

                asyncio.create_task(poison_effect())

            else:
                self.disconnect()
                print("player has been kicked! item name = none")

        # DROP
        elif data_str.startswith("DROP|"):
            if not state.players_control.get(client_id, False): return
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
            if not check_if_position_in_gs_responsibility(x_str):
                return
            weapon_slot = int(parts[2])
            slot_data = state.players_inventory[client_id][weapon_slot]
            drop = slot_data["type"]

            if drop in WEAPON_NAMES:
                if drop != "none":
                    for i in range(weapon_slot, INVENTORY_SIZE - 1):
                        state.players_inventory[client_id][i] = state.players_inventory[client_id][i + 1]
                    state.players_inventory[client_id][INVENTORY_SIZE - 1] = {"type": "none", "ammo": 0}

                    new_id = random.randint(1, 1000000)
                    while new_id in state.map_weapons:
                        new_id = random.randint(1, 1000000)

                    state.map_weapons[new_id] = {
                        "x": float(x_str),
                        "y": float(y_str),
                        "type": drop,
                    }
                    self.broadcast_drop(pos_str, drop, False)
                    state.pending_lb_updates.append(f"ADD:{pos_str},{drop}")
                else:
                    self.disconnect()
                    print("player has been kicked! player does not have this weapon")
            else:
                self.disconnect()
                print("player has been kicked! the server dont recognize this weapon")

        # CHAT
        elif data_str.startswith("CHAT|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting the CHAT command!")
                return
            if len(parts) < 2:
                return
            if not state.players_control[client_id]:
                return
            msg = parts[1]
            state.pending_lb_updates.append(f"CHAT:{msg},{client_id}")
            self.broadcast_chat(msg, state.player_name[client_id])

        elif data_str.startswith("SKILL|"):
            if not state.players_control.get(client_id, False): return
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
            required_time = (0 if state.players_skills[client_id].last_action_time == 0 else state.players_skills[client_id].duration_time) + SKILL_COOL_TIME

            if elapsed_since_last_press >= required_time:
                state.players_skills[client_id] = sent_skill
                state.players_skills[client_id].last_action_time = click_time
                state.players_skills[client_id].is_active = True
                print("Skill Activated!")
                self.broadcast_skill(client_id, state.players_skills[client_id],False)
                asyncio.create_task(state.players_skills[client_id].timer(client_id, self.broadcast_skill))
            else:
                print("Skill issue!")

        # RESPAWN
        elif data_str == "RESPAWN":
            if not state.players_control[client_id]:
                return
            if self not in state.active_clients:
                state.active_clients.add(self)

            x, y = get_random_valid_position()
            spawn_pos = f"{x},{y}"
            state.players_pos[client_id]       = spawn_pos
            state.players_hp[client_id]        = 100
            state.players_inventory[client_id] = {int(i): {"type": "none", "ammo": 0} for i in range(INVENTORY_SIZE)}
            state.players_potions[client_id] = []
            state.players_skills[client_id]    = Skill("Speed Boost", 5, 0, False)
            if self.stream_id is not None:
                self._quic.send_stream_data(self.stream_id, f"RESPAWNED|{spawn_pos}|100\n".encode(), end_stream=False)
                self.transmit()
            self.broadcast_player(client_id, spawn_pos, 100, False)

        # DISCONNECT
        elif data_str == "Disconnected":
            self.disconnect()
            print("player has been kicked! player disconnected")

    # ---------- Broadcast helpers ---------- #

    def broadcast_drop(self, pos_str, type_str, to_yourself):
        msg = f"DROPPED|{pos_str}|{type_str}\n".encode()
        notTo = []
        client_id = self.player_id
        if not state.players_control.get(client_id, True):
            notTo.extend(state.right_common_zone)
            notTo.extend(state.left_common_zone)

        for client in list(state.active_clients):
            if client == self and not to_yourself:
                continue
            if client.stream_id is None:
                continue
            if client.player_id in notTo:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()
        print(msg)

    def broadcast_undrop(self, pos_str, type_str):
        msg = f"UNDROPPED|{pos_str}|{type_str}\n".encode()
        notTo = []
        client_id = self.player_id
        if not state.players_control.get(client_id, True):
            notTo.extend(state.right_common_zone)
            notTo.extend(state.left_common_zone)


        for client in list(state.active_clients):
            if client == self:
                continue
            if client.stream_id is None:
                continue
            if client.player_id in notTo:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()
        print(msg)

    def broadcast_chat(self, msg: str, client_id):
        msg = f"CHAT|{client_id}|{msg}\n".encode()
        notTo = []
        if not state.players_control.get(client_id, True):
            notTo.extend(state.right_common_zone)
            notTo.extend(state.left_common_zone)


        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            if client.player_id in notTo:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

    def broadcast_show_bullet(self, pos: str, angle: str, bullet_id: str, bullet_type: str):
        msg = f"SHOW-BULLET|{pos}|{angle}|{bullet_id}|{bullet_type}\n".encode()
        notTo = []
        client_id = self.player_id
        if not state.players_control.get(client_id, True):
            notTo.extend(state.right_common_zone)
            notTo.extend(state.left_common_zone)


        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            if client.player_id in notTo:
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
        notTo = []
        client_id = self.player_id
        if not state.players_control.get(client_id, True):
            notTo.extend(state.right_common_zone)
            notTo.extend(state.left_common_zone)


        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            if client.player_id in notTo:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

    def broadcast_remove(self, client_id: str):
        msg = f"REMOVE|{client_id}\n".encode()
        print("sent remove!")
        notTo = []
        if not state.players_control.get(client_id, True):
            notTo.extend(state.right_common_zone)
            notTo.extend(state.left_common_zone)


        for client in list(state.active_clients):
            if client.stream_id is None:
                continue
            if client.player_id in notTo:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()

    def broadcast_player(self, sender_id: str, pos_str: str, hp, to_yourself: bool):
        inv = state.players_inventory.get(sender_id, {})
        has_weapon = any(v.get("type", "none") != "none" for v in inv.values())
        msg = f"UPDATE|{sender_id}|{pos_str}|{hp}|{'1' if has_weapon else '0'}\n".encode()
        notTo = []
        if not state.players_control.get(sender_id, True):
            notTo.extend(state.right_common_zone)
            notTo.extend(state.left_common_zone)


        for client in list(state.active_clients):
            if client == self and not to_yourself:
                continue
            if client.player_id in notTo:
                continue
            if client.stream_id is None:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()
        print("changed! -", msg)


    def broadcast_skill(self, sender_id: str, skill, to_yourself: bool):
        msg = f"SKILL|{sender_id}|{skill.name}|{skill.is_active}\n".encode()
        notTo = []
        if not state.players_control.get(sender_id, True):
            notTo.extend(state.right_common_zone)
            notTo.extend(state.left_common_zone)


        for client in list(state.active_clients):
            if client == self and not to_yourself:
                continue
            if client.stream_id is None:
                continue
            if client.player_id in notTo:
                continue
            client._quic.send_stream_data(client.stream_id, msg, end_stream=False)
            client.transmit()
    # ---------- Game logic ---------- #
    async def process_connected(self, data_str: str):
        try:
            parts = data_str.split("|")
        except:
            print("Error while splitting Connected command!")
            self.disconnect()
            return

        if len(parts) >= 8:
            sent_id = parts[1]
            self.player_id = sent_id
            client_id = sent_id
            client_name = parts[2]
            pos_str = parts[3]

            try:
                c_x, c_y = map(float, pos_str.split(","))
                c_hp = int(parts[4])
            except ValueError:
                print("Cheat/Error detected: Invalid numbers in Connected!")
                self.disconnect()
                return

            c_inv_dict = {}
            inv_items = parts[5].split("-")
            for i in range(INVENTORY_SIZE):
                if i < len(inv_items):
                    w_type, ammo = inv_items[i].split(",")
                    c_inv_dict[i] = {"type": w_type, "ammo": int(ammo)}
                else:
                    c_inv_dict[i] = {"type": "none", "ammo": 0}

            c_potions_str = parts[6]
            c_potions = [p.strip() for p in c_potions_str.split(",") if
                         p.strip() and p.strip().lower() not in ("none", "empty", "[]")]

            # פתרון השורש ל-Race Condition: לולאת המתנה קצרה למידע מהשרת הישן או מה-LB
            retries = 0
            while sent_id not in state.expected_players and sent_id not in state.players_pos and retries < 20:
                await asyncio.sleep(0.1)
                retries += 1

            if sent_id in state.expected_players:
                expected_data = state.expected_players[sent_id]

                e_x = expected_data["x"]
                e_y = expected_data["y"]
                e_hp = expected_data["hp"]
                e_inv = expected_data["inv"]

                e_potions = expected_data.get("potions", [])
                e_potions = [p.strip() for p in e_potions if
                             p.strip() and p.strip().lower() not in ("none", "empty", "[]")]

                is_transfer = expected_data.get("is_transfer", False)

                if not is_transfer:
                    if abs(c_x - e_x) > 10 or abs(c_y - e_y) > 10:
                        print(f"[!] DISCONNECT REASON: Position mismatch. Client: {c_x},{c_y} | Expected: {e_x},{e_y}")
                        self.disconnect()
                        return
                else:
                    print(f"Player {client_name} connecting from neighbor. Requesting final sync.")
                    real_id = expected_data["id"]

                    async def notify_arrival():
                        msg = f"CLIENT_CONNECTED|{real_id}|{client_id}|{MY_IP}|{MY_PORT}"
                        src_ip = expected_data.get("source_ip")
                        src_port = expected_data.get("source_port")
                        if src_ip and src_port:
                            # שולחים רק לשרת שממנו הגיע השחקן — לא לכל השכנים
                            await send_one_off_message(src_ip, int(src_port), msg)
                        else:
                            # fallback לסצנריו ישן ללא source address
                            if state.neighbor.get('left'):
                                nip, nport = state.neighbor['left'].split(':')
                                await send_one_off_message(nip, int(nport), msg)
                            if state.neighbor.get('right'):
                                nip, nport = state.neighbor['right'].split(':')
                                await send_one_off_message(nip, int(nport), msg)

                    asyncio.create_task(notify_arrival())

                if c_hp != e_hp:
                    print(f"[-] Warning: HP mismatch. Overriding client ({c_hp}) with server ({e_hp}).")
                    c_hp = e_hp

                for i in range(INVENTORY_SIZE):
                    if c_inv_dict[i]["type"] != e_inv[i]["type"] or c_inv_dict[i]["ammo"] != e_inv[i]["ammo"]:
                        print(f"[-] Warning: Inventory mismatch. Overriding with server data.")
                        c_inv_dict = e_inv
                        break

                if sorted(c_potions) != sorted(e_potions):
                    print(f"[-] Warning: Potions mismatch. Client: {c_potions} | Expected: {e_potions}")
                    print("    -> Overriding client potions with server data.")
                    c_potions = e_potions

                print(f"Player {client_name} passed security validation successfully!")

                real_id = expected_data["id"]
                state.player_real_id[client_id] = real_id
                send = True
                try:
                    if not state.expected_players[sent_id]["connectMsg"]:
                        send = False
                except:
                    pass
                del state.expected_players[sent_id]

            elif sent_id in state.players_pos:
                print(
                    f"[*] Warning: Player {client_name} already fully connected. Ignoring duplicate request to prevent crash.")
                return
            else:
                print(f"[!] DISCONNECT REASON: Fake ID '{sent_id}' not found in state.expected_players!")
                self.disconnect()
                return

            valid_right = True
            if state.server_area_right is not None:
                valid_right = c_x < (float(state.server_area_right) + float(SCREEN_WIDTH) / 2 + 300)

            valid_left = True
            if state.server_area_left is not None:
                valid_left = c_x > (float(state.server_area_left) - float(SCREEN_WIDTH) / 2 - 300)

            # FIX 1: We accept the player into the state EVEN IF momentarily out of bounds.
            # This allows the GS to dynamically pass the new client info to the correct
            # neighbor using the P2P transfer, preventing permanent kicks during area updates.
            state.players_pos[client_id] = pos_str
            state.players_hp[client_id] = c_hp
            state.players_inventory[client_id] = c_inv_dict
            state.player_name[client_id] = client_name
            state.players_control[client_id] = (parts[7] == "True")
            state.players_potions[client_id] = c_potions
            state.players_skills[client_id] = Skill("Speed Boost", 5, 0, False)

            if not (valid_right and valid_left):
                print(
                    f"Player {client_name} is out of bounds upon connection. Accepted momentarily for seamless neighbor sync/transfer.")

        else:
            print("Cheat/Error detected: Missing arguments in Connected command!")
            self.disconnect()
            return

        print("player connected!")
        if send:
            message = f"CONNECT|{state.player_real_id[client_id]}"
            asyncio.create_task(send_to_lb(message))

        for other_id, pos in state.players_pos.items():
            if other_id == client_id:
                continue
            hp = state.players_hp.get(other_id, "100")
            inv = state.players_inventory.get(other_id, {})
            has_weapon = any(v.get("type", "none") != "none" for v in inv.values())
            msg = f"UPDATE|{other_id}|{pos}|{hp}|{'1' if has_weapon else '0'}\n".encode()
            if self.stream_id is not None:
                self._quic.send_stream_data(self.stream_id, msg, end_stream=False)

        for weapon_id, w_data in state.map_weapons.items():
            msg = f"DROPPED|{w_data['x']},{w_data['y']}|{w_data['type']}\n".encode()
            if self.stream_id is not None:
                self._quic.send_stream_data(self.stream_id, msg, end_stream=False)

        for potion_id, p_data in state.map_potion.items():
            msg = f"POTIONS|{p_data['x']},{p_data['y']}|{p_data['type']}\n".encode()
            if self.stream_id is not None:
                self._quic.send_stream_data(self.stream_id, msg, end_stream=False)

        self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], False)
        self.transmit()

    def disconnect(self):
        # --- מנגנון הגנה נגד חיבורי רפאים (Ghost Connections) ---
        if getattr(self, "is_handed_off", False) or self not in state.active_clients:
            return
        # -----------------------------------------------------

        client_id = self.player_id
        self.broadcast_remove(client_id)
        real_id = state.player_real_id.get(client_id)

        # הוספנו את ה-if הזה כדי לחסום דיווחים כוזבים כששחקן עובר שרת
        if real_id:
            if client_id in state.players_pos and client_id in state.players_hp and client_id in state.players_inventory:
                pos = state.players_pos[client_id]
                try:
                    x, y = pos.split(",")
                except:
                    x, y = 0, 0

                hp = state.players_hp[client_id]
                inv = state.players_inventory[client_id]

                potions_list = state.players_potions.get(client_id, [])
                potions_str = ",".join(potions_list) if potions_list else "None"

                inv_items = []
                for i in range(INVENTORY_SIZE):
                    if i in inv:
                        inv_items.append(f"{inv[i]['type']},{inv[i]['ammo']}")
                    else:
                        inv_items.append("none,0")
                inv_str = ";".join(inv_items)

                save_msg = f"SAVE|{real_id}|{x}|{y}|{hp}|{inv_str}|{potions_str}\n"

                if hasattr(state, 'lb_writer') and state.lb_writer:
                    state.lb_writer.write(save_msg.encode())
                    print(f"[!] Sent immediate SAVE for player {real_id}")

            message = f"DISCONNECT|{real_id}"
            asyncio.create_task(send_to_lb(message))

        # מחיקת השחקן (השאר כמו שהיה)
        state.players_pos.pop(client_id, None)
        state.players_hp.pop(client_id, None)
        state.players_inventory.pop(client_id, None)
        state.players_potions.pop(client_id, None)
        state.players_skills.pop(client_id, None)
        state.player_name.pop(client_id, None)
        state.players_control.pop(client_id, None)
        state.player_real_id.pop(client_id, None)

        if self in state.active_clients:
            state.active_clients.remove(self)

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
        for _ in range(gun_range):
            x, y = get_next_bullet_position(x, y, angle)
            state.active_bullets[bullet_id]["x"] = x
            state.active_bullets[bullet_id]["y"] = y

            # FIX 3a: P2P Bullet Crossing Check
            if state.server_area_left is not None and x < float(state.server_area_left) and state.neighbor.get('left'):
                nei_ip, nei_port = state.neighbor['left'].split(':')
                msg = f"TRANSFER_BULLET|{bullet_id}|{gun_type}|{x}|{y}|{angle}"
                asyncio.create_task(send_one_off_message(nei_ip, int(nei_port), msg))
                del state.active_bullets[bullet_id]
                self.broadcast_del_bullet(str(bullet_id))
                return

            if state.server_area_right is not None and x > float(state.server_area_right) and state.neighbor.get(
                    'right'):
                nei_ip, nei_port = state.neighbor['right'].split(':')
                msg = f"TRANSFER_BULLET|{bullet_id}|{gun_type}|{x}|{y}|{angle}"
                asyncio.create_task(send_one_off_message(nei_ip, int(nei_port), msg))
                del state.active_bullets[bullet_id]
                self.broadcast_del_bullet(str(bullet_id))
                return

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
                    print("Error while splitting in gun_tracking!")
                    return
                if abs(px - x) <= TOLERANCE and abs(py - y) <= TOLERANCE:
                    if player_id != self.player_id:
                        del state.active_bullets[bullet_id]
                        self.broadcast_del_bullet(str(bullet_id))
                        self.damage(player_id, gun_damage)
                        return

            for monster in monsters_list:
                try:
                    px = monster.x
                    py = monster.y
                except:
                    print("Error while splitting in gun_tracking!")
                    return
                if abs(px - x) <= TOLERANCE and abs(py - y) <= TOLERANCE:
                    del state.active_bullets[bullet_id]
                    self.broadcast_del_bullet(str(bullet_id))
                    monster.take_damage(gun_damage)
                    return

            await asyncio.sleep(BULLETS_MOVE_TIME)

        if bullet_id in state.active_bullets:
            if(gun_type == "bomb"):
                print("deleted bomb")
            del state.active_bullets[bullet_id]
            self.broadcast_del_bullet(str(bullet_id))

    def damage(self, client_id: str, damage: int):
        hp = int(state.players_hp.get(client_id))
        # if state.players_skills[client_id]
        if state.players_skills[client_id].name == 'Shield' and state.players_skills[client_id].is_active:
            print("shield protection")
            return
        if hp - damage <= 0:
            pos = state.players_pos[client_id]
            dropped = 0
            inv_slot = 0
            while dropped < AMOUNT_TO_DROP_IN_DEATH and inv_slot < INVENTORY_SIZE:
                item = state.players_inventory[client_id].get(inv_slot)
                if item["type"] != "none":
                    new_id = random.randint(1, 1000000)
                    while new_id in state.map_weapons:
                        new_id = random.randint(1, 1000000)
                    try:
                        x = float(pos.split(",")[0])
                        y = float(pos.split(",")[1])
                    except:
                        print("Error while splitting in damage function!")
                        return
                    state.map_weapons[new_id] = {"x": x, "y": y, "type": item["type"]}
                    self.broadcast_drop(pos, item["type"], True)
                    dropped += 1
                inv_slot += 1

            # Send DEAD only to the dying player (keeps connection open for respawn)
            dead_client = None
            for client in state.active_clients:
                if client.player_id == client_id:  # FIX: Root bug fixed here
                    dead_client = client
                    break
            if dead_client and dead_client.stream_id is not None:
                dead_client._quic.send_stream_data(dead_client.stream_id, b"DEAD\n", end_stream=False)
                dead_client.transmit()

            # Send REMOVE to everyone else
            remove_msg = f"REMOVE|{client_id}\n".encode()
            for client in list(state.active_clients):
                if client is dead_client or client.stream_id is None:
                    continue
                client._quic.send_stream_data(client.stream_id, remove_msg, end_stream=False)
                client.transmit()

            # Wipe state but keep connection alive for RESPAWN/Disconnected
            if client_id in state.players_pos:
                del state.players_pos[client_id]
            if client_id in state.players_hp:
                del state.players_hp[client_id]
            if client_id in state.players_inventory:
                del state.players_inventory[client_id]
            if client_id in state.players_potions:
                del state.players_potions[client_id]
            if client_id in state.players_skills:
                del state.players_skills[client_id]
            # NOTE: do NOT remove from state.active_clients

            client_to_remove = None
            for client in state.active_clients:
                if client.player_id == client_id:  # FIX: Root bug fixed here
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

class Skill:
    def __init__(self, name, duration_time, last_action_time, is_active):
        self.name = name
        self.duration_time = duration_time
        self.last_action_time = last_action_time
        self.is_active = is_active

    async def timer(self, client_id, broadcast_skill):
        # Wait for the duration (this doesn't block the rest of the code)
        print(f"timn:{self.duration_time}")
        await asyncio.sleep(self.duration_time)
        # After waiting, turn it off
        self.is_active = False
        state.players_skills[client_id] = self
        broadcast_skill(client_id, self, False)

        print(f"{self.name} duration finished!")


class Monster:
    def __init__(self, x, y,weapon_name , hp, id):
        self.hp = hp
        self.weapon = ["gun", 30, TILE_SIZE]
        for w in WEAPON_LIST:
            if w[0] == weapon_name:
                self.weapon = w
                break
        self.x = x
        self.y = y
        self.id = id
        self.nearest_player = find_nearest_player(self.x, self.y)

        if self.nearest_player:
            self.path = A_star_algorythm((self.x, self.y), self.nearest_player, TILE_SIZE)
        else:
            self.path = None

        self.last_path_time = time.time()
        self.last_shot_time = time.time() - random.uniform(0, 2)

    def take_damage(self, damage):
        global monsters_list
        self.hp -= damage
        if self.hp <= 0:

            death_x = self.x
            death_y = self.y

            state.pending_lb_updates.append(f"remove:{self.id},monster")
            monsters_list.remove(self)

            for i in range(1):
                item = random.choice(POTION_LIST)
                new_id = random.randint(1, int(MAX_POTION))
                while new_id in state.map_potion:
                    new_id = random.randint(1, int(MAX_POTION))
                state.map_potion[new_id] = {"x": death_x, "y": death_y, "type": item[0]}

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

    msg_show = f"SHOW-BULLET|{pos}|{angle}|{bullet_id}|bullet\n".encode()
    for client in list(state.active_clients):
        if client.stream_id is not None:
            client._quic.send_stream_data(client.stream_id, msg_show, end_stream=False)
            client.transmit()

    for _ in range(gun_range):
        x, y = get_next_bullet_position(x, y, angle)
        if bullet_id in state.active_bullets:
            state.active_bullets[bullet_id]["x"] = x
            state.active_bullets[bullet_id]["y"] = y

        # FIX 3b: Monster/Transferred bullets crossing boundary
        if state.server_area_left is not None and x < float(state.server_area_left) and state.neighbor.get('left'):
            nei_ip, nei_port = state.neighbor['left'].split(':')
            msg = f"TRANSFER_BULLET|{bullet_id}|{gun_type}|{x}|{y}|{angle}"
            asyncio.create_task(send_one_off_message(nei_ip, int(nei_port), msg))
            break

        if state.server_area_right is not None and x > float(state.server_area_right) and state.neighbor.get('right'):
            nei_ip, nei_port = state.neighbor['right'].split(':')
            msg = f"TRANSFER_BULLET|{bullet_id}|{gun_type}|{x}|{y}|{angle}"
            asyncio.create_task(send_one_off_message(nei_ip, int(nei_port), msg))
            break

        if not check_if_in_map(x, y):
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
                    if client.player_id == player_id:  # FIX: Root bug fixed here
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
    if y >= len(state.game_map): return False
    if y < 0: return False
    if x >= len(state.game_map[0]): return False
    if x < 0: return False
    return True

def check_if_position_in_gs_responsibility(x):
    if state.server_area_left is not None and float(x) < float(state.server_area_left):
        return False
    elif state.server_area_right is not None and float(x) > float(state.server_area_right):
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

def get_next_bullet_position(x, y, angle_degrees):
    angle_rad = math.radians(angle_degrees)
    return x + math.cos(angle_rad) * 15, y + math.sin(angle_rad) * 15

def check_movement(new_pos, old_pos, skill):
    try:
        new_x, new_y = map(float, new_pos.split(","))
        old_x, old_y = map(float, old_pos.split(","))
    except:
        print("Error while splitting in check_movement!")
        return False
    print(skill.is_active)
    if check_if_in_map(new_x, new_y):
        if state.game_map[int(new_y / TILE_SIZE)][int(new_x / TILE_SIZE)] == ".":
            current_time = pygame.time.get_ticks() / 1000  # Get time in seconds
            if (abs(new_x - old_x) <= 6 and abs(new_y - old_y) <= 6) or (skill.name == "Speed Boost" and current_time - skill.last_action_time - skill.duration_time <= 2):
                return True
            elif abs(new_x - old_x) <= 10 and abs(new_y - old_y) <= 10 and skill.name == "Speed Boost" and skill.is_active:
                return True
    return False


async def monsters_manager():
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
            if dist_to_player <= monster.weapon[2]:
                if now - monster.last_shot_time >= random.uniform(3.5, 5.5):
                    angle = math.degrees(math.atan2(
                        monster.nearest_player[1] - monster.y,
                        monster.nearest_player[0] - monster.x))
                    max_deviation = (100 - MONSTER_ACCURACY) * 0.4
                    angle += random.uniform(-max_deviation, max_deviation)
                    new_id = random.randint(1, MAX_BULLETS)
                    while new_id in state.active_bullets:
                        new_id = random.randint(1, MAX_BULLETS)
                    state.active_bullets[new_id] = {"x": monster.x, "y": monster.y, "angle": angle}
                    asyncio.create_task(monster_gun_tracking(new_id, monster.weapon[0], monster.x, monster.y, angle))
                    monster.last_shot_time = now
            if (monster.path is None or now - monster.last_path_time >= MONSTER_CHANGE_PATH_EVERY_SET_SECONDS):
                new_path = A_star_algorythm((monster.x, monster.y), monster.nearest_player, TILE_SIZE)
                monster.path = new_path
                monster.last_path_time = now
            if monster.path:
                if float(monster.path.data[0]) > float(state.server_area_right) and state.server_area_right is not None:
                    nei_ip, nei_port = state.neighbor.get('right').split(':')
                    msg = f"TRANSFER_MONSTER|{monster.x}|{monster.y}|{monster.weapon[0]}|{monster.hp}|{monster.id}"
                    asyncio.create_task(send_one_off_message(nei_ip, int(nei_port), msg))
                    monsters_list.remove(monster)
                    print(f"[P2P] Sent message to right neighbor: {nei_ip}:{nei_port}")
                    continue

                elif float(monster.path.data[0]) < float(state.server_area_left) and state.server_area_left is not None:
                    nei_ip, nei_port = state.neighbor.get('left').split(':')
                    msg = f"TRANSFER_MONSTER|{monster.x}|{monster.y}|{monster.weapon[0]}|{monster.hp}|{monster.id}"
                    asyncio.create_task(send_one_off_message(nei_ip, int(nei_port), msg))
                    monsters_list.remove(monster)
                    print(f"[P2P] Sent message to left neighbor: {nei_ip}:{nei_port}")
                    continue


                else:
                    monster.x = monster.path.data[0]
                    monster.y = monster.path.data[1]
                    monster.path = monster.path.next
                    if monster.weapon[0] == "gun":
                        type_str = "long"
                    else:
                        type_str = "short"
                    state.pending_lb_updates.append(f"monster:{monster.id},{monster.x},{monster.y},{type_str},{monster.hp}")

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
        client_id = client.player_id  # FIX: Using the correct Application ID
        if not client_id or client_id not in state.players_pos:
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
        print("CPU:", psutil.cpu_percent(interval=None))
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

skills_dict = {
        "Speed Boost": Skill("Speed Boost", 7, 0, False),
        "Shield": Skill("Shield", 6, 0, False),
        "Bombs": Skill("Bombs", 3, 0, False)
}


#lb functions

async def update_game_weapons_from_lb(weapons_string, bigger=True):
    lb_weapons_set = set()

    if weapons_string and weapons_string != "None":
        weapons_list = weapons_string.split(";")
        for weapon_str in weapons_list:
            if not weapon_str:
                continue
            parts = weapon_str.split(",")
            if len(parts) >= 3:
                x_val = float(parts[0])
                y_val = float(parts[1])
                w_type = parts[2]
                lb_weapons_set.add((x_val, y_val, w_type))

    if bigger:
        for x_val, y_val, w_type in lb_weapons_set:
            weapon_exists = False
            for existing_weapon in state.map_weapons.values():
                if existing_weapon["x"] == x_val and existing_weapon["y"] == y_val and existing_weapon[
                    "type"] == w_type:
                    weapon_exists = True
                    break

            if not weapon_exists:
                new_id = random.randint(1, 1000000)
                while new_id in state.map_weapons:
                    new_id = random.randint(1, 1000000)

                state.map_weapons[new_id] = {
                    "x": x_val,
                    "y": y_val,
                    "type": w_type
                }

                clients_msg = f"DROPPED|{x_val},{y_val}|{w_type}\n".encode("utf-8")
                for client in list(state.active_clients):
                    if client.stream_id is not None:
                        client._quic.send_stream_data(client.stream_id, clients_msg, end_stream=False)
                        client.transmit()

    keys_to_delete = []

    for w_id, existing_weapon in state.map_weapons.items():
        weapon_tuple = (existing_weapon["x"], existing_weapon["y"], existing_weapon["type"])

        if weapon_tuple not in lb_weapons_set:
            keys_to_delete.append((w_id, existing_weapon))

    for w_id, w_data in keys_to_delete:
        del state.map_weapons[w_id]

        clients_msg = f"UNDROPPED|{w_data['x']},{w_data['y']}|{w_data['type']}\n".encode("utf-8")
        for client in list(state.active_clients):
            if client.stream_id is not None:
                client._quic.send_stream_data(client.stream_id, clients_msg, end_stream=False)
                client.transmit()


async def update_game_potions_from_lb(potions_string):
    lb_potions_set = set()

    # בודקים שיש סטרינג ושהוא לא "None"
    if potions_string and potions_string != "None":
        # מפצלים את הסטרינג הגדול לרשימה של שיקויים
        potions_list = potions_string.split(";")
        for potion_str in potions_list:
            if not potion_str:
                continue
            parts = potion_str.split(",")
            if len(parts) >= 3:
                x_val = float(parts[0])
                y_val = float(parts[1])
                p_type = parts[2]
                lb_potions_set.add((x_val, y_val, p_type))

    for x_val, y_val, p_type in lb_potions_set:
        potion_exists = False
        for existing_potion in state.map_potion.values():
            if existing_potion["x"] == x_val and existing_potion["y"] == y_val and existing_potion["type"] == p_type:
                potion_exists = True
                break

        if not potion_exists:
            new_id = random.randint(1, 1000000)
            while new_id in state.map_potion:
                new_id = random.randint(1, 1000000)

            state.map_potion[new_id] = {
                "x": x_val,
                "y": y_val,
                "type": p_type
            }

            clients_msg = f"POTIONS|{x_val},{y_val}|{p_type}\n".encode("utf-8")
            for client in list(state.active_clients):
                if client.stream_id is not None:
                    client._quic.send_stream_data(client.stream_id, clients_msg, end_stream=False)
                    client.transmit()

    keys_to_delete = []

    for p_id, existing_potion in state.map_potion.items():
        potion_tuple = (existing_potion["x"], existing_potion["y"], existing_potion["type"])

        if potion_tuple not in lb_potions_set:
            keys_to_delete.append((p_id, existing_potion))

    for p_id, p_data in keys_to_delete:
        del state.map_potion[p_id]

        clients_msg = f"UNDROPPED|{p_data['x']},{p_data['y']}|{p_data['type']}\n".encode("utf-8")
        for client in list(state.active_clients):
            if client.stream_id is not None:
                client._quic.send_stream_data(client.stream_id, clients_msg, end_stream=False)
                client.transmit()


async def update_game_monsters_from_lb(monsters_string):
    #reset the server monsters list
    global monsters_list
    monsters_list = []

    if monsters_string and monsters_string != "None":

        temp_monsters_list = monsters_string.split(";")
        for monster_str in temp_monsters_list:
            if not monster_str:
                continue
            parts = monster_str.split(",")
            if len(parts) >= 5:
                monster_id = int(parts[0])
                x = float(parts[1])
                y = float(parts[2])
                type_str = parts[3]
                hp = int(parts[4])
                if type_str == "long":
                    type_str = "gun"
                else:
                    type_str = "rifle"

                new_monster = Monster(x,y,type_str, hp, monster_id)
                monsters_list.append(new_monster)


def update_server_area_from_lb():
    for client in list(state.active_clients):
        client_id = client.player_id
        if client_id not in state.players_pos:
            continue

        new_x = float(state.players_pos[client_id].split(",")[0])

        if state.players_control.get(client_id, False):
            # ------------------ מעבר שמאלה ------------------
            if state.server_area_left is not None and new_x < (
                    float(state.server_area_left) - 50) and state.neighbor.get('left') is not None:
                nei_ip = state.neighbor['left'].split(':')[0]
                nei_port = state.neighbor['left'].split(':')[1]

                real_id = state.player_real_id.get(client_id)
                p_name = state.player_name.get(client_id)
                pos = state.players_pos[client_id]
                px, py = pos.split(",")
                inv = state.players_inventory[client_id]
                inv_str = ";".join([f"{i},{inv[i]['type']},{inv[i]['ammo']}" for i in range(INVENTORY_SIZE)])
                hp = state.players_hp[client_id]
                potions_list = state.players_potions.get(client_id, [])
                potions = ",".join(potions_list) if potions_list else "None"

                try:
                    skill = state.players_skills[client_id]
                    skill_str = f"{skill.name},{skill.duration_time},{skill.last_action_time},{skill.is_active}"
                except:
                    skill_str = "Speed Boost,5,0,False"

                msg = f"TRANSFER_PLAYER|{real_id}|{client_id}|{p_name}|{px}|{py}|{hp}|{inv_str}|{potions}|{skill_str}"

                async def safe_transfer_left(c=client, nip=nei_ip, nport=nei_port, m=msg, pname=p_name, cid=client_id):
                    await send_one_off_message(nip, nport, m)
                    state.players_handoff_pending.add(cid)
                    msg_switch = f"SWITCHED|{nip}|{nport}|False\n".encode()
                    if c.stream_id is not None:
                        c._quic.send_stream_data(c.stream_id, msg_switch, end_stream=False)
                        c.transmit()
                    print(f"{pname} has been asked to switch to {nip}:{nport}")

                if client_id not in state.left_common_zone:
                    state.left_common_zone.append(client_id)
                    asyncio.create_task(safe_transfer_left())
                    if new_x <= (float(state.server_area_left) - 50):
                        print(f"Sudden boundary shift (Left)! Initiating Handshake Transfer for {client_id}")
                continue

            # ------------------ מעבר ימינה ------------------
            elif state.server_area_right is not None and new_x > (
                    float(state.server_area_right) + 50) and state.neighbor.get('right') is not None:
                nei_ip = state.neighbor['right'].split(':')[0]
                nei_port = state.neighbor['right'].split(':')[1]

                real_id = state.player_real_id.get(client_id)
                p_name = state.player_name.get(client_id)
                pos = state.players_pos[client_id]
                px, py = pos.split(",")
                inv = state.players_inventory[client_id]
                inv_str = ";".join([f"{i},{inv[i]['type']},{inv[i]['ammo']}" for i in range(INVENTORY_SIZE)])
                hp = state.players_hp[client_id]
                potions_list = state.players_potions.get(client_id, [])
                potions = ",".join(potions_list) if potions_list else "None"

                try:
                    skill = state.players_skills[client_id]
                    skill_str = f"{skill.name},{skill.duration_time},{skill.last_action_time},{skill.is_active}"
                except:
                    skill_str = "Speed Boost,5,0,False"

                msg = f"TRANSFER_PLAYER|{real_id}|{client_id}|{p_name}|{px}|{py}|{hp}|{inv_str}|{potions}|{skill_str}"

                async def safe_transfer_right(c=client, nip=nei_ip, nport=nei_port, m=msg, pname=p_name, cid=client_id):
                    await send_one_off_message(nip, nport, m)
                    state.players_handoff_pending.add(cid)
                    msg_switch = f"SWITCHED|{nip}|{nport}|False\n".encode()
                    if c.stream_id is not None:
                        c._quic.send_stream_data(c.stream_id, msg_switch, end_stream=False)
                        c.transmit()
                    print(f"{pname} has been asked to switch to {nip}:{nport}")

                if client_id not in state.right_common_zone:
                    state.right_common_zone.append(client_id)
                    asyncio.create_task(safe_transfer_right())
                    if new_x >= (float(state.server_area_right) + 50):
                        print(f"Sudden boundary shift (Right)! Initiating Handshake Transfer for {client_id}")
                continue
            else:
                # מוחקים מה-common zone רק אם ה-Transfer לא בטיסה (SWITCHED לא נשלח עדיין)
                if client_id in state.left_common_zone and state.server_area_left is not None:
                    if float(new_x) > (float(state.server_area_left) + 200) and client_id not in state.players_handoff_pending:
                        state.left_common_zone.remove(client_id)
                elif client_id in state.right_common_zone and state.server_area_right is not None:
                    if float(new_x) < (float(state.server_area_right) - 200) and client_id not in state.players_handoff_pending:
                        state.right_common_zone.remove(client_id)
        else:
            continue

async def connect_to_lb():
    while True:
        try:
            print(f"[*] Attempting to connect to LB at {state.lb_host}:{state.lb_port}...")

            reader, writer = await asyncio.open_connection(state.lb_host, state.lb_port , limit=1024 * 1024 * 10)
            state.lb_writer = writer

            connect_msg = f"Server connect|{MY_PUBLIC_IP}|{psutil.cpu_percent()}|{MY_PORT}\n"

            writer.write(connect_msg.encode())
            await writer.drain()

            asyncio.create_task(send_heartbeats_to_lb(writer))

            while True:
                line = await reader.readline()
                if not line:
                    break

                msg = line.decode().strip()


                if msg.startswith("Connected|"):
                    state.server_id = int(msg.split("|")[1])
                    print(f"[LB] Assigned ID: {state.server_id}")



                elif msg.startswith("UpdateStats|"):

                    try:
                        parts = msg.split("|")
                        if len(parts) < 7:
                            print("got a shit msg from the lb")
                        border_l = parts[1]
                        border_r = parts[2]
                        if border_l != "None":
                            state.server_area_left = border_l
                        else:
                            state.server_area_left = None
                        if border_r != "None":
                            state.server_area_right = border_r
                        else:
                            state.server_area_right = None

                        neighbor_l = parts[3]
                        neighbor_r = parts[4]

                        if neighbor_l != "None":
                            state.neighbor["left"] = neighbor_l
                        else:
                            state.neighbor["left"] = None

                        if neighbor_r != "None":
                            state.neighbor["right"] = neighbor_r
                        else:
                            state.neighbor["right"] = None


                        weapons = msg.split("|")[5]
                        await update_game_weapons_from_lb(weapons)



                        potions = msg.split("|")[6]
                        await update_game_potions_from_lb(potions)

                        monsters = msg.split("|")[7]

                        await update_game_monsters_from_lb(monsters)

                        update_server_area_from_lb()

                        players_list = list(state.left_common_zone)
                        for client_id in players_list:
                            if client_id in state.players_handoff_pending:
                                continue  # Transfer בטיסה — לא נוגעים ב-zone
                            if client_id not in state.players_pos:
                                state.left_common_zone.remove(client_id)
                                continue
                            if state.server_area_left is None:
                                state.left_common_zone.remove(client_id)
                                continue
                            x = float(state.players_pos[client_id].split(",")[0])
                            if x > (float(state.server_area_left) + 200):
                                state.left_common_zone.remove(client_id)

                        players_list = list(state.right_common_zone)
                        for client_id in players_list:
                            if client_id in state.players_handoff_pending:
                                continue  # Transfer בטיסה — לא נוגעים ב-zone
                            if client_id not in state.players_pos:
                                state.right_common_zone.remove(client_id)
                                continue
                            if state.server_area_right is None:
                                state.right_common_zone.remove(client_id)
                                continue
                            x = float(state.players_pos[client_id].split(",")[0])
                            if x < (float(state.server_area_right) - 200):
                                state.right_common_zone.remove(client_id)





                    except Exception as e:
                        print("[LB] Failed parsing UpdateArea:", e)



                elif msg.startswith("ExpectPlayer"):

                    try:

                        # חיתוך ההודעה לפי '|' וניקוי רווחים מיותרים

                        parts = [p.strip() for p in msg.split("|")]

                        if len(parts) >= 8:
                            p_id = parts[1]
                            fake_id = parts[2]
                            p_name = parts[3]
                            px = float(parts[4])
                            py = float(parts[5])
                            php = int(parts[6])
                            pinv_str = parts[7]


                            potions_str = parts[8] if len(parts) >= 9 else "None"
                            inv_dict = {int(i): {"type": "none", "ammo": 0} for i in range(INVENTORY_SIZE)}
                            if pinv_str and pinv_str.lower() not in ("none", "empty"):
                                items_list = pinv_str.split(";")
                                for item_str in items_list:
                                    if not item_str:
                                        continue

                                    try:

                                        slot_str, w_type, ammo_str = item_str.split(",")
                                        slot = int(slot_str)
                                        if 0 <= slot < INVENTORY_SIZE:
                                            inv_dict[slot] = {"type": w_type, "ammo": int(ammo_str)}

                                    except ValueError:
                                        pass

                            # 2. חילוץ הפושנים בצורה בטוחה שמתעלמת מרווחים
                            expected_potions = [p.strip() for p in potions_str.split(",") if p.strip() and p.strip().lower() not in ("none", "empty", "[]")]
                            # 3. שומרים הכל במילון

                            state.expected_players[fake_id] = {

                                "id": p_id,
                                "x": px,
                                "y": py,
                                "hp": php,
                                "inv": inv_dict,
                                "potions": expected_potions,
                                "is_transfer": False

                            }

                            print(f"[LB] Expected player {p_name} (Fake ID: {fake_id}) is ready to transfer.")


                    except Exception as e:

                        print(f"[LB] Error parsing ExpectPlayer: {e}")
                # expected_players = {} #fake_id -> {id,x,y,hp,inv}
                # ExpectPlayer | {p_id} | {fake_id} | {p_name} | {px} | {py} | {php} | {pinv}
                elif msg.startswith("CHAT"):
                    try:
                        client_name = msg.split("|")[1]
                        player_msg = msg.split("|")[2]
                        send_msg = f"CHAT|{client_name}|{player_msg}\n".encode()
                        for client in list(state.active_clients):
                            if client.stream_id is None:
                                continue
                            client._quic.send_stream_data(client.stream_id, send_msg, end_stream=False)
                            client.transmit()
                    except:
                        print("Error while getting a chat msg from lb")



                elif msg.startswith("TransferClient|"):

                    try:

                        _, c_id, n_ip, n_port = msg.split("|")

                        for client in list(state.active_clients):

                            if client.player_id == c_id:

                                print(f"[LB] Sending SWITCHED to client {c_id} -> {n_ip}:{n_port}")

                                # מתקנים מ-SWITCH ל-SWITCHED בדיוק בפורמט שהקליינט מצפה לו (כולל דגל ה-host)

                                switch_msg = f"SWITCHED|{n_ip}|{n_port}|False\n".encode()

                                if client.stream_id is not None:

                                    client._quic.send_stream_data(client.stream_id, switch_msg, end_stream=False)

                                    client.transmit()

                    except Exception as e:

                        print(f"[LB] Error parsing TransferClient: {e}")

        except Exception as e:
            print(f"[LB] Connection error: {e}. Retrying in 5 seconds...")
            state.lb_writer = None
            await asyncio.sleep(5)


async def send_to_lb(message: str):
    if state.lb_writer is not None:
        try:
            # חשוב להוסיף \n בסוף כדי שה-LB יוכל לקרוא עם readline()
            if not message.endswith("\n"):
                message += "\n"

            state.lb_writer.write(message.encode())
            await state.lb_writer.drain()
        except Exception as e:
            print(f"Error sending to LB: {e}")
            state.lb_writer = None  # איפוס כדי ש-connect_to_lb ינסה להתחבר מחדש
    else:
        print("LB connection not available.")


async def register_with_lb_once(lb_ip: str, timeout: float = 5.0) -> bool:
    try:
        print(f"[*] Trying one-shot registration to LB {lb_ip}:{LB_PORT} ...")
        reader, writer = await asyncio.open_connection(lb_ip, LB_PORT, limit=1024 * 1024 * 10)

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
                    print(msg)
                    parts = msg.split("|")
                    if len(parts) < 8:
                        print(f"wrong msg from lb - only {len(parts)} parts")
                    border_l = parts[1]
                    border_r = parts[2]
                    if border_l != "None":
                        state.server_area_left =  border_l
                    if border_r != "None":
                        state.server_area_right = border_r

                    neighbor_l = parts[3]
                    neighbor_r = parts[4]
                    if neighbor_l != "None":
                        state.neighbor["left"] = neighbor_l
                    else:
                        state.neighbor["left"] = None

                    if neighbor_r != "None":
                        state.neighbor["right"] = neighbor_r
                    else:
                        state.neighbor["right"] = None

                    weapons = parts[5]
                    weapons = weapons.split(";")

                    for weapon in weapons:
                        x_str = weapon.split(",")[0]
                        y_str = weapon.split(",")[1]
                        w_str = weapon.split(",")[2]
                        new_id = random.randint(1, 1000000)
                        while new_id in state.map_weapons:
                            new_id = random.randint(1, 1000000)

                        state.map_weapons[new_id] = {
                            "x": float(x_str),
                            "y": float(y_str),
                            "type": w_str,
                        }
                    potions = msg.split("|")[6]
                    potions = potions.split(";")
                    for potion in potions:
                        x_str = potion.split(",")[0]
                        y_str = potion.split(",")[1]
                        p_type = potion.split(",")[2]

                        new_id = random.randint(1, 1000000)
                        while new_id in state.map_potion:
                            new_id = random.randint(1, 1000000)

                        state.map_potion[new_id] = {
                            "x": float(x_str),
                            "y": float(y_str),
                            "type": p_type,
                        }

                    monsters = msg.split("|")[7]

                    await update_game_monsters_from_lb(monsters)
                    asyncio.create_task(monsters_manager())


                    writer.close()
                    await writer.wait_closed()
                    return True

                except Exception as e:
                    print("[LB] Failed parsing UpdateArea:", e)
                    break

        writer.close()
        await writer.wait_closed()

        print("[LB] One-shot registration failed or timed out.")
        return False

    except Exception as e:
        print(f"[LB] Connection error in one-shot registration: {e}")
        return False


async def send_heartbeats_to_lb(writer):
    try:
        while True:
            if state.server_id is not None:
                msg = f"Server heartbeat|{state.server_id}|{psutil.cpu_percent()}"

                to_send = state.pending_lb_updates.copy()
                state.pending_lb_updates.clear()

                for report in to_send:
                    msg += "|" + report

                msg += "\n"
                writer.write(msg.encode())
                await writer.drain()

            await asyncio.sleep(5)

    except Exception as e:
        print("[LB] Heartbeat stopped:", e)

#gs connection functions
async def send_one_off_message(target_ip, target_port, message):
    try:
        # פותחים חיבור מהיר לשכן
        reader, writer = await asyncio.open_connection(target_ip, target_port)

        # שולחים את ההודעה (חשוב להוסיף \n כדי שהצד השני יקרא שורה שלמה)
        writer.write((message + "\n").encode())
        await writer.drain()

        # סוגרים את החיבור מיד כי סיימנו
        writer.close()
        await writer.wait_closed()

    except Exception as e:
        print(f"[Peer-to-Peer] Failed to send message to {target_ip}:{target_port} - {e}")


async def handle_neighbor_connection(reader, writer):
    global  monsters_list
    try:
        line = await reader.readline()
        if line:
            msg = line.decode().strip()
            print(f"[Peer-to-Peer] Received from neighbor: {msg}")

            parts = msg.split("|")

            if parts[0] == "TRANSFER_PLAYER":
                real_id = parts[1]
                old_client_id = parts[2]
                p_name = parts[3]
                px = float(parts[4])
                py = float(parts[5])
                hp = int(parts[6])
                inv_str = parts[7]
                potions_str = parts[8]

                print(f"[Peer-to-Peer] Receiving player {p_name} ({old_client_id}) from neighbor")

                inv_dict = {i: {"type": "none", "ammo": 0} for i in range(INVENTORY_SIZE)}
                if inv_str and inv_str.lower() not in ("none", "empty"):
                    items_list = inv_str.split(";")
                    for item_str in items_list:
                        if not item_str: continue
                        try:
                            slot_str, w_type, ammo_str = item_str.split(",")
                            slot = int(slot_str)
                            if 0 <= slot < INVENTORY_SIZE:
                                inv_dict[slot] = {"type": w_type, "ammo": int(ammo_str)}
                        except ValueError:
                            pass

                expected_potions = [p.strip() for p in potions_str.split(",") if
                                    p.strip() and p.strip().lower() not in ("none", "empty", "[]")]

                source_ip = writer.get_extra_info('peername')[0]
                source_port = int(parts[10]) if len(parts) > 10 else None  # MY_PORT של השרת השולח

                state.expected_players[old_client_id] = {
                    "id": real_id,
                    "x": px,
                    "y": py,
                    "hp": hp,
                    "inv": inv_dict,
                    "potions": expected_potions,
                    "connectMsg": False,
                    "is_transfer": True,
                    "source_ip": source_ip,
                    "source_port": source_port,
                }

            elif parts[0] == "CLIENT_CONNECTED":
                real_id = parts[1]
                client_id = parts[2]
                nei_ip = parts[3]
                nei_port = int(parts[4])

                if client_id in state.players_pos:
                    state.players_control[client_id] = False  # נעילת סמכות

                    px, py = state.players_pos[client_id].split(",")
                    inv = state.players_inventory.get(client_id,
                                                      {i: {"type": "none", "ammo": 0} for i in range(INVENTORY_SIZE)})
                    inv_str = ";".join([f"{i},{inv[i]['type']},{inv[i]['ammo']}" for i in range(INVENTORY_SIZE)])
                    hp = state.players_hp.get(client_id, 100)
                    potions_list = state.players_potions.get(client_id, [])
                    potions = ",".join(potions_list) if potions_list else "None"

                    # במקרה שאין לסקיל פונקציית ברירת מחדל, נגן על זה
                    try:
                        skill = state.players_skills[client_id]
                        skill_str = f"{skill.name},{skill.duration_time},{skill.last_action_time},{skill.is_active}"
                    except:
                        skill_str = "Speed Boost,5,0,False"

                    # הרכבת תמונת המצב הסופית בהחלט!
                    msg = f"AUTHORITY_TRANSFER|{real_id}|{client_id}|{px}|{py}|{hp}|{inv_str}|{potions}|{skill_str}"

                    asyncio.create_task(send_one_off_message(nei_ip, nei_port, msg))

                    for client in list(state.active_clients):
                        if client.player_id == client_id:
                            # הדלקת חסימת הניתוק באופן מיידי! לפני שהקליינט מספיק להגיב
                            client.is_handed_off = True

                            msg_switch = f"CHANGECONTROL|{nei_ip}|{nei_port}|True\n".encode()
                            if client.stream_id is not None:
                                client._quic.send_stream_data(client.stream_id, msg_switch, end_stream=False)
                                client.transmit()

                            async def delayed_close(c, cid):
                                # FIX 2: Increased delay to 2.5 seconds.
                                await asyncio.sleep(2.5)
                                c._quic.close()
                                c.transmit()
                                c.broadcast_remove(cid)

                                if c in state.active_clients:
                                    state.active_clients.remove(c)

                                still_active = any(other.player_id == cid for other in state.active_clients)
                                if not still_active:
                                    state.players_pos.pop(cid, None)
                                    state.players_hp.pop(cid, None)
                                    state.players_inventory.pop(cid, None)
                                    state.players_potions.pop(cid, None)
                                    state.players_skills.pop(cid, None)
                                    state.player_name.pop(cid, None)
                                    state.players_control.pop(cid, None)
                                    state.player_real_id.pop(cid, None)

                                # Transfer הסתיים — מנקים את הגנת ה-in-flight
                                state.players_handoff_pending.discard(cid)

            elif parts[0] == "AUTHORITY_TRANSFER":

                real_id = parts[1]
                client_id = parts[2]
                px = float(parts[3])
                py = float(parts[4])
                hp = int(parts[5])
                inv_str = parts[6]
                potions_str = parts[7]
                skill_str = parts[8]

                # --- התיקונים ---
                state.player_real_id[client_id] = real_id  # שמירת מזהה המשתמש האמיתי לדיווחי LB
                state.players_control[client_id] = True  # לקיחת סמכות רשמית בשרת החדש
                # ----------------

                # אנחנו מסירים את דריסת ה- players_pos כאן!
                # השרת החדש כבר עוקב אחרי המיקום האמיתי של השחקן ב-Live דרך ה-UDP.
                # החזרה למיקום של השרת הישן תגרום לכישלון ב-check_movement ולניתוק השחקן.
                state.players_hp[client_id] = hp

                inv_dict = {i: {"type": "none", "ammo": 0} for i in range(INVENTORY_SIZE)}

                if inv_str and inv_str.lower() not in ("none", "empty"):
                    for item_str in inv_str.split(";"):
                        if item_str:
                            try:
                                slot_str, w_type, ammo_str = item_str.split(",")
                                inv_dict[int(slot_str)] = {"type": w_type, "ammo": int(ammo_str)}
                            except:
                                pass

                state.players_inventory[client_id] = inv_dict

                expected_potions = [p.strip() for p in potions_str.split(",") if
                                    p.strip() and p.strip().lower() not in ("none", "empty", "[]")]

                state.players_potions[client_id] = expected_potions

                try:
                    s_name, s_dur, s_last, s_act = skill_str.split(",")
                    state.players_skills[client_id] = Skill(s_name, float(s_dur), float(s_last), s_act == "True")
                except Exception as e:
                    state.players_skills[client_id] = Skill("Speed Boost", 5, 0, False)

                print(
                    f"[Peer-to-Peer] Authority Transfer Complete for {client_id}. Perfectly synced and CONTROL TAKEN!")

            elif parts[0] == "TRANSFER_BULLET":
                # FIX 3c: Receive and track crossing bullets from neighbor servers
                bullet_id = int(parts[1])
                gun_type = parts[2]
                x = float(parts[3])
                y = float(parts[4])
                angle = float(parts[5])

                while bullet_id in state.active_bullets:
                    bullet_id = random.randint(1, MAX_BULLETS)

                state.active_bullets[bullet_id] = {
                    "x": x,
                    "y": y,
                    "angle": angle,
                }
                print(f"[Peer-to-Peer] Received crossing bullet {bullet_id} from neighbor")
                # Track it locally using monster_gun_tracking (works globally for any bullet)
                asyncio.create_task(monster_gun_tracking(bullet_id, gun_type, x, y, angle))

            elif parts[0] == "TRANSFER_MONSTER":
                    x = float(parts[1])
                    y = float(parts[2])
                    type_str = parts[3]
                    hp = int(parts[4])
                    monster_id = int(parts[5])
                    new_monster = Monster(x,y,type_str,hp, monster_id)
                    monsters_list.append(new_monster)

    except Exception as e:
        print(f"[Peer-to-Peer] Error handling message: {e}")
    finally:
        writer.close()
        await writer.wait_closed()

async def main():
    global lb_ip

    while True:


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
        idle_timeout=300.0,
    )
    config.load_cert_chain("cert.pem", "key.pem")
    print("Starting QUIC server on udp:0.0.0.0:4433")
    asyncio.create_task(serve(
        host= "0.0.0.0",
        port=int(MY_PORT),
        configuration=config,
        create_protocol=EchoQuicProtocol,
    ))
    asyncio.create_task(connect_to_lb())
    asyncio.create_task(check_cpu())
    asyncio.create_task(track_server_fps())
    peer_server = await asyncio.start_server(handle_neighbor_connection, "0.0.0.0", int(MY_PORT) + 4000)
    asyncio.create_task(peer_server.serve_forever())
    print(f"[*] Started TCP Peer-to-Peer server on {MY_IP}:{MY_PORT}")
    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass