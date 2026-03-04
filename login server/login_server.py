import asyncio
import ssl
import json
import database


IP = "127.0.0.1"
PORT = 8820

LOAD_BALANCER_IP = "127.0.0.1"
LOAD_BALANCER_PORT = 8080


async def get_game_server_from_lb(x, y):
    """
    מתחבר ל-Load Balancer, שולח קואורדינטות ומקבל פרטי שרת משחק.
    """
    try:
        reader, writer = await asyncio.open_connection(LOAD_BALANCER_IP, LOAD_BALANCER_PORT)

        request = json.dumps({"x": x, "y": y})
        writer.write(request.encode())
        await writer.drain()

        data = await reader.read(1024)
        writer.close()
        await writer.wait_closed()

        if data:
            return json.loads(data.decode())
        return None

    except Exception as e:
        print(f"[!] Failed to connect to Load Balancer: {e}")
        return None


def get_ssl_context():
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    try:
        context.load_cert_chain(certfile="server.crt", keyfile="server.key")
        return context
    except FileNotFoundError:
        print("Error: SSL Certificates (server.crt/key) not found!")
        return None


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    print(f"[*] Secure connection from {addr}")

    try:
        data = await reader.read(1024)
        if not data:
            return

        message = data.decode().strip()
        print(f"[>] Received: {message}")

        # 1. טיפול בבדיקת חיבור (הלקוח שולח את זה כשלוחצים Enter במסך ה-IP)
        if message == "CHECK_CONNECTION":
            reply = "OK"

        # 2. טיפול בבקשות LOGIN או REGISTER (פורמט הלקוח: TYPE:USER:PASS)
        elif ":" in message:
            parts = message.split(":")
            if len(parts) == 3:
                request_type, username, password = parts

                if request_type == "REGISTER":
                    success = database.register(username, password)
                    reply = json.dumps({"status": "success", "message": "Registration Success"}) if success \
                        else json.dumps({"status": "error", "message": "Username Exists"})

                elif request_type == "LOGIN":
                    player_id = database.login(username, password)

                    if player_id is not None:
                        # 1. טעינת נתוני מיקום
                        player_data = database.load_player(player_id)
                        x, y = player_data['x'], player_data['y']

                        # 2. פנייה ל-Load Balancer
                        print(f"[?] Querying LB for player {username} at ({x}, {y})...")
                        game_server_info = await get_game_server_from_lb(x, y)

                        if game_server_info:
                            # 3. תשובת הצלחה מלאה
                            reply = json.dumps({
                                "status": "success",
                                "player_id": player_id,
                                "server_ip": game_server_info["ip"],
                                "server_port": game_server_info["port"],
                                "zone": game_server_info.get("zone", "Unknown")
                            })
                        else:
                            reply = json.dumps({"status": "error", "message": "Load Balancer Unavailable"})
                    else:
                        reply = json.dumps({"status": "error", "message": "Login Failed"})

                else:
                    reply = json.dumps({"status": "error", "message": "Unknown Request"})
            else:
                reply = json.dumps({"status": "error", "message": "Invalid Format"})

        # שליחת התשובה
        writer.write(reply.encode())
        await writer.drain()
        print(f"[<] Sent to {addr}: {reply}")

    except Exception as e:
        print(f"[!] Error handling {addr}: {e}")
        try:
            writer.write(b"Server Error")
            await writer.drain()
        except:
            pass
    finally:
        writer.close()
        await writer.wait_closed()
        print(f"[*] Connection closed: {addr}")


async def main():
    database.init_db()

    ssl_context = get_ssl_context()
    if not ssl_context:
        return

    server = await asyncio.start_server(
        handle_client, IP, PORT, ssl=ssl_context
    )

    print(f"--- Secure Login Server running on {IP}:{PORT} ---")

    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())