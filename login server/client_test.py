import pygame
import asyncio
import threading
import ssl
import time


def run_game_client():
    pygame.init()
    width, height = 800, 600
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("MMORPG Client - Secure Connection")
    font = pygame.font.SysFont("Arial", 28, bold=True)
    clock = pygame.time.Clock()

    # --- משתני מצב ---
    # --- משתני מצב ---
    inputs = {
        "ip": "",
        "port": "",
        "user": "",
        "pass": "",
        "confirm_pass": ""
    }
    active_field = "ip"
    status_msg = "Enter Server IP & Port"
    state = "SERVER_INFO"
    running = True

    def start_network_thread(request_type):
        nonlocal status_msg, state, active_field

        async def network_logic():
            nonlocal status_msg, state, active_field
            try:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

                reader, writer = await asyncio.open_connection(
                    inputs["ip"], int(inputs["port"]), ssl=context
                )

                if request_type == "CHECK_CONNECTION":
                    writer.write(b"CHECK_CONNECTION")
                    await writer.drain()
                    data = await reader.read(100)
                    if data.decode().strip() == "OK":
                        status_msg = "Connected! Choose an option."
                        state = "CHOICE_MENU"
                    writer.close()
                else:
                    message = f"{request_type}:{inputs['user']}:{inputs['pass']}"
                    writer.write(message.encode())
                    await writer.drain()

                    raw_data = await reader.read(100)
                    reply = raw_data.decode().strip()
                    status_msg = f"Server: {reply}"

                    if "Success" in reply:
                        time.sleep(1.0)
                        state = "CHOICE_MENU"
                        inputs["pass"], inputs["confirm_pass"] = "", ""

                    writer.close()
                await writer.wait_closed()
            except Exception:
                status_msg = "Error: Connection Failed!"
                state = "SERVER_INFO"

        thread = threading.Thread(target=lambda: asyncio.run(network_logic()))
        thread.daemon = True
        thread.start()

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                # --- מקש ESC לניווט אחורה ---
                if event.key == pygame.K_ESCAPE:
                    if state in ["LOGIN_FORM", "REGISTER_FORM"]:
                        state = "CHOICE_MENU"
                        status_msg = "Select Action"
                    elif state == "CHOICE_MENU":
                        state = "SERVER_INFO"
                        active_field = "ip"
                        status_msg = "Enter Server IP & Port"

                # --- קלט טקסט ---
                if state in ["SERVER_INFO", "LOGIN_FORM", "REGISTER_FORM"]:
                    if event.key == pygame.K_BACKSPACE:
                        inputs[active_field] = inputs[active_field][:-1]
                    elif event.key == pygame.K_TAB:
                        if state == "SERVER_INFO":
                            keys = ["ip", "port"]
                        elif state == "LOGIN_FORM":
                            keys = ["user", "pass"]
                        else:
                            keys = ["user", "pass", "confirm_pass"]
                        idx = keys.index(active_field)
                        active_field = keys[(idx + 1) % len(keys)]
                    elif event.unicode.isprintable() and event.unicode != "":
                        inputs[active_field] += event.unicode

                # --- אישור (Enter) ---
                if event.key == pygame.K_RETURN:
                    if state == "SERVER_INFO" and inputs["ip"] and inputs["port"]:
                        state = "CONNECTING"
                        start_network_thread("CHECK_CONNECTION")
                    elif state == "LOGIN_FORM" and inputs["user"] and inputs["pass"]:
                        start_network_thread("LOGIN")
                    elif state == "REGISTER_FORM" and inputs["user"] and inputs["pass"]:
                        if inputs["pass"] == inputs["confirm_pass"]:
                            start_network_thread("REGISTER")
                        else:
                            status_msg = "Error: Passwords do not match!"

                # --- בחירה בתפריט ---
                if state == "CHOICE_MENU":
                    if event.key == pygame.K_l:
                        state, active_field = "LOGIN_FORM", "user"
                        status_msg = "Enter credentials"
                    elif event.key == pygame.K_r:
                        state, active_field = "REGISTER_FORM", "user"
                        status_msg = "Create new account"

        # --- ציור ---
        screen.fill((240, 240, 240))
        center_x = width // 2

        if state == "CHOICE_MENU":
            label = font.render("MAIN MENU", True, (0, 0, 0))
            screen.blit(label, label.get_rect(center=(center_x, 150)))
            l_text = font.render("[L] Login to existing account", True, (50, 150, 255))
            r_text = font.render("[R] Register new account", True, (50, 150, 255))
            screen.blit(l_text, l_text.get_rect(center=(center_x, 280)))
            screen.blit(r_text, r_text.get_rect(center=(center_x, 350)))

        elif state in ["SERVER_INFO", "LOGIN_FORM", "REGISTER_FORM", "CONNECTING"]:
            if state in ["SERVER_INFO", "CONNECTING"]:
                fields = ["ip", "port"]
            elif state == "LOGIN_FORM":
                fields = ["user", "pass"]
            else:
                fields = ["user", "pass", "confirm_pass"]

            title = state.replace("_", " ")
            title_surf = font.render(title, True, (0, 0, 0))
            screen.blit(title_surf, title_surf.get_rect(center=(center_x, 60)))

            for i, key in enumerate(fields):
                color = (50, 150, 255) if active_field == key else (50, 50, 50)
                lbl = font.render(f"{key.upper()}:", True, (0, 0, 0))
                y_pos = 140 + i * 110
                screen.blit(lbl, lbl.get_rect(center=(center_x, y_pos)))

                rect = pygame.Rect(0, 0, 400, 45)
                rect.center = (center_x, y_pos + 45)
                pygame.draw.rect(screen, (220, 220, 220), rect, 0, border_radius=5)
                pygame.draw.rect(screen, color, rect, 2, border_radius=5)

                txt = "*" * len(inputs[key]) if "pass" in key else inputs[key]
                val_surf = font.render(txt, True, (0, 0, 0))
                screen.blit(val_surf, val_surf.get_rect(center=rect.center))

        # הצגת הוראת חזרה (ESC) בפינה
        if state != "SERVER_INFO":
            back_hint = pygame.font.SysFont("Arial", 18).render("ESC: Back", True, (100, 100, 100))
            screen.blit(back_hint, (20, 20))

        # סטטוס
        status_color = (200, 0, 0) if "Error" in status_msg or "Failed" in status_msg else (0, 150, 0)
        status_surf = font.render(status_msg, True, status_color)
        screen.blit(status_surf, status_surf.get_rect(center=(center_x, 540)))

        pygame.display.flip()
        clock.tick(30)
    pygame.quit()


if __name__ == "__main__":
    run_game_client()