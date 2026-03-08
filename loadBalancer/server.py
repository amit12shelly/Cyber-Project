import time

class game_server:
    def __init__(self, id, ip, port, cpu, area):
        self.id = id
        self.ip = ip
        self.port = port
        self.cpu = cpu
        self.last_seen = time.time()  # חותמת זמן של הרגע בו השרת נוצר/עודכן

    def update_heartbeat(self, cpu=None):
        self.last_seen = time.time()
        if cpu is not None:
            self.cpu = float(cpu)

    def is_alive(self, timeout=30):
        # מחזיר True אם השרת יצר קשר ב-30 השניות האחרונות
        return (time.time() - self.last_seen) < timeout

    def __repr__(self):
        return "<Server {} | {}:{} | CPU: {}%>".format(self.id, self.ip, self.port, self.cpu)

    def get_id(self):
        return self.id
    def get_ip(self):
        return self.ip
    def get_port(self):
        return self.port
    def get_cpu(self):
        return self.cpu
    def get_area(self):
        return self.area

    def set_id(self, id):
        self.id = id
    def set_cpu(self, cpu):
        self.cpu = cpu
    def set_area(self, area):
       self.area = area
