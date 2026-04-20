import pygame
import asyncio
import threading
import ssl
import json
import os

def load_config():
    filename = "config.json"
    default_config = {"login_server_ip": "127.0.0.1", "login_server_port": 8820}

    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
    return default_config


def login_client():
    config = load_config()

    pygame.init()
    width, height = 1920, 1080
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("MMORPG Client - Secure Connection")
    font = pygame.font.SysFont("Arial", 28, bold=True)
    clock = pygame.time.Clock()

    # --- משתני מצב ---
    # --- משתני מצב ---
    inputs = {
        "server ip": config["login_server_ip"],  # <--- טעינה אוטומטית כאן
        "username": "",
        "password": "",
        "confirm_password": ""
    }
    active_field = "username"
    status_msg = ""
    state = "CHOICE_MENU"
    running = True
    player_data = None
    login_done = False

    img = pygame.image.load("img/loading_screen.png")
    img = pygame.transform.scale(img, (1920, 1080))

    def start_network_thread(request_type):
        nonlocal status_msg, state, active_field, player_data, login_done

        async def network_logic():
            nonlocal status_msg, state, active_field, player_data, login_done
            try:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

                reader, writer = await asyncio.open_connection(
                    inputs["server ip"], int(8820), ssl=context
                )

                if request_type == "CHECK_CONNECTION":
                    writer.write(b"CHECK_CONNECTION")
                    await writer.drain()
                    data = await reader.read(1024)
                    if data.decode().strip() == "OK":
                        status_msg = "Connected! Choose an option."
                        state = "CHOICE_MENU"
                    writer.close()

                else:
                    message = f"{request_type}:{inputs['username']}:{inputs['password']}"
                    writer.write(message.encode())
                    await writer.drain()

                    # קריאת התשובה המפורטת מהשרת
                    raw_data = await reader.read(1024)
                    reply = raw_data.decode().strip()

                    # בדיקה אם ההתחברות הצליחה
                    if reply.startswith("LOGIN_SUCCESS"):
                        parts = reply.split("|")
                        player_data = {
                            "id": parts[1],
                            "username": parts[2],
                            "x": int(parts[3]),
                            "y": int(parts[4]),
                            "hp": int(parts[5]),
                            "inventory": parts[6],
                            "gs_ip": parts[7],
                            "gs_port": int(parts[8])
                        }
                        login_done = True

                        status_msg = f"Welcome {player_data['username']}!"
                        print(f"Loaded Player Data: {player_data}")

                    elif reply == "Registration Success":
                        status_msg = "Account Created! Please Login."
                        state = "CHOICE_MENU"
                    else:
                        status_msg = f"Server: {reply}"

                    writer.close()
                await writer.wait_closed()

            except Exception as e:
                if "refused" in str(e) or "Timeout" in str(e):
                    status_msg = f"Server is offline. Please try again later."
                else:
                    status_msg = f"Error: {e}"
                state = "SERVER_INFO"

        thread = threading.Thread(target=lambda: asyncio.run(network_logic()))
        thread.daemon = True
        thread.start()

    while running:
        if login_done:
            running = False  # שובר את הלופ של ה-UI וממשיך לסוף הפונקציה
            continue

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                player_data = None

            if event.type == pygame.KEYDOWN:
                # --- מקש ESC לניווט אחורה ---
                if event.key == pygame.K_ESCAPE:
                    if state in ["LOGIN_FORM", "REGISTER_FORM"]:
                        state = "CHOICE_MENU"
                        status_msg = "Select Action"
                    elif state == "CHOICE_MENU":
                        state = "SERVER_INFO"
                        active_field = "server ip"
                        status_msg = ""

                # --- קלט טקסט ---
                if state in ["SERVER_INFO", "LOGIN_FORM", "REGISTER_FORM"]:
                    if event.key == pygame.K_BACKSPACE:
                        inputs[active_field] = inputs[active_field][:-1]
                    elif event.key == pygame.K_TAB:
                        if state == "SERVER_INFO":
                            keys = ["server ip"]
                        elif state == "LOGIN_FORM":
                            keys = ["username", "password"]
                        else:
                            keys = ["username", "password", "confirm_password"]
                        idx = keys.index(active_field)
                        active_field = keys[(idx + 1) % len(keys)]
                    elif event.unicode.isprintable() and event.unicode != "":
                        inputs[active_field] += event.unicode

                # --- אישור (Enter) ---
                if event.key == pygame.K_RETURN:
                    if state == "SERVER_INFO" and inputs["server ip"]:
                        state = "CONNECTING"
                        start_network_thread("CHECK_CONNECTION")
                    elif state == "LOGIN_FORM" and inputs["username"] and inputs["password"]:
                        start_network_thread("LOGIN")
                    elif state == "REGISTER_FORM" and inputs["username"] and inputs["password"]:
                        if inputs["password"] == inputs["confirm_password"]:
                            start_network_thread("REGISTER")
                        else:
                            status_msg = "Error: Passwords do not match!"

                # --- בחירה בתפריט ---
                if state == "CHOICE_MENU":
                    if event.key == pygame.K_l:
                        state, active_field = "LOGIN_FORM", "username"
                        status_msg = "Enter credentials"
                    elif event.key == pygame.K_r:
                        state, active_field = "REGISTER_FORM", "username"
                        status_msg = "Create new account"

        # --- ציור ---
        screen.fill((0, 0, 0))
        screen.blit(img, (0, 0))

        center_x = width // 2

        if state == "CHOICE_MENU":
            l_text = font.render("[L] Login to existing account", True, (50, 150, 255))
            r_text = font.render("[R] Register new account", True, (50, 150, 255))
            screen.blit(l_text, l_text.get_rect(center=(center_x, 430)))
            screen.blit(r_text, r_text.get_rect(center=(center_x, 500)))

            status_color = (200, 0, 0) if "Error" in status_msg or "Failed" in status_msg else (0, 150, 0)
            status_surf = font.render(status_msg, True, status_color)
            screen.blit(status_surf, status_surf.get_rect(center=(center_x, 630)))


        elif state in ["SERVER_INFO", "CONNECTING"]:
            fields = ["server ip"]

            for i, key in enumerate(fields):
                color = (50, 150, 255) if active_field == key else (50, 50, 50)
                lbl = font.render(f"{key.upper()}:", True, (0, 0, 0))
                y_pos = 420 + i * 110
                screen.blit(lbl, lbl.get_rect(center=(center_x, y_pos)))

                rect = pygame.Rect(0, 0, 400, 45)
                rect.center = (center_x, y_pos + 45)
                pygame.draw.rect(screen, (220, 220, 220), rect, 0, border_radius=5)
                pygame.draw.rect(screen, color, rect, 2, border_radius=5)

                txt = "*" * len(inputs[key]) if "pass" in key else inputs[key]
                val_surf = font.render(txt, True, (0, 0, 0))
                screen.blit(val_surf, val_surf.get_rect(center=rect.center))

            status_color = (200, 0, 0) if "Error" in status_msg or "Failed" in status_msg else (0, 150, 0)
            status_surf = font.render(status_msg, True, status_color)
            screen.blit(status_surf, status_surf.get_rect(center=(center_x, 630)))


        elif state == "LOGIN_FORM":
            fields = ["username", "password"]

            for i, key in enumerate(fields):
                color = (50, 150, 255) if active_field == key else (50, 50, 50)
                lbl = font.render(f"{key.upper()}:", True, (0, 0, 0))
                y_pos = 420 + i * 110
                screen.blit(lbl, lbl.get_rect(center=(center_x, y_pos)))

                rect = pygame.Rect(0, 0, 400, 45)
                rect.center = (center_x, y_pos + 45)
                pygame.draw.rect(screen, (220, 220, 220), rect, 0, border_radius=5)
                pygame.draw.rect(screen, color, rect, 2, border_radius=5)

                txt = "*" * len(inputs[key]) if "pass" in key else inputs[key]
                val_surf = font.render(txt, True, (0, 0, 0))
                screen.blit(val_surf, val_surf.get_rect(center=rect.center))

            status_color = (200, 0, 0) if "Error" in status_msg or "Failed" in status_msg else (0, 150, 0)
            status_surf = font.render(status_msg, True, status_color)
            screen.blit(status_surf, status_surf.get_rect(center=(center_x, 660)))


        elif state == "REGISTER_FORM":
            fields = ["username", "password", "confirm_password"]

            for i, key in enumerate(fields):
                color = (50, 150, 255) if active_field == key else (50, 50, 50)
                lbl = font.render(f"{key.upper()}:", True, (0, 0, 0))
                y_pos = 350 + i * 110
                screen.blit(lbl, lbl.get_rect(center=(center_x, y_pos)))

                rect = pygame.Rect(0, 0, 400, 45)
                rect.center = (center_x, y_pos + 45)
                pygame.draw.rect(screen, (220, 220, 220), rect, 0, border_radius=5)
                pygame.draw.rect(screen, color, rect, 2, border_radius=5)

                txt = "*" * len(inputs[key]) if "pass" in key else inputs[key]
                val_surf = font.render(txt, True, (0, 0, 0))
                screen.blit(val_surf, val_surf.get_rect(center=rect.center))

            status_color = (200, 0, 0) if "Error" in status_msg or "Failed" in status_msg else (0, 150, 0)
            status_surf = font.render(status_msg, True, status_color)
            screen.blit(status_surf, status_surf.get_rect(center=(center_x, 680)))


        # הצגת הוראת חזרה (ESC) בפינה
        if state != "SERVER_INFO":
            back_hint = pygame.font.SysFont("Arial", 25).render("ESC: Back", True, (255, 255, 255), (0, 0, 0))
            screen.blit(back_hint, (20, 20))


        pygame.display.flip()
        clock.tick(30)
    pygame.quit()
    return player_data


if __name__ == "__main__":
    login_client()