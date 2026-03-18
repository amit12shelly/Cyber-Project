import asyncio
import time

import server
import weapons_manager
import potions_manager

WIDTH = 1920 * 64
LB_IP = "0.0.0.0"
LB_PORT = 8080
HEARTBEAT_TIMEOUT = 15

LOGIN_SERVER_IP = "127.0.0.1"
LOGIN_SERVER_PORT = 8821

MAP_NAME = "map.txt"

servers = []
next_server_id = 0


async def forward_save_to_login(message):
    try:
        reader, writer = await asyncio.open_connection(LOGIN_SERVER_IP, LOGIN_SERVER_PORT)
        writer.write(f"{message}\n".encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        print(f"[!] LB failed to forward to login: {e}")


def serialize_items(items_dict):
    return ";".join([f"{data['x']},{data['y']},{data['type']}"
                     for id, data in items_dict.items()])


async def divide_map():
    if not servers:
        return

    total_weight = 0
    weights = []

    for s in servers:
        cpu = max(s.cpu, 1)
        w = 1 / cpu
        weights.append(w)
        total_weight += w

    current_x = 0

    for i, s in enumerate(servers):
        portion = weights[i] / total_weight
        width = int(WIDTH * portion)

        new_min = current_x
        new_max = current_x + width if i < len(servers)-1 else WIDTH

        s.set_x_min(new_min)
        s.set_x_max(new_max)

        if i > 0:
            left_s = servers[i - 1]
            left_neighbor = f"{left_s.ip}:{left_s.port}"
        else:
            left_neighbor = "None"

        if i < len(servers) - 1:
            right_s = servers[i + 1]
            right_neighbor = f"{right_s.ip}:{right_s.port}"
        else:
            right_neighbor = "None"

        relevant_loot = {
            weapon_id: data
            for weapon_id, data in weapons_manager.state.map_weapons.items()
            if new_min <= data["x"] < new_max
        }

        relevant_potions = {
            potion_id: data
            for potion_id, data in potions_manager.state.map_potions.items()
            if new_min <= data["x"] < new_max
        }

        loot_str = serialize_items(relevant_loot)
        potions_str = serialize_items(relevant_potions)

        update_msg = f"UpdateStats|{new_min}|{new_max}|{left_neighbor}|{right_neighbor}|{loot_str}|{potions_str}\n"

        try:
            s.writer.write(update_msg.encode())
            await s.writer.drain()
        except Exception as e:
            print(f"[!] Failed to send update to GS-{s.id}: {e}")

        current_x = new_max


async def update_server_stats():
    global servers
    while True:
        await asyncio.sleep(5)

        # removing offline servers
        alive_servers = [s for s in servers if s.is_alive(HEARTBEAT_TIMEOUT)]

        if len(alive_servers) != len(servers):
            print(f"\n[!] Detected server drop! ({len(servers) - len(alive_servers)} servers disconnected)")
            servers = alive_servers
            await divide_map()

        print_current_map_state() # printing the current map division



def print_current_map_state():
    if not servers:
        print("[Status] No active servers.")
        return

    print("\n" + "=" * 60)
    print(f" CURRENT WORLD MAP DIVISION (Total Width: {WIDTH})")
    print("-" * 60)

    sorted_servers = sorted(servers, key=lambda s: s.get_x_min())

    for s in sorted_servers:
        start_pct = int((s.get_x_min() / WIDTH) * 20)
        end_pct = int((s.get_x_max() / WIDTH) * 20)
        bar = ["-"] * 20
        for i in range(start_pct, end_pct):
            if i < 20: bar[i] = "#"
        visual_bar = "".join(bar)

        print(
            f"GS-{s.id:02} | {s.ip}:{s.port} | "
            f"[{visual_bar}] | X: {s.get_x_min():<7} to {s.get_x_max():<7} | CPU: {s.get_cpu():>5.1f}%"
        )

    print("=" * 60 + "\n")


async def handle_gs_lifecycle(reader, writer):
    peer_ip, _ = writer.get_extra_info("peername")
    global next_server_id, servers
    current_gs = None

    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            data = line.decode().strip()
            parts = data.split("|")

            if parts[0] == "Server connect":
                gs_ip = parts[1]
                gs_cpu = float(parts[2])
                gs_port = int(parts[3])

                if gs_ip == "0.0.0.0":
                    gs_ip = peer_ip

                current_gs = server.game_server(next_server_id, gs_ip, gs_port, 0, WIDTH, writer)
                current_gs.set_cpu(gs_cpu)

                servers.append(current_gs)
                print(f"[+] GS-{current_gs.id} connected. Reported IP: {gs_ip}:{gs_port}")

                writer.write(f"Connected|{current_gs.id}\n".encode())
                await writer.drain()

                next_server_id += 1
                await divide_map()

            elif parts[0] == "CONNECT":
                if len(parts) >= 2:
                    print(f"[*] Forwarding CONNECT for Player {parts[1]}")
                    asyncio.create_task(forward_save_to_login(data))

            elif parts[0] == "DISCONNECT":
                if len(parts) >= 2:
                    print(f"[*] Forwarding DISCONNECT for Player {parts[1]}")
                    asyncio.create_task(forward_save_to_login(data))


            elif parts[0] == "SAVE":
                if len(parts) >= 6:
                    print(f"[*] Received save request for RealID: {parts[1]}")
                    save_msg = "|".join(parts)

                    asyncio.create_task(forward_save_to_login(save_msg))
                else:
                    print("[!] GS sent malformed SAVE message")


            elif parts[0] == "Server heartbeat":
                gs_id = int(parts[1])
                cpu_load = float(parts[2])

                target_server = None
                for s in servers:
                    if s.id == gs_id:
                        target_server = s
                        break

                if target_server:
                    old_cpu = target_server.cpu
                    target_server.cpu = cpu_load
                    target_server.last_seen = time.time()

                    for cmd_part in parts[3:]:
                        if not cmd_part or ":" not in cmd_part:
                            continue

                        cmd_type, data = cmd_part.split(":", 1)

                        if cmd_type == "add":
                            x, y, item_kind = data.split(",")
                            x, y = int(x), int(y)
                            new_id = int(time.time() * 1000)

                            if "potion" in item_kind.lower() or "poison" in item_kind.lower():
                                potions_manager.state.map_potions[new_id] = {"x": x, "y": y, "type": item_kind}
                            else:
                                weapons_manager.state.map_weapons[new_id] = {"x": x, "y": y, "type": item_kind}

                        elif cmd_type == "remove":
                            # פורמט: remove:x,y,item_type
                            x, y, item_kind = data.split(",")
                            x, y = int(x), int(y)

                            # חיפוש ומחיקה מהמנהל המתאים
                            if "potion" in item_kind.lower() or "poison" in item_kind.lower():
                                to_delete = [id for id, d in potions_manager.state.map_potions.items()
                                             if d["x"] == x and d["y"] == y]
                                for id_del in to_delete: del potions_manager.state.map_potions[id_del]
                            else:
                                to_delete = [id for id, d in weapons_manager.state.map_weapons.items()
                                             if d["x"] == x and d["y"] == y]
                                for id_del in to_delete: del weapons_manager.state.map_weapons[id_del]


                        elif cmd_type == "chat":
                            if "," in data:
                                msg, sender = data.split(",", 1)
                                chat_broadcast = f"ChatBroadcast|{sender}|{msg}\n"
                                print(f"[*] Global Chat from {sender}: {msg}")

                                for s in servers:
                                    if s != target_server:
                                        try:
                                            s.writer.write(chat_broadcast.encode())
                                            asyncio.create_task(s.writer.drain())
                                        except Exception as e:
                                            print(f"[!] Failed to broadcast chat to GS-{s.id}: {e}")

                    # אם ה-CPU השתנה משמעותית -> מחלקים מחדש
                    if abs(old_cpu - cpu_load) > 100: #or len(parts) > 3 אם יש שינויים בדברים
                        await divide_map()

            elif parts[0] == "RegisterPlayer":
                if len(parts) < 9:
                    writer.write(b"Error|Invalid Format (Missing Potions)\n")
                    await writer.drain()
                    continue

                real_id, fake_id, p_name, px, py, php, pinv, ppotions = parts[1:9]
                px_int = int(float(px))

                target_gs = None
                for s in servers:
                    if s.get_x_min() <= px_int < s.get_x_max():
                        target_gs = s
                        break

                if target_gs:
                    expect_msg = f"ExpectPlayer|{real_id}|{fake_id}|{p_name}|{px}|{py}|{php}|{pinv}|{ppotions}\n"
                    try:
                        target_gs.writer.write(expect_msg.encode())
                        await target_gs.writer.drain()

                        response = f"BestServer|{target_gs.id}|{target_gs.ip}|{target_gs.port}\n"
                    except Exception as e:
                        print(f"[!] Failed to notify GS-{target_gs.id}: {e}")
                        response = "Error|GS Communication Failed\n"
                else:
                    response = "Error|No Server Available for this position\n"

                writer.write(response.encode())
                await writer.drain()


            elif parts[0] == "GetServer":
                px = int(parts[1])

                target_server = None
                for s in servers:
                    if s.get_x_min() <= px <= s.get_x_max():
                        target_server = s
                        break

                if target_server:
                    response = f"BestServer|{target_server.ip}|{target_server.port}\n"
                else:
                    response = "Error|No Server Available\n"

                writer.write(response.encode())
                await writer.drain()
                break

    except Exception as e:
        print(f"[!] Error in GS lifecycle: {e}")
    finally:
        if current_gs and current_gs in servers:
            print(f"[-] GS-{current_gs.id} disconnected.")
            servers.remove(current_gs)
            await divide_map()
        writer.close()
        await writer.wait_closed()


def load_map(map_name):
    with open(map_name, "r") as f:
        lines = f.readlines()
    return [list(line.strip()) for line in lines]


async def main():
    print("[*] Loading map file...")
    try:
        game_map = load_map(MAP_NAME)
    except FileNotFoundError:
        print(f"[!] Critical: {MAP_NAME} not found!")
        return

    if game_map:
        print(f"[*] Map loaded. Size: {len(game_map[0])}x{len(game_map)} tiles.")

        weapons_manager.spawn_loot_per_camera_zone(game_map, per_zone=2)
        potions_manager.spawn_potions_per_camera_zone(game_map, per_zone=2)

        print(f"[*] World populated: {len(weapons_manager.state.map_weapons)} weapons, "
              f"{len(potions_manager.state.map_potions)} potions.")


    server = await asyncio.start_server(handle_gs_lifecycle, LB_IP, LB_PORT)
    print(f"[*] Load Balancer running on {LB_IP}:{LB_PORT}")

    asyncio.create_task(update_server_stats())

    async with server:
        await server.serve_forever()

# spawn_random_monsters(MONSTERS_AMOUNT)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] LB shutting down.")