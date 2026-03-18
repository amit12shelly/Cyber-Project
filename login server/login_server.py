import asyncio
import ssl
import database
import secrets

IP = "0.0.0.0"
PORT = 8820

LB_IP = "127.0.0.1"
LB_PORT = 8080


async def register_player_on_lb(real_id, fake_id, username, x, y, hp, inv_str):
    try:
        reader, writer = await asyncio.open_connection(LB_IP, LB_PORT)

        query = f"RegisterPlayer|{real_id}|{fake_id}|{username}|{x}|{y}|{hp}|{inv_str}\n"
        writer.write(query.encode())
        await writer.drain()

        line = await reader.readline()
        writer.close()
        await writer.wait_closed()

        msg = line.decode().strip()
        if msg.startswith("BestServer|"):
            # ה-LB מחזיר עכשיו: BestServer|gs_id|gs_ip|gs_port
            parts = msg.split("|")
            if len(parts) >= 4:
                return parts[2], parts[3]
        return None, None
    except Exception as e:
        print(f"[!] Error querying LB: {e}")
        return None, None


def serialize_inventory(inventory):
    """הופך את המילון למחרוזת בפורמט: slot,type,ammo;slot,type,ammo"""
    items = []
    for slot, data in inventory.items():
        items.append(f"{slot},{data['type']},{data['ammo']}")
    return ";".join(items) if items else "Empty"


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
    reply = ""

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
                    reply = "Registration Success" if success else "Username Exists"

                elif request_type == "LOGIN":
                    real_id = database.login(username, password)
                    if real_id is not None:
                        player_data = database.load_player(real_id)
                        inv_str = serialize_inventory(player_data['inventory'])
                        fake_id = secrets.token_hex(16)

                        gs_ip, gs_port = await register_player_on_lb(
                            real_id, fake_id, player_data['username'],
                            player_data['x'], player_data['y'], player_data['hp'], inv_str
                        )

                        if gs_ip and gs_port:
                            if gs_ip and gs_port:
                                reply = (
                                    f"LOGIN_SUCCESS|{fake_id}|"
                                    f"{player_data['username']}|{player_data['x']}|"
                                    f"{player_data['y']}|{player_data['hp']}|"
                                    f"{inv_str}|"
                                    f"{gs_ip}|{gs_port}"
                                )
                        else:
                            reply = "Login Failed: No Game Server available"


                    else:
                        reply = "Login Failed"

                else:
                    reply = "Error: Unknown Request"
            else:
                reply = "Error: Invalid Format"
        else:
            reply = "Error: Protocol Mismatch"

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

    server = await asyncio.start_server(handle_client, IP, PORT, ssl=ssl_context)

    print(f"--- Secure Login Server running on {IP}:{PORT} ---")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Server stopped by user.")