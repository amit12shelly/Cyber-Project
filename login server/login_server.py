import socket
import database
import asyncio

IP = "0.0.0.0"
PORT = 8820

LOAD_BALANCER_IP = "0.0.0.0"
LOAD_BALANCER_PORT = 8080

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    print("Client connected:", addr)

    try:
        data = await reader.read(1024)
        if not data:
            return

        message = data.decode().strip()
        print("Received:", message)

        if "?" not in message:
            writer.write(b"invalid format")
            await writer.drain()
            return

        command, args = message.split("?", 1)

        # ---------- REGISTER ----------
        if command == "reg":
            params = dict(x.split("=") for x in args.split("&"))
            username = params.get("u")
            password = params.get("p")

            if not username or not password:
                reply = "missing fields"
            else:
                success = database.register(username, password)
                reply = "ok" if success else "username exists"

        # ---------- LOGIN ----------
        elif command == "sign-in":
            params = dict(x.split("=") for x in args.split("&"))
            username = params.get("u")
            password = params.get("p")

            if not username or not password:
                reply = "missing fields"
            else:
                player_id = database.login(username, password)
                reply = "fail" if player_id is None else "ok id=" + str(player_id)

        else:
            reply = "unknown command"

        writer.write(reply.encode())
        await writer.drain()

    except Exception as e:
        print("Error:", e)
        writer.write(b"server error")
        await writer.drain()

    finally:
        writer.close()
        await writer.wait_closed()
        print("Client disconnected:", addr)


async def main():
    database.init_db()

    server = await asyncio.start_server(handle_client, IP, PORT)
    print("Async Login Server running on port", PORT)

    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())