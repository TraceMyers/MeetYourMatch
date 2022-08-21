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


def handle_clients(pipe, responses):
    client_data = pipe.recv()


def receive_clients(
    udp_socket, 
    connection_data, 
    handler_pipes,
    responses, 
    buffer_size,
    subproc_ct
):
    pipe_i = -1

    while True:
        pipe_i += 1
        if pipe_i >= subproc_ct:
            pipe_i = 0

        try:
            msg = udp_socket.recvfrom(buffer_size)
        except WindowsError: # probably incoming package too big; ignore
            continue

        msg_data = msg[0]
        ip_address = msg[1]
        remote_status = msg_data[0]

        if remote_status == STATUS_NONE:
            c = Client(name=msg_data[2:42], address=ip_address)
            handler_pipes[pipe_i].send((c, SORT_REGI))
        else:
            address_port = ''.join(ip_address)
            try:
                client = connection_data.ip_to_client[address_port]
                client.remote_status = remote_status
            except:
                responses.put((ERROR_NO_CLIENT, ip_address))
                continue
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
    connection_data = ConnectionData()

    udp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    udp_socket.bind((local_ip, local_port))
    print(f'UDP TURN server running on {local_ip}:{local_port}')

    handler_pipes = (Pipe() for _ in range(subproc_ct))
    responses = Queue()

    handler_args = ((handler_pipes[i], responses) for i in range(subproc_ct))
    reccl_args = (
        udp_socket, 
        connection_data, 
        handler_pipes,
        responses, 
        buffer_size,
        subproc_ct
    )

    handlers = [Process(target=handle_clients, args=handler_args[i]) for i in range(subproc_ct)]
    reccl_t = Thread(target=receive_clients, args=reccl_args)
    try:
        for i in range(subproc_ct):
            handlers[i].start()
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
