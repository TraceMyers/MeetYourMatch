from constants import *
from struct import pack, unpack
from time import time
from threading import Lock


class ConnectionLog:

    def __init__(self, max_poll_rate, turnover_time, max_ips):
        self.ip_log = {}
        self.turnover_time = turnover_time
        self.max_poll_rate = max_poll_rate
        self.ban_list = []
        self.max_ips = max_ips

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
        elif len(self.ip_log.keys()) >= self.max_ips:
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
        self.status = CL_STATUS_NONE            # 4
        self.flags = 0                          # 4
        self.time_stamp = 0                     # 8
        self.name = 'JoeSevere\0\0\0\0\0\0\0'   # 16
        self.admin_key = None                   # 16
        self.client_data = b''                  # 460 (udp) -> 508 total

    def unpackit(self, data):
        self.status, self.flags, self.time_stamp, self.name, \
            self.admin_key, self.client_data = unpack('<2Id16s16s460s', data)
        self.name = self.name.decode()
        self.admin_key = self.admin_key.decode()
    
    def packit(self):
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
    def __init__(self, pdata, address):
        self.name = pdata.name
        self.status = pdata.status
        self.address = address
        self.match_size = 0
        self.set_local_ip(pdata)

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f'{self.address[0]}:{self.address[1]} | {self.name} | {self.status:04X}'

    def set_match_size(self, pdata):
        self.client_ct = pdata.client_data[0]
        return 1 <= self.client_ct <= MAX_MATCH_SIZE

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
        self.alive_ctr = MATCHMAKING_ALIVE_TIME
        self.in_match = False


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
        self.alive_ctr = MATCHMAKING_ALIVE_TIME
        self.in_match = False


# only auto-locking in str because it was found to be a potentially thread-unsafe thing to 
# rely on auto-locking for most things, since calls made in sequence can be divided by a 
# lock.acquire happening on another thread
class LockedMatchingData:

    def __init__(self, max_user_ct):
        self.address_to_record = {}
        self.sessions = []
        self.unmatched_clients = []
        self.lock = Lock()
        self.max_user_ct = max_user_ct

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        self.lock.acquire()
        clients = '\n'.join([str(client) for client in self.unmatched_clients])
        sessions = '\n'.join([str(session) for session in self.sessions])
        self.lock.release()
        return(
            '--------------------------\nGrouping Data:\n--------------------------\n'
            f'= Clients =\n\n{clients}\n\n= Sessions =\n\n{sessions}'
        )

    def add_unmatched_locked(self, client):
        if len(self.addresses_to_record.keys()) < self.max_user_ct:
            matching_client = MatchingClient(client)
            self.unmatched_clients.append(matching_client)
            self.address_to_record[matching_client.address] = matching_client
            return True
        return False
    
    def add_host_locked(self, client):
        if len(self.addresses_to_record.keys()) < self.max_user_ct:
            matching_host = MatchingHost(client)
            self.sessions.append(Session(matching_host))
            self.address_to_record[matching_host.address] = matching_host
            return True
        return False

    def record_exists_locked(self, address):
        return address in self.address_to_record.keys()

    def find_client_unmatched(self, address):
        for i in range(len(self.unmatched_clients)):
            uclient = self.unmatched_clients[i]
            if uclient.address == address:
                return i
        return -1

    def find_client_matched(self, address):
        for i in range(len(self.sessions)):
            s = self.sessions[i]
            for j in range(len(s.clients)):
                c = s.clients[j]
                if c.address == address:
                    return i, j
        return -1, -1

    def find_host(self, address):
        for i in range(len(self.sessions)):
            s = self.sessions[i]
            if address == s.host.address:
                return i
        return -1

    def drop(self, address):
        if address in self.address_to_record.keys():
            del self.address_to_record[address]
        for i in range(len(self.unmatched_clients)):
            uclient_address = self.unmatched_clients[i].address
            if uclient_address == address:
                self.unmatched_clients.pop(i)
                break
        found_client = False
        for i in range(len(self.sessions)):
            session = self.sessions[i]
            if address == session.host.address:
                for client in session.clients:
                    if len(self.unmatched_clients) < self.max_user_ct:
                        self.unmatched_clients.append(client)
                    else:
                        break
                self.sessions.pop(i)
                break
            else:
                for j in range(len(session.clients)):
                    client_address = session.clients[j].address
                    if client_address == address:
                        found_client = True
                        session.clients.pop(j)
                        session.addresses.remove(address)
                        break
                if found_client:
                    break

    def reset_alive_ctr_unmatched_client(self, index):
        self.unmatched_clients[index].alive_ctr = MATCHMAKING_ALIVE_TIME

    def reset_alive_ctr_matched_client(self, session_i, client_i):
        self.sessions[session_i].clients[client_i].alive_ctr = MATCHMAKING_ALIVE_TIME

    def reset_alive_ctr_host(self, session_i):
        self.sessions[session_i].host.alive_ctr = MATCHMAKING_ALIVE_TIME

    def set_client_in_match(self, session_i, client_i):
        self.sessions[session_i].clients[client_i].in_match = True

    def set_host_in_match(self, session_i):
        self.sessions[session_i].host.in_match = True

    def acquire_lock(self):
        self.lock.acquire()

    def release_lock(self):
        self.lock.release()

    def pack_session(self, index, pdata):
        session = self.sessions[index]
        session_data = [(session.host.name, session.host.address), ]
        for client in session.clients:
            session_data.append((client.name, client.address))

        max_len = MAX_GROUP_PACK - 1
        ctr = 0
        byte_strings = []
        for item in session_data:
            if ctr >= max_len:
                print("ERROR: LockedMatchingData::pack_session overflow")
                break
            name = item[0]
            ip_address, port = item[1][0], item[1][1]
            ip_bytes = bytes([int(addr_item) for addr_item in ip_address.split('.')]) \
                        + int.to_bytes(port, 2, 'little')
            byte_strings.append(pack('16s6s', name.encode(), ip_bytes))
            ctr += 1
        byte_str = b''.join(byte_strings)
        pdata.client_data = byte_str + b'000009'


class Session:

    def __init__(self, host):
        self.host = host
        self.clients = []
        self.client_max = host.match_size - 1
        self.addresses = set([host.address])
        self.locked = False

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

    def str_line_count(self):
        return 6 + len(self.clients) - 1


class SessionData:

    def __init__(self):
        self.sessions = []


"""
Usage of this in a thread-safe way requires thought; it doesn't just make usage safe automatically.
"""
class LockedList:

    def __init__(self, *args):
        self.list = list(*args)
        self.lock = Lock()

    """
    only for use after calling acquire_lock()
    """
    def __getitem__(self, index):
        return self.list[index]

    def __contains__(self, item):
        self.lock.acquire()
        contains_item = item in self.list
        self.lock.release()
        return contains_item

    def get(self, index):
        self.lock.acquire()
        item = self.list[index]
        self.lock.release()
        return item

    def find(self, item):
        self.lock.acquire()
        index = self.list.index(item)
        self.lock.release()
        return index

    def append(self, item):
        self.lock.acquire()
        self.list.append(item)
        self.lock.release()

    def remove(self, item):
        self.lock.acquire()
        self.list.remove(item)
        self.lock.release()

    def clear(self):
        self.lock.aqcuire()
        self.list.clear()
        self.lock.release()

    def acquire_lock(self):
        self.lock.acquire()

    def release_lock(self):
        self.lock.release()


def buffer_incoming(sock, bufsiz, incoming, name):
    """
    buffer incoming packets
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
