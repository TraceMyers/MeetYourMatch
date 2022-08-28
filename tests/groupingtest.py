import socket
from threading import Thread, Lock, local
from struct import pack, unpack
from time import sleep, time
from os import path
from inspect import currentframe, getfile
from sys import path as _path
from multiprocessing import Queue
from collections import deque
currentdir = path.dirname(path.abspath(getfile(currentframe())))
parentdir = path.dirname(currentdir)
_path.insert(0, parentdir)
from constants import *
from random import choice

def byte_name(name):
    return name.encode() + b'\0' * (12 - len(name))

def game_size_bytes(ct):
    return int.to_bytes(ct, 1, 'little') + b'\0' * 467

# instantiate
url = '192.168.0.203'
client_port = 7782
remote_ports = [7777, 7778, 7779]
buffer_size = 1024
flags = 0
time_stamp = 0
admin_key = b'\0' * 16
server_locs = [(url, remote_ports[i]) for i in range(len(remote_ports))]
sockets = [socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM) for _ in range(7)]
names = [
    'Travis', 'Duncan', 'Reshawn', 'Denise', 'Scooter', 'Jason', 'Jason', 'Mishmash!',
    'Skeeter', 'Newsy', 'Breezy'
]
statuses = [
    STATUS_REG_HOST, STATUS_REG_CLIENT, STATUS_REG_CLIENT, STATUS_REG_CLIENT, STATUS_REG_CLIENT,
    STATUS_REG_HOST_KNOWNHOST, STATUS_REG_CLIENT_KNOWNHOST
]
_client_data = [
    3, 0, 0, 0, 5, 5, 0, 0, 1, 0, 5
]
_client_data = [game_size_bytes(item) for item in _client_data]

# init & processing
for i in range(len(sockets)):
    _socket = sockets[i]
    _socket.bind((url, client_port + i))
names = [byte_name(name) for name in names]


def parse_client_data(client_data):
    group_prefix = b'000001'
    suffix = b'000009'
    iplist_prefix = b'000002'
    i = 0
    group_data = []
    iplist_data = []
    while True:
        if i + 6 > MAX_CLBYTES:
            break
        if client_data[i:i+6] == group_prefix:
            i += 6
            if i + 18 > MAX_CLBYTES:
                break
            while True:
                if i + 18 > MAX_CLBYTES:
                    break
                item = client_data[i:i+18]
                if item[:6] == suffix:
                    i += 6
                    break
                unpacked = unpack('12s6s', item)
                name = unpacked[0].decode()
                ip = '.'.join([str(int.from_bytes(
                    unpacked[1][j:j+1], 'little'
                )) for j in range(4)])
                port = int.from_bytes(unpacked[1][4:], 'little')
                group_data.append((name, (ip, port)))
                i += 18
        elif client_data[i:i+6] == iplist_prefix:
            i += 6
            if i + 6 > MAX_CLBYTES:
                break
            while True:
                if i + 6 > MAX_CLBYTES:
                    break
                item = client_data[i:i+6]
                if item == suffix:
                    i += 6
                    break
                unpacked = unpack('6s', item)[0]
                ip = '.'.join([str(int.from_bytes(
                    unpacked[j:j+1], 'little'
                )) for j in range(4)])
                port = int.from_bytes(unpacked[4:], 'little')
                iplist_data.append((ip, port))
                i += 6
        else:
            break
    return group_data, iplist_data

def get_timestamp():
    return time() * 1000 % 10000000

def packed_host_pings(host_pings):
    client_data = b'0'
    len_pings = len(host_pings.keys())
    if len_pings > 0:
        client_data = int.to_bytes(len_pings, 1, 'little')
        for address, lat in host_pings.items():
            ip_bytes = bytes([int(k) for k in address[0].split('.')])
            client_data += pack('4sHd', ip_bytes, address[1], lat)
    client_data += b'0' * (468 - len(client_data))
    return client_data

# numbers = unpack('4BHf', client_data[i:i+10])
# address_tup = ('.'.join([str(num) for num in numbers[:4]], numbers[4]))

def server_com_t(_socket, buf, name):
    while True:
        msg = _socket.recvfrom(buffer_size)
        buf[name].append(msg)
        

def listen(_socket, print_lock, names, recbuf, i):
    try:
        server_update_time = 5
        t_host_pings = local()
        t_host_pings = {}
        t_retname = local()
        t_status = local()
        t_flags = local()
        t_time_stamp = local()
        t_client_data = local()
        t_cl_data = local()
        t_msg = local()
        t_group_data = local()
        t_iplist_data = local()
        t_prev_time = local()
        t_prev_time = time()
        t_server_update_ctr = local()
        t_server_update_ctr = 0
        p_status = local()
        t_status = STATUS_NONE
        admin_key = b'0000' * 4


        while True:
            t_new_time = time()
            t_server_update_ctr += t_new_time - t_prev_time
            t_prev_time = t_new_time

            if len(recbuf[names[i]]) > 0:
                t_msg = recbuf[names[i]].popleft()
                t_status, t_flags, t_time_stamp, t_retname, admin_key, t_client_data = unpack('<2Id12s16s464s', t_msg[0])

            if t_server_update_ctr > server_update_time:
                t_status = STATUS_GROUPING
                if len(t_host_pings.keys()) > 0:
                    t_flags |= CL_ADDRESSES_LATENCIES
                    t_client_data = packed_host_pings(t_host_pings)
                else:
                    t_client_data = b'0' * 468
                t_cl_data = pack('<2Id12s16s464s', t_status, t_flags, t_time_stamp, names[i], admin_key, t_client_data)
                _socket.sendto(t_cl_data, choice(server_locs))
                t_flags = 0x0000
                p_status = STATUS_PING
                t_cl_data = pack('<2Id12s16s464s', p_status, t_flags, t_time_stamp, names[i], admin_key, t_client_data)
                for server_loc in server_locs:
                    sleep(0.001)
                    _socket.sendto(t_cl_data, server_loc)
                t_server_update_ctr = 0
            if t_status == STATUS_NONE:
                continue
            if t_status == STATUS_PING:
                # print(f'{names[i].decode()} got pinged from {t_retname.decode()}')
                t_status = STATUS_PINGBACK
                t_time_stamp = get_timestamp()
                t_cl_data = pack('<2Id12s16s464s', t_status, t_flags, t_time_stamp, names[i], admin_key, t_client_data)
                _socket.sendto(t_cl_data, t_msg[1])
                t_status = STATUS_NONE
            elif t_status == STATUS_PINGBACK:
                print_lock.acquire()
                t = get_timestamp() - t_time_stamp
                # print(f'{names[i].decode()} got pinged back from {t_retname.decode()}: {t:.2f}ms')
                t_host_pings[t_msg[1]] = t
                print(t_msg[1])
                print_lock.release()
                t_status = STATUS_NONE
            else:
                if t_status == STATUS_LATCHECK_HOST:
                    # print(f'{names[i].decode()} recieved message from {t_retname.decode()}')
                    t_group_data, t_iplist_data = parse_client_data(t_client_data)
                    # if len(t_group_data) > 0:
                    #     print(f'group: {t_group_data}')
                    if len(t_iplist_data) > 0:
                    #     print(f'iplist: {t_iplist_data}')
                        for ip_item in t_iplist_data:
                            t_status = STATUS_PORT_OPEN
                            t_cl_data = pack('<2Id12s16s464s', t_status, t_flags, t_time_stamp, names[i], admin_key, t_client_data)
                            _socket.sendto(t_cl_data, ip_item)
                    t_status = STATUS_NONE
                elif t_status == STATUS_LATCHECK_CLIENT:
                    # print(f'{names[i].decode()} recieved message from {t_retname.decode()}')
                    _, t_iplist_data = parse_client_data(t_client_data)
                    if len(t_iplist_data) > 0:
                        # print(f'iplist: {t_iplist_data}')
                        for ip_item in t_iplist_data:
                            t_status = STATUS_PING
                            t_time_stamp = get_timestamp()
                            t_cl_data = pack('<2Id12s16s464s', t_status, t_flags, t_time_stamp, names[i], admin_key, t_client_data)
                            _socket.sendto(t_cl_data, ip_item)
                    t_status =STATUS_NONE
    except KeyboardInterrupt:
        return

print_lock = Lock()
clients = []
recbuf = {n:deque() for n in names}
for i in range(len(sockets)):
    _socket = sockets[i]
    name = names[i]
    _status = statuses[i]
    client_data = _client_data[i]
    print(f'{i}')
    print("---")
    print(f"sending name={name.decode()}, status={hex(_status)}, data={client_data[0]}")
    print("---")
    cl_data = pack('<2Id12s16s464s', _status, flags, time_stamp, name, admin_key, client_data)
    _socket.sendto(cl_data, choice(server_locs))
    client_t = Thread(target=listen, args=(_socket, print_lock, names, recbuf, i))
    clients.append(client_t)
    myrec = Thread(target=server_com_t, args=(_socket, recbuf, names[i]))
    myrec.start()
    client_t.start()
    sleep(0.03)

for client in clients:
    if client.is_alive():
        client.join()


# DONE: (1) make and join named games
# DONE: (2) multiple, varied size groups with host & join testing
# TODO: (3) ping testing between clients
# DONE: (4) timeout communication & excecution between processes
# DONE: (5) migration process from grouping to session

# NOTE: need to be in control of client ports, so need to hijack Unreal comms