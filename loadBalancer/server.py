import time

class game_server:
    def __init__(self, server_id, ip, port, x_min, x_max, writer):
        self.id = server_id
        self.ip = ip
        self.port = port
        self.x_min = x_min
        self.x_max = x_max
        self.cpu = 0.0
        self.writer = writer
        self.last_seen = time.time()


    def update_heartbeat(self, cpu=None):
        self.last_seen = time.time()
        if cpu is not None:
            self.cpu = float(cpu)

    def is_alive(self, timeout=10):
        # מחזיר True אם השרת יצר קשר ב-10 השניות האחרונות
        return (time.time() - self.last_seen) < timeout

    def __repr__(self):
        return f"<Server {self.id} | X-Range: [{self.x_min}-{self.x_max}] | CPU: {self.cpu}%>"

    def get_id(self):
        return self.id
    def get_ip(self):
        return self.ip
    def get_port(self):
        return self.port
    def get_cpu(self):
        return self.cpu
    def get_last_seen(self):
        return self.last_seen
    def get_x_min(self):
        return self.x_min
    def get_x_max(self):
        return self.x_max

    def set_id(self, id):
        self.id = id
    def set_cpu(self, cpu):
        self.cpu = cpu
    def set_x_min(self, x_min):
        self.x_min = x_min
    def set_x_max(self, x_max):
        self.x_max = x_max
