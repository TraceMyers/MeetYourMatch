from constants import *
from struct import pack, unpack
from time import time


class ConnectionLog:

    def __init__(self, max_poll_rate, turnover_time):
        self.ip_log = {}
        self.turnover_time = turnover_time
        self.max_poll_rate = max_poll_rate
        self.ban_list = []

    def get_client(self, ip_address):
        if ip_address in self.ip_to_client:
            return self.ip_to_client[ip_address]
        return None

    def log_ip(self, ip_address, remote_status):
        """log and refuse connections"""
        cur_time = time()
        if ip_address in self.ban_list:
            return SV_ERROR_IP_BANNED
        elif ip_address in self.ip_log:
            prev_time = self.ip_log[ip_address][0]
            self.ip_log[ip_address][0] = cur_time
            if cur_time - prev_time < self.max_poll_rate:
                self.ip_log[ip_address][1] += 1
                if self.ip_log[ip_address][1] > 3:
                    addr = ip_address[0]
                    self.ban_list.append(addr)
                return SV_ERROR_FAST_POLL_RATE
            else:
                self.ip_log[ip_address][1] = 0
        elif len(self.ip_log.keys()) >= SES_MAX:
            return SV_ERROR_IP_LOG_MAXED
        else:
            self.ip_log[ip_address] = [0, 0]
        self.ip_log[ip_address][0] = cur_time
        return 0

    def turnover(self):
        """drop stale connections"""
        turnover_time = self.turnover_time
        ip_log = self.ip_log

        dropped_ips = []
        for key, value in ip_log.items():
            entry_delta_time = time() - value
            if entry_delta_time > turnover_time:
                dropped_ips.append(key)
        for ip in dropped_ips:
            del ip_log[ip]
        return dropped_ips

    def forget_client(self, ip_address):
        del self.ip_log[ip_address]


class PacketData:

    __slots__ = (
        'status', 'flags', 'time_stamp', 'name', 'admin_key', 'client_data'
    )
    def __init__(self):
        self.status = STATUS_NONE               # 4
        self.flags = 0                          # 4
        self.time_stamp = 0                     # 8
        self.name = 'JoeSevere\0\0\0\0\0\0\0'   # 16
        self.admin_key = None                   # 16
        self.client_data = b''                  # 460 (udp) -> 508 total

    def unpacket_udp(self, data):
        self.status, self.flags, self.time_stamp, self.name, \
            self.admin_key, self.client_data = unpack('<2Id16s16s460s', data)
        self.name = self.name.decode()
        self.admin_key = self.admin_key.decode()
    
    def pack_udp(self):
        return pack(
            f'<2Id16s16s460s',
            self.status, self.flags, self.time_stamp, 
            bytes(self.name, 'utf-8'), GAP, self.client_data
        )


class Client:
    """
    Data piped from main process once sorted.
    """

    __slots__ = (
        'name', 'status', 'address', 'match_size', 'host_latencies', 'local_address'
    )
    def __init__(self, name, address, status, match_size=0, local_address=(None, None)):
        self.name = name
        self.status = status
        self.address = address
        self.match_size = match_size
        self.local_address = local_address

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f'{self.address[0]}:{self.address[1]} | {self.name} | {self.status:04X}'

    def set_client_ct(self, pdata):
        self.client_ct = pdata.client_data[0]
        return 1 <= self.client_ct <= MAX_CLIENT_CT

    def set_local_ip(self, pdata):
        try:
            data = unpack('4BH', pdata.client_data[1:7])
            self.local_address = ('.'.join([str(num) for num in data[:4]]), data[4])
        except:
            print("ERROR Client::set_local_ip() failed")
            pass

    def unpack_host_latency_info(self, pdata):
        try:
            client_data = pdata.client_data
            address_ct = client_data[0]
            for i in range(1, address_ct * 16 + 1, 16):
                data = unpack('4BHd', client_data[i:i+16])
                address_tup = ('.'.join([str(num) for num in data[0:4]]), data[4])
                self.host_latencies[address_tup] = data[5]
        except:
            print("ERROR Client::unpack_host_latency_info() failed")
            pass


class MatchingClient(Client):

    __slots__ = (
        'host_latencies', 'lat_status', 'lat_ctr', 'connect_ctr', 'session'
    )
    def __init__(self, client):
        super().__init__(
            client.name, 
            client.address, 
            client.status, 
            0, 
            client.client_ct, 
            client.local_address
        )
        self.host_latencies = {}
        self.lat_status = LAT_LOW
        self.lat_ctr = 0
        self.connect_ctr = 0
        self.session = None


class MatchingHost(Client):

    def __init__(self, client):
        super().__init__(
            client.name, 
            client.address, 
            client.status, 
            client.match_size, 
            client.client_ct, 
            client.local_address
        )
        self.session = None


class MatchingData:

    __slots__ = ('addresses', 'hosts', 'unmatched_clients', 'matched_clients', 'sessions')
    def __init__(self):
        self.addresses = []
        self.hosts = []
        self.unmatched_clients = []
        self.matched_clients = []
        self.sessions = []

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        clients = '\n'.join([str(client) for client in self.clients])
        sessions = '\n'.join([str(session) for session in self.sessions])
        return(
            '--------------------------\nGrouping Data:\n--------------------------\n'
            f'= Clients =\n\n{clients}\n\n= Sessions =\n\n{sessions}'
        )


class Session:

    def __init__(self, host, client_max=1):
        self.host = host
        self.known_name = None if host.status != STATUS_REG_HOST_KNOWNHOST else host.name
        self.clients = []
        self.client_max = client_max
        self.com = COM_STUN
        self.addresses = set([host.address]) # used after grouping
        self.locked = False
        self.timeout_ctr = 0

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        clients = '\n'.join([str(client) for client in self.clients])
        return(
            '=============|Session|=============\n'
            f'client ct = {len(self.clients)} | client max = {self.client_max}\n'
            '= Host =\n'
            f'{self.host}\n'
            f'= Clients =\n{clients}\n'
        )


class SessionData:

    def __init__(self):
        self.sessions = []


def buffer_incoming(sock, bufsiz, incoming, name):
    """
    buffer incoming registrations
    """
    while True:
        try:
            incoming.append(sock.recvfrom(bufsiz))
        except WindowsError: 
            # probably incoming package too big; ignore
            # TODO: get more details
            continue
        except Exception as e:
            print(f'ERROR {name}::buffer_incoming() passed exception from sock.recvfrom():')
            print(e)
            continue

