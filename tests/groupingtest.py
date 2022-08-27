import socket
from threading import Thread, Lock
from struct import pack, unpack
from time import sleep
from os import path
from inspect import currentframe, getfile
from sys import path as _path
currentdir = path.dirname(path.abspath(getfile(currentframe())))
parentdir = path.dirname(currentdir)
_path.insert(0, parentdir)
from constants import *

def byte_name(name):
    return name.encode() + b'\0' * (12 - len(name))

def game_size_bytes(ct):
    return int.to_bytes(ct, 1, 'little') + b'\0' * 467

# instantiate
url = '192.168.0.203'
client_port = 7782
remote_port = 7777
buffer_size = 1024
flags = 0
time_stamp = 0
admin_key = b'\0' * 16
server_loc = (url, remote_port)
sockets = [socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM) for _ in range(11)]
names = [
    'Travis', 'Duncan', 'Reshawn', 'Denise', 'Scooter', 'Jason', 'Jason', 'Mishmash!',
    'Skeeter', 'Newsy', 'Denise'
]
statuses = [
    STATUS_REG_HOST, STATUS_REG_CLIENT, STATUS_REG_CLIENT, STATUS_REG_HOST, STATUS_REG_HOST,
    STATUS_REG_HOST_KNOWNHOST, STATUS_REG_CLIENT_KNOWNHOST, STATUS_REG_CLIENT, STATUS_REG_HOST,
    STATUS_REG_CLIENT, STATUS_REG_HOST
]
_client_data = [
    1, 0, 0, 0, 5, 5, 0, 0, 1, 0, 5
]
_client_data = [game_size_bytes(item) for item in _client_data]

# init & processing
for i in range(len(sockets)):
    _socket = sockets[i]
    _socket.bind((url, client_port + i))
names = [byte_name(name) for name in names]

def listen(_socket, print_lock):
    try:
        while True:
            msg = _socket.recvfrom(buffer_size)
            status, flags, time_stamp, name, admin_key, client_data = unpack('<2If12s16s468s', msg[0])
            print_lock.acquire()
            print(hex(status), hex(flags), time_stamp, name.decode(), admin_key.decode())
            partner_ip = '.'.join([str(int.from_bytes(
                client_data[i:i+1], 'little'
            )) for i in range(4)])
            partner_ip += ':' + str(int.from_bytes(client_data[4:6], 'little'))
            print(f'partner_ip: {partner_ip}')
            print_lock.release()
    except KeyboardInterrupt:
        return

print_lock = Lock()
clients = []
for i in range(len(sockets)):
    _socket = sockets[i]
    name = names[i]
    _status = statuses[i]
    client_data = _client_data[i]
    print(f'{i}')
    print("---")
    print(f"sending name={name.decode()}, status={hex(_status)}, data={client_data[0]}")
    print("---")
    cl_data = pack('<2If12s16s468s', _status, flags, time_stamp, name, admin_key, client_data)
    _socket.sendto(cl_data, server_loc)
    client_t = Thread(target=listen, args=(_socket, print_lock))
    clients.append(client_t)
    client_t.start()
    sleep(0.1)

for client in clients:
    if client.is_alive():
        client.join()


# DONE: (1) make and join named games
# DONE: (2) multiple, varied size groups with host & join testing
# TODO: (3) ping testing between clients
# TODO: (4) timeout communication & excecution between processes
# TODO: (5) migration process from grouping to session
# TODO: (6) sessions belong on separate process

# NOTE: need to be in control of client ports, so need to hijack Unreal comms