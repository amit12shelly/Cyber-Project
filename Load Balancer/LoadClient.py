import asyncio

async def connect_to_game():
    lb_host = '127.0.0.1'
    lb_port = 8080
    try:
        print(f"Connecting to Load Balancer at {lb_host}:{lb_port}...")

        # פתיחת חיבור ל-Load Balancer
        reader, writer = await asyncio.open_connection(lb_host, lb_port)
        # קריאת התגובה (ה-IP של שרת המשחק)
        data = await reader.read(100)
        message = data.decode().strip()

        print(f"Message from LB: {message}")

        if "Connect to: " in message:
            game_server_ip = message.replace("Connect to: ", "")
            print(f" Success! Redirecting player to actual game server: {game_server_ip}")
        else:
            print("Received unexpected response from LB.")

        writer.close()
        await writer.wait_closed()

    except ConnectionRefusedError:
        print("Error: Could not connect to Load Balancer. Make sure it's running!")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(connect_to_game())