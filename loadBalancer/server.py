class game_server:
    def __init__(self, id, ip, port, cpu, area):
        self.id = id
        self.ip = ip
        self.port = port
        self.cpu = cpu
        self.area = area

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
