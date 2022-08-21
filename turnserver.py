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
        self.hash_to_client = dict()
        self.ip_log = []


class Client:

    def __init__(self, name, address, local_key):
        self.name = name
        self.address = address
        self.local_key = local_key
        self.status = STATUS_PAIRING
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


def registry_thread():
    pass


def pairing_thread():
    pass


def session_init_thread():
    pass


def entry_process():
   registry_t = Thread(target=registry_thread) 
   pairing_t = Thread(target=pairing_thread)
   session_init_t = Thread(target=session_init_thread)


def transfer_process():
    pass


def receive_clients(udp_socket, buffer_size, connection_data, pipe):
    with open('secret_key.txt') as f:
        secret_key = f.readline() # any old string

    while True:
        try:
            msg = udp_socket.recvfrom(buffer_size)
        except WindowsError: # probably too big
            pass

        msg_data = msg[0]
        remote_status = msg_data[0]

        if remote_status == STATUS_NONE:
            pipe.send(None, SORT_RPSI, 0)
        else:
            address_port = ''.join(msg[1])
            client_hash = hash(f'{address_port}{secret_key}')
            try:
                client = connection_data.hash_to_client[client_hash]
                client.in_data = msg_data
            except:
                pipe.send(None, SORT_ERR, ERROR_NO_CLIENT)

            if remote_status & STATUS_TRANSFER:
                if client.status & STATUS_TRANSFER:
                    remote_tfer_state = msg_data[1]
                    if client.tfer_state == remote_tfer_state:
                        pipe.send(client, SORT_TFER, 0)
                    elif client.tfer_state > remote_tfer_state:
                        pipe.send(None, SORT_ERR, ERROR_CLIENT_STATE_BEHIND)
                    else:
                        pipe.send(None, SORT_ERR, ERROR_CLIENT_STATE_AHEAD)
                pipe.send(None, SORT_ERR, ERROR_BAD_STATUS)
            elif remote_status == STATUS_PAIRING:
                if client.status == STATUS_PAIRING or client.status == STATUS_SESSION_PREPARING:
                    pipe.send(client, SORT_RPSI, 0)
                pipe.send(None, SORT_ERR, ERROR_BAD_STATUS)
            elif remote_status == STATUS_SESSION_PREPARING:
                if client.status == STATUS_SESSION_PREPARING:
                    pipe.send(client, SORT_RPSI, 0)
                pipe.send(None, SORT_ERR, ERROR_BAD_STATUS)
            elif remote_status == STATUS_SESSION_READY:
                if client.status == STATUS_SESSION_PREPARING or client.status == STATUS_SESSION_READY:
                    pipe.send(client, SORT_RPSI, 0)
                elif client.status == STATUS_TRANSFER:
                    pipe.send(client, SORT_TFER, 0)
                pipe.send(None, SORT_ERR, ERROR_BAD_STATUS)



# def main_thread(
#     udp_socket, 
#     socket_lock, 
#     pipe_locks, 
#     pipes, 
#     secret_key, 
#     connection_data, 
#     buffer_size
# ):
#     client, sort_code = retrieve_client(msg_in, secret_key, connection_data)


def main():
    # process_ct = 3
    # thread_ct = 3
    # port = 8192
    # just like a game, we need to check all of our processes in and hand out usable data to
    # each process every tick.
    # top process listens on the port, passes messages down

    
    local_ip = '192.168.0.203'
    local_port = 8192
    buffer_size = 1024
    main_thread_ct = 3
    connection_data = ConnectionData()

    udp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    udp_socket.bind((local_ip, local_port))
    print(f'UDP TURN server running on {local_ip}:{local_port}')

    entry_to_main, entry_to_main_snd = Pipe()
    tfer0_to_main, tfer0_to_main_snd = Pipe()
    tfer1_to_main, tfer1_to_main_snd = Pipe()
    main_to_entry_rcv, main_to_entry = Pipe()
    main_to_tfer0_rcv, main_to_tfer0 = Pipe()
    main_to_tfer1_rcv, main_to_tfer1 = Pipe()
    clrec_to_main_rcv, clrec_to_main_snd = Pipe()

    entry_args = (entry_to_main_snd, main_to_entry_rcv)
    tfer0_args = (tfer0_to_main_snd, main_to_tfer0_rcv)
    tfer1_args = (tfer1_to_main_snd, main_to_tfer1_rcv)

    entry_proc = Process(target=entry_process, args=entry_args)
    tfer0_proc = Process(target=transfer_process, args=tfer0_args)
    tfer1_proc = Process(target=transfer_process, args=tfer1_args)

    entry_proc.start()
    tfer0_proc.start()
    tfer1_proc.start()

    socket_lock = Lock()
    main_pipe_locks = (Lock() for _ in range(main_thread_ct))
    main_pipes = (entry_to_main, tfer0_to_main, tfer1_to_main, main_to_entry, main_to_tfer0, main_to_tfer1)

    # def receive_clients(udp_socket, buffer_size, connection_data, pipe, secret_key):
    # main_threads = (Thread(target=main_thread, args=(
    #     udp_socket, 
    #     socket_lock, 
    #     main_pipe_locks, 
    #     main_pipes, 
    #     secret_key, 
    #     connection_data, 
    #     buffer_size
    # )))

    recieving_thread = Thread(target=receive_clients, args=(udp_socket, buffer_size, connection_data, clrec_to_main_snd))
    recieving_thread.start()
    while True:
        try:
            # msg_data = msg_in[0]
            # msg_address = msg_in[1]
            # print(msg_data[0] & STATUS_PAIRING, msg_data[1] & ERROR_DATA_FORMAT, msg_address)
            # print(msg_data)
        except KeyboardInterrupt:
            for c in active_children():
                c.kill()

# import hashlib


# def get_sha256_hash(filename, buffer_size=2**10*8):
#     file_hash = hashlib.sha256()

# registration is thread-safe with a key queue
# 

# global variable data get and set
# 234:GET: player = pairing_registry[i]
# 230:SET: player.time_left -= delta_time
# 240:GET: game = game_registry[i]
# 245:SET: game.time_left -= delta_time


if __name__ == '__main__':
    main()
