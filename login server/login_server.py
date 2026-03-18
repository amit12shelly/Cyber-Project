import asyncio
import ssl
import database
import secrets

IP = "0.0.0.0"
PORT = 8820
INTERNAL_PORT = 8821


LB_IP = "127.0.0.1"
LB_PORT = 8080


def parse_inventory_to_dict(inv_str):
    inventory = {}
    # בדיקה אם המחרוזת ריקה או "none"
    if not inv_str or inv_str in ["Empty", "none", ""]:
        return inventory

    try:
        items = inv_str.split(";")

        for slot_id, item_data in enumerate(items):
            if "," in item_data:
                # פיצול לסוג וכמות
                parts = item_data.split(",")
                if len(parts) == 2:
                    item_type, ammo = parts

                    # דילוג על סלוטים ריקים
                    if item_type == "none":
                        continue

                    inventory[slot_id] = {
                        "type": item_type,
                        "ammo": int(ammo)
                    }
    except Exception as e:
        print(f"[!] Error parsing inventory string: {e}")

    return inventory


async def handle_internal_lb(reader, writer):
    try:
        data = await reader.read(4096)
        if not data:
            return

        message = data.decode().strip()
        parts = message.split("|")

        if parts[0] == "SAVE" and len(parts) >= 6:
            real_id = parts[1]
            inventory_dict = parse_inventory_to_dict(parts[5])

            if len(parts) > 6:
                potions_str = parts[6]
                if potions_str and potions_str not in ("None", "Empty", ""):
                    potions_list = potions_str.split(",")
                    for i, p_type in enumerate(potions_list):
                        slot_id = 5 + i
                        if slot_id <= 10:  # מגבלה טכנית לסלוטים
                            inventory_dict[slot_id] = {
                                "type": p_type,
                                "ammo": 1  # לשיקוי בודד תמיד יש כמות 1
                            }

            state_to_save = {
                "player_id": real_id,
                "x": float(parts[2]),
                "y": float(parts[3]),
                "hp": int(parts[4]),
                "inventory": inventory_dict
            }

            try:
                database.save_player(state_to_save)
                print(f"[*] Successfully saved player {real_id} via LB request.")
            except Exception as e:
                print(f"[!] database.save_player failed: {e}")

    except Exception as e:
        print(f"[!] Error handling internal LB message: {e}")
    finally:
        writer.close()
        await writer.wait_closed()


async def register_player_on_lb(real_id, fake_id, username, x, y, hp, inv_str, potions_str):
    try:
        reader, writer = await asyncio.open_connection(LB_IP, LB_PORT)

        query = f"RegisterPlayer|{real_id}|{fake_id}|{username}|{x}|{y}|{hp}|{inv_str}|{potions_str}\n"
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
    if not inventory:
        return "Empty"

    parts = []
    for slot, data in inventory.items():
        parts.append(f"{slot},{data['type']},{data['ammo']}")

    return ";".join(parts) if parts else "Empty"


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

                        # הפרדה: נשקים (0-4) ושיקויים (5-10)
                        full_inventory = player_data['inventory']
                        weapons_only = {k: v for k, v in full_inventory.items() if k <= 4}
                        potions_only = [v['type'] for k, v in full_inventory.items() if k >= 5]

                        inv_str = serialize_inventory(weapons_only)
                        potions_str = ",".join(potions_only) if potions_only else "None"

                        fake_id = secrets.token_hex(16)

                        # שליחה ל-LB עם הפרמטר החדש
                        gs_ip, gs_port = await register_player_on_lb(
                            real_id, fake_id, player_data['username'],
                            player_data['x'], player_data['y'], player_data['hp'],
                            inv_str, potions_str  # <--- הוספת potions_str
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

    client_server = await asyncio.start_server(handle_client, IP, PORT, ssl=ssl_context)
    internal_lb_server = await asyncio.start_server(handle_internal_lb, IP, INTERNAL_PORT)

    print(f"--- Login Server Running ---")
    print(f"[*] External (SSL) on port {PORT}")
    print(f"[*] Internal (LB) on port {INTERNAL_PORT}")

    async with client_server, internal_lb_server:
        await asyncio.gather(
            client_server.serve_forever(),
            internal_lb_server.serve_forever()
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Server stopped by user.")