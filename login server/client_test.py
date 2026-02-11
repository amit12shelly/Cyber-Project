import socket

def main():

    while True:
        my_socket = socket.socket()
        my_socket.connect(("127.0.0.1", 8820))

        command = input("\nSend 'register' to register and 'sign-in' to sign in\n")
        username = input("Username: ")
        password = input("password: ")

        if command == "register":
            info = "reg?u=" + str(username) + "&p=" + str(password)
            my_socket.send(info.encode())

            data = my_socket.recv(1024).decode()
            print("The server sent " + data)

        elif command == "sign-in":
            info = "sign-in?u=" + str(username) + "&p=" + str(password)
            my_socket.send(info.encode())

            data = my_socket.recv(1024).decode()
            print("The server sent " + data)

        else:
            continue


if __name__ == '__main__':
    main()