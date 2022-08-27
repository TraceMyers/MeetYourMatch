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
    2, 0, 0, 0, 6, 6, 0, 0, 2, 0, 6
]
_client_data = [game_size_bytes(item) for item in _client_data]

# init & processing
for i in range(len(sockets)):
    _socket = sockets[i]
    _socket.bind((url, client_port + i))
names = [byte_name(name) for name in names]


