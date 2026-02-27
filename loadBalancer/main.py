import asyncio

servers = [{"ip": "127.0.0.1", "cpu": 12.4, "port": 4433, "area": {"t-l": [0,22], "b-r": [8,100]}}, {"ip": "127.0.0.1", "cpu": 12.4, "port": 8000, "area": {"t-l": [0,22], "b-r": [8,100]}}]

width, height = 100, 100


async def update_server_stats():
    """Background task to simulate receiving CPU updates."""
    while True:
        # For now, we'll just simulate it
        await asyncio.sleep(2)
        print(f"Current Server Stats: {servers}")


async def handle_server_connection(reader, writer):
    data = await reader.read(1024)
    message = data.decode().strip()
    message_split = message.split("|")
    if message_split[0] == "Connect":
        server_ip = message_split[1]
        server_cpu = message_split[2]
        port = message_split[3]
        servers.append = {"ip": server_ip ,"cpu": server_cpu, "port": port}
        divide_map()


def divide_map():
    num_of_servers = len(servers)
    offset_x = 0
    offset_y = 0
    for server in servers:
        server["area"]["t-l"] = [offset_x, offset_y]
        server["area"]["b-r"] = [offset_x + width // num_of_servers, 100]
        print(server)
        offset_x += width // num_of_servers

async def handle_client(reader, writer):
    """Triggered whenever a new player tries to log in."""
    # 1. Logic to find the lowest CPU server
    data = await reader.read(1024)
    message = data.decode().strip()
    message_split = message.split("|")
    if message_split[0] != "Client connect": return
    if len(message_split) < 3:
        writer.write(b"Error: Send coordinates as x,y\n")
        await writer.drain()
        return

    x = int(message_split[1])
    y = int(message_split[2])
    print('Received coordinates:{X},{Y}'.format(X=x, Y=y))

    selected_ip = None
    selected_port = None
    for server in servers:
        if x >= server["area"]["t-l"][0] and x <= server["area"]["b-r"][0]:
            selected_ip = server["ip"]
            selected_port = server["port"]

    response = f"Connect to:{selected_ip}:{selected_port}\n"

    print("Sending the client :{SERVER_IP}:{SERVER_PORT}".format(SERVER_IP=selected_ip, SERVER_PORT=selected_port))
    writer.write(response.encode())
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def main():
    # Start the heartbeat listener
    asyncio.create_task(update_server_stats())
    server = await asyncio.start_server(handle_client, '0.0.0.0', 8080)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    divide_map()
    asyncio.run(main())