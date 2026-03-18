import asyncio
import math
import random

import psutil
import heapq
import time

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
WEAPON_LIST = [["gun", 20, TILE_SIZE * 10],["rifle" ,10 , TILE_SIZE * 20],["rpg",30,TILE_SIZE*25]]
WEAPON_NAMES = [w[0] for w in WEAPON_LIST]
WEAPON_DAMAGE = [w[1] for w in WEAPON_LIST]
WEAPON_RANGE = [w[2] for w in WEAPON_LIST]
BOMB_WEAPON = ["bomb", 35, 15]

WEAPON_AMMO = {"gun": 30, "rifle": 20, "rpg": 5}
MONSTER_CHANGE_PATH_EVERY_SET_SECONDS = 3
MONSTER_ACCURACY = 65
MAX_POTION = 9000
POTION_LIST = [["Potion", 40],["Poison",5]]
counter = count()
monsters_list = []
SERVER_FPS = 0
SKILL_COOL_TIME = 1

LB_PORT = 8080

MY_IP = gs_and_lb_helper_functions.get_local_ip()
MY_PORT = 4433


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
    pending_lb_updates = []

    #game info
    map_weapons = {}  # weapon_id -> {x, y, type}
    game_map = load_map()
    monsters = {}
    map_potion = {}


state = GameState()


class EchoQuicProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        state.active_clients.add(self)
        self.stream_id = None
        self.recv_buffer = ""
        self.player_id = self._quic.host_cid.hex()

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

        # CONNECTED
        client_id = self.player_id
        # CONNECTED
        if data_str.startswith("Connected|"):
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting Connected command!")
                self.disconnect()
                return

            if len(parts) >= 6:
                sent_id = parts[1]
                client_name = parts[2]
                pos_str = parts[3]

                try:
                    c_x, c_y = map(float, pos_str.split(","))
                    c_hp = int(parts[4])
                except ValueError:
                    print("Cheat/Error detected: Invalid numbers in Connected!")
                    self.disconnect()
                    return

                # 1. בונים את האינוונטרי שהקליינט טוען שיש לו
                c_inv_dict = {}
                inv_items = parts[5].split("-")
                for i in range(INVENTORY_SIZE):
                    if i < len(inv_items):
                        w_type, ammo = inv_items[i].split(",")
                        c_inv_dict[i] = {"type": w_type, "ammo": int(ammo)}
                    else:
                        c_inv_dict[i] = {"type": "none", "ammo": 0}

                # 2. שלב האבטחה (Validation) מול הנתונים מה-LB
                if sent_id in state.expected_players:
                    expected_data = state.expected_players[sent_id]

                    e_x = expected_data["x"]
                    e_y = expected_data["y"]
                    e_hp = expected_data["hp"]
                    e_inv = expected_data["inv"]

                    # בדיקת מיקום: שמים סובלנות (Tolerance) של 10 פיקסלים בגלל המרות של float
                    if abs(c_x - e_x) > 10 or abs(c_y - e_y) > 10:
                        print(f"Cheat detected! Position mismatch. Client claimed: {c_x},{c_y}. Expected: {e_x},{e_y}")
                        self.disconnect()
                        return

                    # בדיקת חיים: התאמה מדויקת
                    if c_hp != e_hp:
                        print(f"Cheat detected! HP mismatch. Client claimed: {c_hp}. Expected: {e_hp}")
                        self.disconnect()
                        return

                    # בדיקת אינוונטרי: בודק כל משבצת ותחמושת
                    for i in range(INVENTORY_SIZE):
                        if c_inv_dict[i]["type"] != e_inv[i]["type"] or c_inv_dict[i]["ammo"] != e_inv[i]["ammo"]:
                            print(f"Cheat detected! Inventory mismatch at slot {i}.")
                            self.disconnect()
                            return

                    print(f"Player {client_name} passed security validation successfully!")

                    # מעדכנים את ה-ID מ-Fake ID ל-Real ID
                    real_id = expected_data["id"]
                    self.player_id = real_id
                    client_id = real_id

                    # מוחקים את השחקן מרשימת המצופים (כדי למנוע שימוש חוזר באותו Fake ID)
                    del state.expected_players[sent_id]

                else:
                    # הגעה ראשונית לשרת (ללא מעבר P2P) או כניסה רגילה מהלוגין
                    self.player_id = sent_id
                    client_id = sent_id

                # --- אתחול הנתונים לאחר שהקליינט עבר את הבדיקה בהצלחה ---
                x_str = pos_str.split(",")[0]
                if x_str < (state.server_area_right + SCREEN_WIDTH/2):
                    if x_str > (state.server_area_left - SCREEN_WIDTH/2):
                        state.players_pos[client_id] = pos_str
                        state.players_hp[client_id] = c_hp
                        state.players_inventory[client_id] = c_inv_dict
                        state.player_name[client_id] = client_name

                        state.players_control[client_id] = True
                        state.players_potions[client_id] = 0
                        state.players_skills[client_id] = Skill("Speed Boost", 5, 0, False)
                    else:
                        return
                else:
                    return

            else:
                print("Cheat/Error detected: Missing arguments in Connected command!")
                self.disconnect()
                return
            print("player connected!")
            # --- המשך ההתחברות והשליחה למשתמשים האחרים ---
            id_msg = f"SETID|{client_id}\n".encode()
            if self.stream_id is not None:
                self._quic.send_stream_data(self.stream_id, id_msg, end_stream=False)

            for other_id, pos in state.players_pos.items():
                if other_id == client_id:
                    continue
                hp = state.players_hp.get(other_id, "100")
                msg = f"UPDATE|{other_id}|{pos}|{hp}\n".encode()
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

        elif data_str.startswith("ConnectedID"):
            print(client_id, "connected from other server!")
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting Connected command!")
                return
            self.player_id = parts[1]
            client_id = self.player_id
            state.players_control[client_id] = (parts[2] == "True")

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
                if other_id == client_id:
                    continue
                if other_pos == new_pos:
                    self.disconnect()
                    print("player has been kicked! player collision")
                    return

            if check_movement(new_pos, state.players_pos[client_id], state.players_skills[self.player_id]):
                state.players_pos[client_id] = new_pos
                self.broadcast_player(client_id, new_pos, state.players_hp[client_id], False)
                new_x = float(new_pos.split(",")[0])

                if client_id not in state.players_control:
                    state.players_control[client_id] = True

                if state.players_control[client_id]:

                    # ------------------ מעבר שמאלה ------------------
                    if state.neighbor.get('left') is not None:
                        if state.server_area_left is not None and new_x < float(state.server_area_left):
                            nei_ip = state.neighbor['left'].split(':')[0]
                            nei_port = state.neighbor['left'].split(':')[1]

                            if new_x  > (float(state.server_area_right) - float(SCREEN_WIDTH)/2):
                                # דגל חסימת הצפות! בודק אם טרם שלחנו
                                if not getattr(self, 'spectator_sent_left', False):
                                    self.spectator_sent_left = True  # מסמן ששלחנו

                                    # -------transfer client-------
                                    inv = state.players_inventory[client_id]
                                    inv_str = "-".join(
                                        [f"{inv[i]['type']},{inv[i]['ammo']}" for i in range(INVENTORY_SIZE)])
                                    skill = state.players_skills[client_id]
                                    skill_str = f"{skill.name},{skill.duration_time},{skill.last_action_time},{skill.is_active}"
                                    pos = state.players_pos[client_id]
                                    hp = state.players_hp[client_id]
                                    potions = state.players_potions[client_id]
                                    msg = f"TRANSFER_PLAYER|{client_id}|{pos}|{hp}|{potions}|{inv_str}|{skill_str}"

                                    asyncio.create_task(send_one_off_message(nei_ip, nei_port, msg))

                                    msg_switch = f"SWITCHED|{nei_ip}|{nei_port}|False\n".encode()
                                    self._quic.send_stream_data(self.stream_id, msg_switch, end_stream=False)
                                    self.transmit()
                            else:
                                msg_switch = f"SWITCHED|{nei_ip}|{nei_port}|True\n".encode()
                                self._quic.send_stream_data(self.stream_id, msg_switch, end_stream=False)
                                self.transmit()

                                if self in state.active_clients:
                                    state.active_clients.remove(self)
                                self.disconnect()
                                print("out of border")
                        else:
                            # מאפס את הדגל אם השחקן חזר פנימה לשרת המקורי
                            self.spectator_sent_left = False


                    # ------------------ מעבר ימינה ------------------
                    elif state.neighbor.get('right') is not None:
                        if state.server_area_right is not None and new_x < float(state.server_area_right):
                            nei_ip = state.neighbor['right'].split(':')[0]
                            nei_port = state.neighbor['right'].split(':')[1]

                            if new_x  < (float(state.server_area_right) + float(SCREEN_WIDTH)/2):
                                # דגל חסימת הצפות! בודק אם טרם שלחנו
                                if not getattr(self, 'spectator_sent_right', False):
                                    self.spectator_sent_right = True  # מסמן ששלחנו

                                    # -------transfer client-------
                                    inv = state.players_inventory[client_id]
                                    inv_str = "-".join(
                                        [f"{inv[i]['type']},{inv[i]['ammo']}" for i in range(INVENTORY_SIZE)])
                                    skill = state.players_skills[client_id]
                                    skill_str = f"{skill.name},{skill.duration_time},{skill.last_action_time},{skill.is_active}"
                                    pos = state.players_pos[client_id]
                                    hp = state.players_hp[client_id]
                                    potions = state.players_potions[client_id]
                                    msg = f"TRANSFER_PLAYER|{client_id}|{pos}|{hp}|{potions}|{inv_str}|{skill_str}"

                                    asyncio.create_task(send_one_off_message(nei_ip, nei_port, msg))

                                    msg_switch = f"SWITCHED|{nei_ip}|{nei_port}|False\n".encode()
                                    self._quic.send_stream_data(self.stream_id, msg_switch, end_stream=False)
                                    self.transmit()

                            else:
                                # חצה לחלוטין
                                msg_switch = f"SWITCHED|{nei_ip}|{nei_port}|True\n".encode()
                                self._quic.send_stream_data(self.stream_id, msg_switch, end_stream=False)
                                self.transmit()

                                if self in state.active_clients:
                                    state.active_clients.remove(self)
                                self.disconnect()
                                print("out of border")

                        else:
                            # מאפס את הדגל אם השחקן חזר פנימה לשרת המקורי
                            self.spectator_sent_right = False

            else:
                self.disconnect()
                print("player has been kicked! movement problem")
        # ATTACK
        elif data_str.startswith("CHANGECONTROL|"):
            parts = data_str.split("|")
            if len(parts) == 2:
                state.players_control[client_id] = parts[1]


        elif data_str.startswith("ATTACK|"):
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

                center_x = float(x_str) + 32
                center_y = float(y_str) + 32

                state.active_bullets[new_id] = {
                    "x": center_x + 28,
                    "y": center_y - 8,
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
            center_x = float(x_str) + 32
            center_y = float(y_str) + 32

            state.active_bullets[new_id] = {
                "x": center_x + 28,
                "y": center_y - 8,
                "angle": angle,
            }
            print("shooting!")
            asyncio.create_task(self.gun_tracking(new_id, weapon))

        # PICKUP
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
            found_potion_id = None

            for p_id, p_data in state.map_potion.items():
                if abs(p_data["x"] - px) <= TOLERANCE and abs(p_data["y"] - py) <= TOLERANCE:
                    print(p_data["type"])
                    if p_data["type"] == pickup_type:
                        print("sup dog up the hp")
                        state.players_potions[client_id] += 1
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
            try:
                parts = data_str.split("|")
            except:
                print("Error while splitting the USE command!")
                return
            if len(parts) < 2:
                return

            item_name = parts[1]

            if client_id not in state.players_hp:
                return
            if state.players_potions[client_id] <= 0:
                return

            if item_name == "Potion":
                state.players_hp[client_id] += UP_HP
                if state.players_hp[client_id] > 100:
                    state.players_hp[client_id] = 100
                state.players_potions[client_id] -= 1
                self.broadcast_player(client_id, state.players_pos[client_id], state.players_hp[client_id], True)

            elif item_name == "Poison":
                if len(parts) < 3:
                    return
                pos = parts[2]
                poison_x, poison_y = map(float, pos.split(","))
                state.players_potions[client_id] -= 1
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
            msg = parts[1]
            state.pending_lb_updates.append(f"CHAT:{msg},{client_id}")
            self.broadcast_chat(msg, state.player_name[client_id])

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
                self.broadcast_skill(client_id, state.players_skills[client_id],False)
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
            if client == self and not to_yourself:
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
        client_id = self.player_id

        # נודיע לכולם שהשחקן התנתק מהמפה
        self.broadcast_remove(client_id)

        # נחלץ את ה-Real ID כדי לשלוח ל-LB
        real_id = state.player_real_id.get(client_id)

        # נשמור רק אם יש לו Real ID ואם הוא עדיין קיים במילוני הנתונים
        if real_id and client_id in state.players_pos and client_id in state.players_hp and client_id in state.players_inventory:
            pos = state.players_pos[client_id]
            try:
                x, y = pos.split(",")
            except:
                x, y = 0, 0

            hp = state.players_hp[client_id]
            inv = state.players_inventory[client_id]

            # הופכים את המילון של התיק למחרוזת בפורמט שביקשת
            inv_items = []
            for i in range(INVENTORY_SIZE):
                if i in inv:
                    inv_items.append(f"{inv[i]['type']},{inv[i]['ammo']}")
                else:
                    inv_items.append("none,0")
            inv_str = "-".join(inv_items)

            # מוסיפים את הודעת השמירה לתור שיישלח ל-Load Balancer ב-Heartbeat הבא
            save_msg = f"SAVE:{real_id},{x},{y},{hp},{inv_str}"
            state.pending_lb_updates.append(save_msg)
            print(f"Added SAVE request for player {real_id}")

        # מחיקת השחקן מכל המילונים הרלוונטיים (בטוח, ללא קריסות KeyError)
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
        for _ in range(gun_range):
            x, y = get_next_bullet_position(x, y, angle)
            state.active_bullets[bullet_id]["x"] = x
            state.active_bullets[bullet_id]["y"] = y

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
    if y >= len(state.game_map): return False
    if y < 0: return False
    if x >= len(state.game_map[0]): return False
    if x < 0: return False
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
        "Speed Boost": Skill("Speed Boost", 10, 0, False),
        "Shield": Skill("Shield", 6, 0, False),
        "Bombs": Skill("Bombs", 7, 0, False)
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

async def connect_to_lb():
    while True:
        try:
            print(f"[*] Attempting to connect to LB at {state.lb_host}:{state.lb_port}...")

            reader, writer = await asyncio.open_connection(state.lb_host, state.lb_port , limit=1024 * 1024 * 10)
            state.lb_writer = writer

            connect_msg = f"Server connect|{MY_IP}|{psutil.cpu_percent()}|{MY_PORT}\n"

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

                    except Exception as e:
                        print("[LB] Failed parsing UpdateArea:", e)

                elif msg.startswith("ExpectPlayer"):
                        try:
                            # חיתוך ההודעה לפי '|' וניקוי רווחים מיותרים
                            parts = [p.strip() for p in msg.split("|")]

                            # מוודאים שיש לנו את כל 8 החלקים (0 עד 7)
                            if len(parts) >= 8:
                                p_id = parts[1]
                                fake_id = parts[2]
                                p_name = parts[3]
                                px = float(parts[4])
                                py = float(parts[5])
                                php = int(parts[6])
                                pinv_str = parts[7]

                                # 1. קודם כל מאתחלים תיק ריק כברירת מחדל
                                inv_dict = {int(i): {"type": "none", "ammo": 0} for i in range(INVENTORY_SIZE)}

                                # 2. בודקים אם יש נתונים אמיתיים (מוודאים שזה לא "Empty" או "None")
                                if pinv_str and pinv_str not in ("None", "Empty"):
                                    # הלוגין סרבר מפריד פריטים עם נקודה-פסיק
                                    items_list = pinv_str.split(";")
                                    for item_str in items_list:
                                        if not item_str:
                                            continue

                                        try:
                                            # הלוגין סרבר שולח 3 נתונים: סלוט, סוג, תחמושת
                                            slot_str, w_type, ammo_str = item_str.split(",")
                                            slot = int(slot_str)

                                            # מכניסים לתיק רק אם הסלוט חוקי (0 עד 4)
                                            if 0 <= slot < INVENTORY_SIZE:
                                                inv_dict[slot] = {"type": w_type, "ammo": int(ammo_str)}
                                        except ValueError:
                                            # אם יש פריט משובש מהדאטה-בייס, נתעלם ממנו כדי שהשרת לא יקרוס
                                            pass

                                # 3. שומרים במילון תחת ה-fake_id
                                state.expected_players[fake_id] = {
                                    "id": p_id,
                                    "x": px,
                                    "y": py,
                                    "hp": php,
                                    "inv": inv_dict
                                }

                                print(f"[LB] Expected player {p_name} (Fake ID: {fake_id}) is ready to transfer.")

                        except Exception as e:
                            print(f"[LB] Error parsing ExpectPlayer: {e}")
                    #expected_players = {} #fake_id -> {id,x,y,hp,inv}
                    #ExpectPlayer | {p_id} | {fake_id} | {p_name} | {px} | {py} | {php} | {pinv}
                elif msg.startswith("GET-MONSTER"):
                    try:
                        parts = msg.split("|")[1:]
                        for monsters in parts:
                            pixel_x = monsters.split(",")[0]
                            pixel_y = monsters.split(",")[1]
                            hp = monsters.split(",")[2]
                            monster = Monster(pixel_x, pixel_y, hp)
                            monsters_list.append(monster)
                    except:
                        print("Error while getting monsters from lb")




                elif msg.startswith("TransferClient|"):
                    _, c_id, n_ip, n_port = msg.split("|")

                    for client in list(state.active_clients):
                        if client._quic.host_cid.hex() == c_id:
                            print(f"[LB] Sending SWITCH to client {c_id} -> {n_ip}:{n_port}")

                            switch_msg = f"SWITCH|{n_ip}|{n_port}\n".encode()
                            client._quic.send_stream_data(client.stream_id, switch_msg)
                            client.transmit()

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
                    if len(parts) < 7:
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
    try:
        line = await reader.readline()
        if line:
            msg = line.decode().strip()
            print(f"[Peer-to-Peer] Received from neighbor: {msg}")

            parts = msg.split("|")


            if parts[0] == "TRANSFER_PLAYER":
                client_id = parts[1]
                pos = parts[2]
                hp = int(parts[3])
                potions = int(parts[4])
                inv_str = parts[5]
                skill_str = parts[6]

                print(f"[Peer-to-Peer] Receiving player {client_id} from neighbor")

                state.players_pos[client_id] = pos
                state.players_hp[client_id] = hp
                state.players_potions[client_id] = potions
                state.players_control[client_id] = True

                state.players_inventory[client_id] = {}
                inv_items = inv_str.split("-")
                for i in range(INVENTORY_SIZE):
                    w_type, ammo = inv_items[i].split(",")
                    state.players_inventory[client_id][i] = {"type": w_type, "ammo": int(ammo)}

                s_name, s_dur, s_last, s_act = skill_str.split(",")
                state.players_skills[client_id] = Skill(s_name, float(s_dur), float(s_last), s_act == "True")


    except Exception as e:
        print(f"[Peer-to-Peer] Error handling message: {e}")
    finally:
        writer.close()
        await writer.wait_closed()



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
    print("Starting QUIC server on udp:0.0.0.0:4433")
    asyncio.create_task(serve(
        host=MY_IP,
        port=MY_PORT,
        configuration=config,
        create_protocol=EchoQuicProtocol,
    ))
    asyncio.create_task(connect_to_lb())
    asyncio.create_task(check_cpu())
    asyncio.create_task(monsters_manager())
    asyncio.create_task(track_server_fps())
    peer_server = await asyncio.start_server(handle_neighbor_connection, MY_IP, MY_PORT)
    asyncio.create_task(peer_server.serve_forever())
    print(f"[*] Started TCP Peer-to-Peer server on {MY_IP}:{MY_PORT}")
    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass