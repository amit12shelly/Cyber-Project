import asyncio
import json
import time
from server import game_server

WIDTH = 1920 * 64
LB_IP = "0.0.0.0"
LB_PORT = 8080
HEARTBEAT_TIMEOUT = 15


servers = []
next_server_id = 0

OVERLAP_SIZE = 500


async def divide_map():
    if not servers:
        return

    sorted_servers = sorted(servers, key=lambda s: s.get_x_min())

    total_weight = 0
    weights = []

    for s in servers:
        cpu = max(s.cpu, 1)
        w = 1 / cpu
        weights.append(w)
        total_weight += w

    current_x = 0

    for i, s in enumerate(sorted_servers):
        portion = weights[i] / total_weight
        width = int(WIDTH * portion)

        new_min = current_x
        new_max = current_x + width if i < len(servers)-1 else WIDTH

        neighbors = {}
        if i > 0:
            left = sorted_servers[i - 1]
            neighbors["left"] = {"id": left.id, "host": left.ip, "port": left.port}
        if i < len(sorted_servers) - 1:  # שכן מימין
            right = sorted_servers[i + 1]
            neighbors["right"] = {"id": right.id, "host": right.ip, "port": right.port}

        area_data = {
            "core": [new_min, new_max],
            "view": [max(0, new_min - OVERLAP_SIZE), min(WIDTH, new_max + OVERLAP_SIZE)],
            "neighbors": neighbors
        }

        s.x_min = new_min
        s.x_max = new_max

        update_msg = f"UpdateArea|{json.dumps(area_data)}\n"

        s.writer.write(update_msg.encode())
        await s.writer.drain()

        s.writer.write(update_msg.encode())
        await s.writer.drain()

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

                current_gs = game_server(next_server_id, gs_ip, gs_port, 0, WIDTH, writer)
                current_gs.set_cpu(gs_cpu)

                servers.append(current_gs)
                print(f"[+] GS-{current_gs.id} connected. Reported IP: {gs_ip}:{gs_port}")

                writer.write(f"Connected|{current_gs.id}\n".encode())
                await writer.drain()

                next_server_id += 1
                await divide_map()


            elif parts[0] == "Server heartbeat":
                gs_id = int(parts[1])
                cpu_load = float(parts[2])

                for s in servers:
                    if s.id == gs_id:
                        old_cpu = s.cpu
                        s.cpu = cpu_load
                        s.last_seen = time.time()

                        # אם ה-CPU השתנה משמעותית -> מחלקים מחדש
                        if abs(old_cpu - cpu_load) > 100:
                            await divide_map()
                        break

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


async def main():
    server = await asyncio.start_server(handle_gs_lifecycle, LB_IP, LB_PORT)
    print(f"[*] Load Balancer running on {LB_IP}:{LB_PORT}")

    asyncio.create_task(update_server_stats())

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] LB shutting down.")