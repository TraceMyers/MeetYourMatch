from multiprocessing import Process, Queue, Pipe, active_children
from threading import Thread, Lock
from sys import argv
from time import time
import socket

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

SORT_RPSI   = 0
SORT_TFER   = 1
SORT_ERR    = 2
SORT_BAN    = 3

ROLE_CLIENT = 0
ROLE_SERVER = 1
ROLE_NONE   = 2

ENTRY_TO_MAIN = 0
TFER0_TO_MAIN = 1
TFER1_TO_MAIN = 2
MAIN_TO_ENTRY = 3
MAIN_TO_TFER0 = 4
MAIN_TO_TFER1 = 5

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


ENTRY_KEY_CT = 200


class ConnectionData:

    def __init__(self):
        self.ip_to_client = dict()
        self.ip_log = [] # currently unused because it's slow


class Client:

    def __init__(self, name, address):
        self.name = name
        self.address = address
        self.local_key = -1
        self.local_status = STATUS_NONE
        self.remote_status = STATUS_NONE
        self.tfer_state = 0
        self.log_ctr = 0
        self.in_data = None


class Registry:

    def __init__(self):
        clients = [None for _ in range(ENTRY_KEY_CT)]


class PairingData:

    def __init__(self):
        clients = [None for _ in range(ENTRY_KEY_CT)]


class SessionInitData:

    def __init__(self):
        clients = [None for _ in range(ENTRY_KEY_CT)]


def register_clients():
    pass


def pair_clients():
    pass


def session_init():
    pass


def entry_process():
   regi_t = Thread(target=register_clients) 
   pair_t = Thread(target=pair_clients)
   sess_t = Thread(target=session_init)


def transfer_process(responses):
    pass


def receive_clients(
    udp_socket, 
    connection_data, 
    entry_pipe,
    tfer_pipes,
    responses, 
    buffer_size
):
    tfer_i = 0
    while True:
        try:
            msg = udp_socket.recvfrom(buffer_size)
        except WindowsError: # probably incoming package too big; ignore
            continue
        msg_data = msg[0]
        ip_address = msg[1]
        remote_status = msg_data[0]

        if remote_status == STATUS_NONE:
            c = Client(name=msg_data[2:42], address=ip_address)
            entry_pipe.send(c)
        else:
            address_port = ''.join(ip_address)
            try:
                client = connection_data.ip_to_client[address_port]
                client.remote_status = remote_status
            except:
                responses.put((ERROR_NO_CLIENT, ip_address))
            if remote_status & STATUS_TRANSFER:
                if client.local_status & STATUS_TRANSFER:
                    remote_tfer_state = msg_data[1]
                    if client.tfer_state == remote_tfer_state:
                        tfer_pipes[tfer_i].send(client)
                        tfer_i = 0 if tfer_i == 1 else 1
                    elif client.tfer_state > remote_tfer_state:
                        responses.put((ERROR_CLIENT_STATE_BEHIND, ip_address))
                    else:
                        responses.put((ERROR_CLIENT_STATE_AHEAD, ip_address))
                responses.put((ERROR_BAD_STATUS, ip_address))
            elif remote_status == STATUS_PAIRING:
                if client.local_status == STATUS_PAIRING \
                or client.local_status == STATUS_SESSION_PREPARING:
                    entry_pipe.send(client)
                responses.put((ERROR_BAD_STATUS, ip_address))
            elif remote_status == STATUS_SESSION_PREPARING:
                if client.local_status == STATUS_SESSION_PREPARING:
                    entry_pipe.send(client)
                responses.put((ERROR_BAD_STATUS, ip_address))
            elif remote_status == STATUS_SESSION_READY:
                if client.local_status == STATUS_SESSION_PREPARING \
                or client.local_status == STATUS_SESSION_READY:
                    entry_pipe.send(client)
                elif client.local_status == STATUS_TRANSFER:
                    tfer_pipes[tfer_i].send(client)
                    tfer_i = 0 if tfer_i == 1 else 1
                responses.put((ERROR_BAD_STATUS, ip_address))


def main():
    local_ip = '192.168.0.203'
    local_port = 8192
    buffer_size = 1024
    connection_data = ConnectionData()

    udp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    udp_socket.bind((local_ip, local_port))
    print(f'UDP TURN server running on {local_ip}:{local_port}')

    entry_pipe_remote, entry_pipe_local = Pipe()
    tfer0_pipe_remote, tfer0_pipe_local = Pipe()
    tfer1_pipe_remote, tfer1_pipe_local = Pipe()
    responses = Queue()

    entry_args = (entry_pipe_remote, responses)
    tfer0_args = (tfer0_pipe_remote, responses)
    tfer1_args = (tfer1_pipe_remote, responses)
    reccl_args = (
        udp_socket, 
        connection_data, 
        entry_pipe_local,
        (tfer0_pipe_local, tfer1_pipe_local),
        responses, 
        buffer_size
    )

    entry_proc = Process(target=entry_process, args=entry_args)
    tfer0_proc = Process(target=transfer_process, args=tfer0_args)
    tfer1_proc = Process(target=transfer_process, args=tfer1_args)
    reccl_t = Thread(target=receive_clients, args=reccl_args)
    try:
        entry_proc.start()
        tfer0_proc.start()
        tfer1_proc.start()
        reccl_t.start()
        while True:
            outgoing = []
            while not responses.empty():
                outgoing.append(responses.get())
            for response in outgoing:
                udp_socket.sendto(response[0], response[1])
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
