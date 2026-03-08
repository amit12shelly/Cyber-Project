import asyncio
import ssl
import json
from server import game_server

servers = []
width, height = 100, 100





async def update_server_stats():
    """Background task to simulate receiving CPU updates."""
    while True:
        # For now, we'll just simulate it
        await asyncio.sleep(2)
        print(f"Current Server Stats: {servers}")





async def handle_server_connection(writer, message):
    message_split = message.split("|")
    server_ip = message_split[1]
    server_cpu = message_split[2]
    port = message_split[3]
    servers.append = game_server(len(servers) - 1, server_ip , port, server_cpu, {"t-l":[0,0], "b-r":[100,100]})
    writer.write("Connected|{}".format(len(servers) -1))
    await writer.drain()
    divide_map()





def divide_map():
    num_of_servers = len(servers)
    if num_of_servers == 0: return

    # Calculate weights based on CPU
    total_cpu = sum(server.get_cpu() for server in servers)
    weights = [server.get_cpu() / total_cpu for server in
               servers] if total_cpu > 0 else [1 / num_of_servers] * num_of_servers

    current_x = 0.0
    overlap = 10

    for i, server in enumerate(servers):
        start_x = int(round(current_x))
        current_x += width * weights[i]
        end_x = int(round(current_x))

        server.get_area()["t-l"] = [start_x, 0]

        if i == num_of_servers - 1:
            server.get_area()["b-r"] = [width, height]
        else:
            server.get_area()["b-r"] = [min(end_x + overlap, width), height]

    # for gs in servers:




async def handle_connection(reader, writer):
    data = await reader.read(1024)
    message = data.decode().strip()
    if message.startswith(b"Server connect"):
        await handle_server_connection(writer, message)
    elif message.startswith(b"Client connect"):
        await handle_login_request(writer, message)
    elif message.startswith(b"Client out of area"):
        await handle_client_area(writer, message)





async def handle_client_area(writer, message):
    message_split = message.split("|")
    s_id = message_split[0]
    s_x = int(message_split[1])
    s_y = int(message_split[2])
    c_id = message_split[3]
    for server in servers:
      if s_x <= server.get_area()["t-l"][0] and s_x >= server.get_area()["b-r"][0] and server.get_id != s_id:
          writer.write("Connect client {} to server {}".format(c_id, server.get_id))
          await writer.drain()






async def handle_login_request(writer, message):
    """
        מטפל בבקשת התחברות מה-Login Server.
        מפענח את המיקום (x, y) ומחזיר את השרת המתאים.
        """
    try:
        data = json.loads(message)
        x = data.get("x")
        y = data.get("y")

        selected_server = None

        # 2. חיפוש השרת שהשטח שלו מכסה את ה-x של השחקן
        for server in servers:
            area = server.get_area()
            # בדיקה אם ה-x נמצא בתוך הגבולות של השרת
            if area["t-l"][0] <= x <= area["b-r"][0]:
                selected_server = server
                break

        if selected_server:
            response = {
                "ip": selected_server.get_ip(),
                "port": selected_server.get_port(),
                "zone": f"Server-{selected_server.get_id()}"
            }
            print(
                f"[<] LB: Routing to Server {selected_server.get_id()} ({selected_server.get_ip()}:{selected_server.get_port()})")
        else:
            # מקרה קצה - אם המפה לא מחוסה (לא אמור לקרות אם divide_map עובדת)
            response = {"error": "No server available for this location"}

        # 4. שליחת התשובה בחזרה ל-Login Server
        writer.write(json.dumps(response).encode())
        await writer.drain()

    except Exception as e:
        print(f"[!] LB Error in handle_login_request: {e}")
    finally:
        writer.close()
        await writer.wait_closed()







async def main():
    # Start the heartbeat listener
    asyncio.create_task(update_server_stats())
    server = await asyncio.start_server(handle_connection(), '0.0.0.0', 8080)
    async with server:
        await server.serve_forever()



if __name__ == "__main__":
    divide_map()
    asyncio.run(main())