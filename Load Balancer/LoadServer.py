import asyncio
import psutil

# Shared state of your game servers
server_pool = {
    "server_1": {"ip": "192.168.1.10", "cpu": 60.2},
    "server_2": {"ip": "192.168.1.11", "cpu": 50.4},
    "server_3": {"ip": "192.168.1.13", "cpu": 95.8},
    "server_4": {"ip": "192.168.1.4", "cpu": 12.4},
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
    best_server = min(server_pool.values(), key=lambda s: s['cpu'])
    if best_server['cpu'] > 95.0:
        response = "Error: All servers are full. Try again later.\n"
    else:
        response = f"Connect to: {best_server['ip']}\n"
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