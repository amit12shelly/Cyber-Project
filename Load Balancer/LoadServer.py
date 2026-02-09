import asyncio

# Shared state of your game servers
server_pool = {
    "server_1": {"ip": "10.12.9.177", "cpu": 60.2,"port": 4433},
    "server_2": {"ip": "10.12.9.177", "cpu": 50.4,"port": 4433},
    "server_3": {"ip": "10.12.9.177", "cpu": 95.8,"port": 4433},
    "server_4": {"ip": "10.12.9.177", "cpu": 12.4,"port": 4433},
}

async def update_server_stats():
    """Background task to simulate receiving CPU updates."""
    while True:
        # For now, we'll just simulate it
        await asyncio.sleep(2)
        print(f"Current Server Stats: {server_pool}")

async def handle_client(reader, writer):
    """Triggered whenever a new player tries to log in."""
    # 1. Logic to find the lowest CPU server
    data = await reader.read(1024)
    message = data.decode().strip()
    message_split = message.split(",")

    if len(message_split) < 2:
        writer.write(b"Error: Send coordinates as x,y\n")
        await writer.drain()
        return

    x = int(message_split[0])
    y = int(message_split[1])
    print('Received coordinates:{X},{Y}'.format(X=x, Y=y))

    if x < 50 and x >= 0:
        if y < 50 and y >= 0:
            selected_ip = server_pool["server_1"]["ip"]
            selected_port = server_pool["server_1"]["port"]
        else:
            selected_ip = server_pool["server_4"]["ip"]
            selected_port = server_pool["server_4"]["port"]
    elif x > 50 and x <=100:
        if y < 50 and y >= 0:
            selected_ip = server_pool["server_2"]["ip"]
            selected_port = server_pool["server_2"]["port"]
        else:
            selected_ip = server_pool["server_3"]["ip"]
            selected_port = server_pool["server_3"]["port"]
    # best_server = min(server_pool.values(), key=lambda s: s['cpu'])
    # if best_server['cpu'] > 95.0:
    #     response = "Error: All servers are full. Try again later.\n"
    # else:
    response = f"Connect to:{selected_ip}:{selected_port}\n"
    print("Sending the client :{SERVER_IP}:{SERVER_PORT}".format(SERVER_IP =selected_ip,SERVER_PORT = selected_port))
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
    asyncio.run(main())