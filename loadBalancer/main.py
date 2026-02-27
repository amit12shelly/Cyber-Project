import asyncio
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
    if message_split[0] == "Server connect":
        server_ip = message_split[1]
        server_cpu = message_split[2]
        port = message_split[3]
        servers.append = game_server(len(servers) - 1, server_ip , port, server_cpu, {"t-l":[0,0], "b-r":[100,100]})
        writer.write("Connected|{}".format(len(servers) -1))
        await writer.drain()
        divide_map()

def divide_map():
    num_of_servers = len(servers)
    offset_x = 0
    offset_y = 0
    overlap_width = 10
    for server in servers:
        server.get_area()["t-l"] = [offset_x, offset_y]
        server.get_area()["b-r"] = [offset_x + (width + overlap_width * num_of_servers) // num_of_servers, 100]
        print(server)
        offset_x += width // num_of_servers - overlap_width

async def handle_connection(reader, writer):
    data = await reader.read(1024)
    message = data.decode().strip()
    if message.startswith(b"Server connect"):
        await handle_server_connection(writer, message)
    elif message.startswith(b"Client connect"):
        await handle_server_connection(writer, message)
    elif message.startswith(b"Client out of area"):
        await handle_client_area(writer, message)

async def handle_client_area(writer, message):
    message_split = message.split("|")
    s_id = message_split[0]
    s_x = int(message_split[1])
    s_y = int(message_split[2])
    for server in servers:
        if s_x <= server.get_area()["t-l"][0] and s_x >= server.get_area()["b-r"][0] and server.get_id:



async def handle_client(writer, message):
    """Triggered whenever a new player tries to log in."""
    # 1. Logic to find the lowest CPU server
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
    # for server in servers:
    #     if x >= server.get_area()["t-l"][0] and x <= server.get_area()["b-r"][0] and :
    #         selected_ip = server.get_ip()
    #         selected_port = server.get_port()
    #         break

    response = f"Connect to:{selected_ip}:{selected_port}\n"

    print("Sending the client :{SERVER_IP}:{SERVER_PORT}".format(SERVER_IP=selected_ip, SERVER_PORT=selected_port))
    writer.write(response.encode())
    await writer.drain()
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