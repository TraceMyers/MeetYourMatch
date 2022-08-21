from multiprocessing import Process, Queue, Pipe, active_children
from threading import Thread, Lock
from sys import argv
from time import time
import socket
from xmlrpc.client import NOT_WELLFORMED_ERROR

# client sends same state for keep alive, +1 for advance

STATUS_NONE                 = 0x00
STATUS_PAIRING              = 0x01
STATUS_SESSION_PREPARING    = 0x02
STATUS_SESSION_READY        = 0x03
STATUS_TRANSFER             = 0x08 
STATUS_TRANSFER_NO_DATA     = 0x09 
STATUS_TRANSFER_AGAIN       = 0x0a 

ERROR_DATA_FORMAT           = 0x10
ERROR_REGISTER_FAIL         = 0x20
ERROR_INTAKE_MAXED          = 0x30
ERROR_TRANSFERS_MAXED       = 0x40
ERROR_NO_SESSION            = 0x50
ERROR_NO_CLIENT             = 0x60
ERROR_NO_PARTNER            = 0x70
ERROR_CLIENT_STATE_BEHIND   = 0x80 
ERROR_CLIENT_STATE_AHEAD    = 0x90
ERROR_BAD_STATUS            = 0xa0
ERROR_FAST_POLL_RATE        = 0xb0
ERROR_IP_LOG_MAXED          = 0xc0
ERROR_CLIENT_LOG_MAXED      = 0xd0

SORT_REGI = 0
SORT_PAIR = 1
SORT_INIT = 2
SORT_TFER = 3
SORT_KICK = 4

ROLE_CLIENT = 0
ROLE_SERVER = 1
ROLE_NONE   = 2


# MAX_CONNECTS_PER_SEC = 

# 2-3 processes:
# 1. registration, pairing, session init
# 2. data relay
# 3. data relay (if needed)

# separator allowed in data field (bytes OK)
# better optimization per thread


# ----------- dividing data up for threads to each handle; data gets copied between them when a client
# advances in process, so they don't have to share data

# entry point, validates entry data, passes viable candidates to pairing pool


KEY_CT = 200
MAX_IP = KEY_CT * 4

class ConnectionLog:

    def __init__(self, max_poll_rate, turnover_time):
        self.ip_log = {}
        self.ip_to_client = {}
        self.turnover_time = turnover_time
        self.max_poll_rate = max_poll_rate

    def get_client(self, ip_address):
        if ip_address in self.ip_to_client:
            return self.ip_to_client[ip_address]
        return None

    def log_ip(self, ip_address):
        cur_time = time()
        if ip_address in self.ip_log:
            prev_time = self.ip_log[ip_address]
            if cur_time - prev_time < self.max_poll_rate:
                self.ip_log[ip_address] = cur_time
                return ERROR_FAST_POLL_RATE
        elif len(self.ip_log.keys()) >= MAX_IP:
            return ERROR_IP_LOG_MAXED
        self.ip_log[ip_address] = cur_time
        return 0

    def turnover(self):
        dropped_ips = []
        for key, value in self.ip_log.items():
            entry_delta_time = time() - value
            if entry_delta_time > self.turnover_time:
                dropped_ips.append(key)
                del self.ip_log[key]
                if key in self.ip_to_client:
                    del self.ip_to_client[key]
        return dropped_ips

    def forget(self, ip_address):
        # try is a little faster than if unless except is thrown; shouldn't throw most of the time
        try:
            del self.ip_log[ip_address]
        except:
            pass
        try:
            del self.ip_to_client[ip_address]
        except:
            pass


class Client:

    def __init__(self, name, ip_address):
        self.name = name
        self.ip_address = ip_address
        self.local_key = -1
        self.partner_key = None
        self.local_status = STATUS_NONE
        self.remote_status = STATUS_NONE
        self.tfer_state = 0
        self.in_data = None


class ClientData:

    def __init__(self):
        self.clients = [None for _ in range(KEY_CT)]
        self.key_ctr = 0


class Registry:

    def __init__(self):
        self.client_data = ClientData()


class PairingData:

    def __init__(self):
        self.client_data = ClientData()


class SessionInitData:

    def __init__(self):
        self.client_data = ClientData()


class SessionData:

    def __init__(self):
        self.client_data = ClientData()


def intake_unassign_clients(clients, from_struct):
    pass


def intake_assign_clients(clients, to_struct):
    struct_clients = to_struct.client_data.clients
    struct_key = to_struct.client_data.key_ctr
    if struct_key >= KEY_CT:
        return False, ERROR_INTAKE_MAXED
    for client in clients:
        struct_clients[struct_key] = client
        client.local_key = struct_key
        while struct_clients[struct_key] != None:
            struct_key += 1
            if struct_key >= KEY_CT:
                to_struct.client_data.key_ct = struct_key
                return False, ERROR_INTAKE_MAXED
    to_struct.client_data.key_ct = struct_key
    return True, 0


def register_clients():
    pass


def pair_clients():
    pass


def session_init():
    pass

def proc_entry(pipe, reponses, is_handler):
    regi_data = Registry()
    pair_data = PairingData()
    sint_data = SessionInitData()
    sess_data = SessionData()


def handle_clients(client_pipe, drop_pipe, responses):
    client_data = client_pipe.recv()
    drop_list = drop_pipe.recv()
    pass


def receive_clients(
    udp_socket, 
    connect_log, 
    handler_pipes,
    responses,
    connect_lock,
    buffer_size,
    subproc_ct
):
    pipe_i = -1

    while True:
        try:
            msg = udp_socket.recvfrom(buffer_size)
            pipe_i += 1
            if pipe_i >= subproc_ct:
                pipe_i = 0
        except WindowsError: # probably incoming package too big; ignore
            continue

        msg_data = msg[0]
        ip_address = msg[1]
        remote_status = msg_data[0]
        connect_lock.acquire()
        error = connect_log.log_ip(ip_address)
        connect_lock.release()
        if error > 0:
            responses.put((error, ip_address))
            continue
        if remote_status == STATUS_NONE:
            c = Client(name=msg_data[2:42], address=ip_address)
            handler_pipes[pipe_i].send((c, SORT_REGI))
        else:
            connect_lock.acquire()
            client = connect_log.get_client(ip_address)
            connect_lock.release()
            if client is None:
                responses.put((ERROR_NO_CLIENT, ip_address))
                continue
            client.remote_status = remote_status
            if remote_status & STATUS_TRANSFER:
                if client.local_status & STATUS_TRANSFER:
                    remote_tfer_state = msg_data[1]
                    if client.tfer_state == remote_tfer_state:
                        handler_pipes[pipe_i].send((client, SORT_TFER))
                    elif client.tfer_state > remote_tfer_state:
                        responses.put((ERROR_CLIENT_STATE_BEHIND, ip_address))
                        continue
                    else:
                        responses.put((ERROR_CLIENT_STATE_AHEAD, ip_address))
                        continue
                responses.put((ERROR_BAD_STATUS, ip_address))
            elif remote_status == STATUS_PAIRING:
                if client.local_status == STATUS_PAIRING:
                    handler_pipes[pipe_i].send((client, SORT_PAIR))
                elif client.local_status == STATUS_SESSION_PREPARING:
                    handler_pipes[pipe_i].send((client, SORT_INIT))
                else:
                    responses.put((ERROR_BAD_STATUS, ip_address))
                    continue
            elif remote_status == STATUS_SESSION_PREPARING:
                if client.local_status == STATUS_SESSION_PREPARING:
                    handler_pipes[pipe_i].send(client)
                else:
                    responses.put((ERROR_BAD_STATUS, ip_address))
                    continue
            elif remote_status == STATUS_SESSION_READY:
                if client.local_status == STATUS_SESSION_PREPARING \
                or client.local_status == STATUS_SESSION_READY:
                    handler_pipes[pipe_i].send(client)
                elif client.local_status == STATUS_TRANSFER:
                    handler_pipes[pipe_i].send(client)
                else:
                    responses.put((ERROR_BAD_STATUS, ip_address))
                    continue

# TODO: figure out how to pack out data, including where ROLE goes

def main():
    local_ip = '192.168.0.203'
    local_port = 8192
    buffer_size = 1024
    subproc_ct = 3
    ip_turnover_time = 15
    ip_turnover_update = 5
    max_poll_rate = 0.099
    connect_log = ConnectionLog(max_poll_rate, ip_turnover_time)

    udp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    udp_socket.bind((local_ip, local_port))
    print(f'UDP TURN server running on {local_ip}:{local_port}')

    reccl_handler_pipes = (Pipe() for _ in range(subproc_ct))
    reccl_handler_pipes_rcv = [pipe[0] for pipe in reccl_handler_pipes]
    reccl_handler_pipes_snd = [pipe[1] for pipe in reccl_handler_pipes]
    main_handler_pipes = (Pipe() for _ in range(subproc_ct))
    main_handler_pipes_rcv = [pipe[0] for pipe in main_handler_pipes]
    main_handler_pipes_snd = [pipe[1] for pipe in main_handler_pipes]
    responses = Queue()
    connect_lock = Lock()

    handler_args = (
        (reccl_handler_pipes_rcv[i], main_handler_pipes_rcv[i], responses) 
        for i in range(subproc_ct)
    )
    reccl_args = (
        udp_socket, 
        connect_log, 
        reccl_handler_pipes_snd,
        responses,
        connect_lock,
        buffer_size,
        subproc_ct
    )

    handlers = [Process(target=handle_clients, args=handler_args[i]) for i in range(subproc_ct)]
    reccl_t = Thread(target=receive_clients, args=reccl_args)
    try:
        for i in range(subproc_ct):
            handlers[i].start()
        reccl_t.start()
        ip_turnover_ctr = 0
        prev_time = time()
        while True:
            outgoing = []
            while not responses.empty():
                outgoing.append(responses.get())
            for response in outgoing:
                udp_socket.sendto(response[0], response[1])
            
            new_time = time()
            ip_turnover_ctr += new_time - prev_time
            if ip_turnover_ctr >= ip_turnover_update:
                connect_lock.acquire()
                dropped = connect_log.turnover()
                connect_lock.release()
                for pipe in main_handler_pipes_snd:
                    pipe.send(dropped)
                ip_turnover_ctr = 0
            prev_time = new_time
    except KeyboardInterrupt:
        for c in active_children():
            c.kill()
        

# msg_data = msg_in[0]
# msg_address = msg_in[1]
# print(msg_data[0] & STATUS_PAIRING, msg_data[1] & ERROR_DATA_FORMAT, msg_address)
# print(msg_data)

# registration is thread-safe with a key queue
# 

# global variable data get and set
# 234:GET: player = pairing_registry[i]
# 230:SET: player.time_left -= delta_time
# 240:GET: game = game_registry[i]
# 245:SET: game.time_left -= delta_time


if __name__ == '__main__':
    main()
