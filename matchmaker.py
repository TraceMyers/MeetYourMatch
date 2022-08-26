from multiprocessing import Process, Pipe, active_children, Manager
from threading import Thread, Lock
from sys import argv
from time import time, sleep
import socket
from struct import pack, unpack
from collections import deque
import traceback
from constants import *

# NOTE: the use of ':' before each section name allows for easy section searching
# NOTE: another architecture I thought of when waking: multi-headed with end-to-end recv & send
#       processes that communicate with each other. And, data is piped in a circular fashion
#       between them so they have fairly consistent piping times once the server is loaded.
#       If all data is piped this way, the architecture scales indefinitely with increasingly
#       worse connection refusal accuracy; so, to work, registration and connection refusal
#       would have to happen on a separate server that maintains a master record of all
#       clients in session; that server would inform the matchmaking & session server
#       to expect a new connection, and the client would be told to connect to that server.
#       registration should use TCP
# TODO: name registering so that users can always expect to use the same name
# TODO: use debugger *often*
# TODO: try STUN then TURN for every session; STUN sessions in a separate cache
#       and keep them alive with generous timeout & host regularly pinging. If
#       a new client joins whose router refuses the nat punch, send message to host
#       asking whether to: refuse client connection or allow client over TURN;
#       sessions thus grouped and treated differently: STUN, TURN, MIXED
# TODO: STUN latency gauging - pass clients host list and client returns with latencies
#       pass hosts client lists to expect messages from
#       also serves as STUN success check
# TODO: TURN latency gauging - handle per regular update
# TODO: send_bytes() and recv_bytes() shaved off 10-20ms per 10,000 packets
# TODO: send back expected match join time & that will be reflected in the amt of time before
#       matches are made. Making match time dependent on new connection rate makes match quality
#       less dependent on connection rate
# TODO: process cldata buffers are statically sized, which means they need to be checked for end
#       every assignment
# TODO: change resp_queue to resp_pipe, since each process as its own socket now
# TODO: clients need to ping server every 7.4 seconds or so on whatever ports they aren't sending to
#       in order to maintain the connections and continue to recieve from those ports AND it should
#       be spacing them out to come out over the max poll rate

# --------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------:classes
# --------------------------------------------------------------------------------------------------

# ------------------------------------------------------------------------------------------:network

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
        """log and refuse connections"""
        cur_time = time()
        if ip_address in self.ip_log:
            prev_time = self.ip_log[ip_address]
            if cur_time - prev_time < self.max_poll_rate:
                return ERROR_FAST_POLL_RATE
        elif len(self.ip_log.keys()) >= SES_MAX:
            return ERROR_IP_LOG_MAXED
        self.ip_log[ip_address] = cur_time
        return 0

    def turnover(self):
        """drop stale connections"""
        turnover_time = self.turnover_time
        ip_log = self.ip_log
        ip_to_client = self.ip_to_client

        dropped_ips = []
        for key, value in ip_log.items():
            entry_delta_time = time() - value
            if entry_delta_time > turnover_time:
                dropped_ips.append(key)
        for ip in dropped_ips:
            del ip_log[ip]
            if ip in ip_to_client:
                del ip_to_client[ip]
        return dropped_ips

    def forget_client(self, ip_address):
        del self.ip_log[ip_address]
        del self.ip_to_client[ip_address]


class CLData:

    __slots__ = (
        'status', 'flags', 'time_stamp', 'name', 'admin_key', 'client_data'
    )
    def __init__(self):
        self.status = STATUS_NONE           # 4
        self.flags = 0                      # 4
        self.time_stamp = 0                 # 4
        self.name = 'JoeErrname'            # 12
        self.admin_key = None               # 16
        self.client_data = DEFAULT_CLDATA   # 468 (udp) -> 508 total

    def unpacket_udp(self, data):
        self.status, self.flags, self.time_stamp, self.name, \
            self.admin_key, self.client_data = unpack('<2If12s16s468s', data)
        self.name = self.name.decode()
        self.admin_key = self.admin_key.decode()

# -------------------------------------------------------------------------------------------:client

class Client:
    """
    Data piped from main process once sorted.
    """

    __slots__ = ('name', 'status', 'address', 'latency', 'group_size')
    def __init__(self, name, address, status, latency=0.0, group_size=2):
        self.name = name
        self.status = status
        self.address = address
        self.latency = latency # for TURN only
        self.group_size = group_size

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f'{self.address[0]}:{self.address[1]} | {self.name} | {self.status:04X}'


class GrpClient(Client):

    def __init__(self, client):
        super().__init__(client.name, client.address, client.status, 0, client.group_size)
        self.lat_status = LAT_LOW
        self.host_latencies = {}
        self.lat_ctr = 0
        self.avg_latency = 0 # for TURN only
        self.avg_latency_ctr = 0 # for TURN only

# -------------------------------------------------------------------------------------:handler data

class RegisterBuffer:

    __slots__ = ('clients', 'client_ct')
    def __init__(self):
        self.clients = {}
        self.client_ct = 0

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        clients = '\n'.join([str(client) for client in self.clients])
        return(
            f'--------------------------\nRegister Buffer:\n--------------------------\n{clients}'
        )


class GroupingData:

    __slots__ = ('ungrouped_clients', 'client_ct', 'addresses', 'sessions', 'session_ct')
    def __init__(self):
        self.ungrouped_clients = []
        self.client_ct = 0
        self.addresses = set()
        self.sessions = []
        self.session_ct = 0

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        clients = '\n'.join([str(client) for client in self.ungrouped_clients])
        sessions = '\n'.join([str(session) for session in self.sessions])
        return(
            '--------------------------\nGrouping Data:\n--------------------------\n'
            f'= Ungrouped Clients =\n\n{clients}\n\n= Sessions =\n\n{sessions}'
        )


class SessionData:

    def __init__(self):
        pass


class Session:

    def __init__(self, host, client_max=2):
        # TODO: set client max
        # TODO: probably make a GrpSession w/out addresses
        self.host = host
        self.known_name = None if host.status != STATUS_REG_HOST_KNOWNHOST else host.name
        self.clients = []
        self.client_ct = 1
        self.client_max = client_max
        self.com = COM_STUN
        self.addresses = set([host.address]) # used after grouping

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        clients = '\n'.join([str(client) for client in self.clients])
        return(
            '=============|Session|=============\n'
            f'client ct = {self.client_ct} | client max = {self.client_max}\n'
            '= Host =\n'
            f'{self.host}\n'
            f'= Clients =\n{clients}\n'
        )

# --------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------:functions
# --------------------------------------------------------------------------------------------------

# ------------------------------------------------------------------------------------------:packing

def get_timestamp():
    return time.time() * 1000 % 10000000 # milliseconds for single-precision float packing


def pack_udp(cl_data):
    return pack(
        f'<2If12s16s468s',
        cl_data.status, cl_data.flags, cl_data.time_stamp, 
        bytes(cl_data.name, 'utf-8'), GAP, cl_data.client_data
    )


def pack_tcp(cl_data):
    # TODO: recalculate client_data size
    return pack(
        f'<2If12s16s1312s',
        cl_data.status, cl_data.flags, cl_data.time_stamp, 
        bytes(cl_data.name, 'utf-8'), GAP, cl_data.client_data
    )


def set_group_size(cldata, client):
    client.group_size = cldata.client_data[0]
    return 2 <= client.group_size <= MAX_GROUP_SIZE

# -----------------------------------------------------------------------------------------:register

def regbuf_add_client_to_local(client, register_buffer, main_cldata, cld_i):
    client_address = client.address
    buf_clients = register_buffer.clients
    if register_buffer.client_ct >= SES_MAX:
        cld_i = grp_cldata_basic_add(main_cldata, cld_i, ERROR_INTAKE_MAXED, client_address)
        return cld_i
    elif client_address in buf_clients:
        cld_i = grp_cldata_basic_add(main_cldata, cld_i, STATUS_NONE, client_address)
        return cld_i
    cld_i = grp_cldata_basic_add(main_cldata, cld_i, client.status, client_address)
    buf_clients[client_address] = client
    register_buffer.client_ct += 1
    return cld_i


def regbuf_copy_local_to_central(local, central):
    central_clients = central.clients
    local_clients = local.clients
    central_client_ct = central.client_ct
    for address in local_clients.keys():
        if address not in central_clients:
            central_clients[address] = local_clients[address]
            central_client_ct += 1
    central.client_ct = central_client_ct
    local_clients.clear()
    local.client_ct = 0

# --------------------------------------------------------------------------------------------:group

def grp_merge_regbuf(
        grpdat,
        regbuf_clients,
        regbuf_client_keys,
        grp_cldata,
        grpdat_hosts,
        session_hosts
):
    grpdat_addresses = grpdat.addresses
    grpdat_client_ct = grpdat.client_ct
    grpdat_session_ct = grpdat.session_ct
    grpdat_sessions = grpdat.sessions
    cldata_ctr = 0

    for address in regbuf_client_keys:
        client = regbuf_clients[address]
        client_status = client.status
        if address in grpdat_addresses:
            cldata_ctr = grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_ALREADY_REGISTERED, address)
            continue
        elif grpdat_client_ct >= SES_MAX:
            cldata_ctr = grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_INTAKE_MAXED, address)
            continue
        elif client_status == STATUS_REG_CLIENT:
            cldata_ctr = grp_cldata_basic_add(grp_cldata, cldata_ctr, STATUS_GROUPING, address)
            grp_add_client_to_ungrouped(grpdat, GrpClient(client))
        elif client_status == STATUS_REG_HOST or client_status == STATUS_REG_HOST_KNOWNHOST:
            client_name = client.name
            hostname_i = grp_hostname_index(grpdat_hosts, grpdat_session_ct, client_name)
            if hostname_i >= 0:
                cldata_ctr = \
                    grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_HOST_NAME_TAKEN, address)
                continue
            join_request_list = get_session_jrq(session_hosts, client_name)
            if join_request_list is not None:
                cldata_ctr = \
                    grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_HOST_NAME_TAKEN, address)
                continue
            cldata_ctr = grp_cldata_basic_add(grp_cldata, cldata_ctr, STATUS_GROUPING, address)
            grp_add_session(grpdat, GrpClient(client))
        elif client_status == STATUS_REG_CLIENT_KNOWNHOST:
            client_name = client.name
            hostname_index = \
                grp_hostname_index(grpdat_hosts, grpdat_session_ct, client_name)
            if hostname_index >= 0:
                session = grpdat_sessions[hostname_index]
                if session.client_ct >= session.client_max:
                    cldata_ctr = \
                        grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_SESSION_MAXED, address)
                    continue
                # TODO: password check; just have default password None
                iplist_bytes = grp_iplist_to_bytes((session.host.address, ))
                cldata_ctr = grp_cldata_iplist_add(
                    grp_cldata,
                    cldata_ctr,
                    STATUS_GROUPING,
                    client.address,
                    iplist_bytes
                )
                session.clients.append(GrpClient(client))
                session.addresses.add(address)
                grpdat_addresses.add(address)
                session.client_ct += 1
                grpdat_client_ct += 1
            else:
                join_request_list = get_session_jrq(session_hosts, client_name)
                if join_request_list is None:
                    cldata_ctr = \
                        grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_NO_SESSION, address)
                    continue
                join_request_list.append(GrpClient(client))
                cldata_ctr = grp_cldata_basic_add(grp_cldata, cldata_ctr, STATUS_GROUPING, address)
                continue

    regbuf_clients.clear()
    return cldata_ctr


def grp_cldata_basic_add(cldata_list, cldata_i, status, address):
    cldata_tup = cldata_list[cldata_i]
    cldata_tup[0].status = status
    cldata_tup[1] = address
    return cldata_i + 1


def grp_iplist_to_bytes(iplist):
    # 78 = 468 // 6, max number of 6 byte ip/ports we can pack
    len_iplist = len(iplist)
    if len_iplist > 78:
        address_byte_list = [
            bytes([int(item) for item in ip_port[0].split('.')])
            + int.to_bytes(ip_port[1], 2, 'little')
            for ip_port in iplist[:78]
        ]
        ip_ct = 78
    else:
        address_byte_list = [
            bytes([int(item) for item in ip_port[0].split('.')])
            + int.to_bytes(ip_port[1], 2, 'little')
            for ip_port in iplist
        ]
        ip_ct = len_iplist
    ip_bytes = b''.join(address_byte_list)
    byte_ct = ip_ct * 6
    null_pack_ct = 78 - ip_ct
    null_pack = b'\0\0\0\0' * null_pack_ct
    null_pack_chars = null_pack_ct * 4
    return pack(f'{byte_ct}s{null_pack_chars}s', ip_bytes, null_pack)

def grp_cldata_iplist_add(cldata_list, cldata_i, status, address, ip_bytes):
    cldata_tup = cldata_list[cldata_i]
    cldata = cldata_tup[0]
    cldata.client_data = ip_bytes
    cldata.status = status
    cldata_tup[1] = address
    return cldata_i + 1


def grp_add_client_to_ungrouped(grpdat, client):
    grpdat.ungrouped_clients.append(client)
    grpdat.addresses.add(client.address)
    grpdat.client_ct += 1


def grp_rem_client_from_ungrouped(grpdat, client, dropping=False):
    grpdat.ungrouped_clients.remove(client)
    if dropping:
        grpdat.addresses.remove(client.address)
        grpdat.client_ct -= 1


def grp_add_session(grpdat, host):
    grpdat.addresses.add(host.address)
    session = Session(host, host.group_size)
    grpdat.sessions.append(session)
    grpdat.session_ct += 1
    grpdat.client_ct += 1


def grp_rem_session(grpdat, session):
    grpdat.addresses.remove(session.host.address)
    for client in session.clients:
        grpdat.addresses.remove(client.address)
    grpdat.client_ct -= session.client_ct
    grpdat.sessions.remove(session)
    grpdat.session_ct -= 1


def grp_rem_client_from_session(grpdat, session, client):
    client_address = client.address
    grpdat.addresses.remove(client_address)
    session.addresses.remove(client_address)
    session.clients.remove(client)
    session.client_ct -= 1
    grpdat.client_ct -= 1


def get_session_jrq(hostnames, name):
    if name in hostnames:
        return hostnames[name][1]
    return None


def grp_hostname_index(hostnames, session_ct, name):
    for i in range(session_ct):
        if hostnames[i] == name:
            return i
    return -1

# --------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------:thread entry points
# --------------------------------------------------------------------------------------------------

def grp_handle(grpdat, regbuf_queue, grp_cldata, sessions_hostnames, delta_time):
    cldata_ctr = 0
    # TODO: would be better to check a shared memory value
    regbuf = regbuf_queue.get()
    if regbuf.client_ct > 0:
        regbuf_clients = regbuf.clients
        regbuf_client_keys = regbuf_clients.keys()
        # avoiding piping a list we can just decompress from existing data here
        grpdat_sessions = grpdat.sessions
        grpdat_hostnames = [session.host.name for session in grpdat_sessions] # TODO MOVE
        if grpdat.client_ct == SES_MAX:
            for address in regbuf_client_keys:
                cldata_ctr = grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_INTAKE_MAXED, address)
            regbuf_clients.clear()
            regbuf.client_ct = 0
            regbuf_queue.put(regbuf)
            return
        else:
            cldata_ctr = grp_merge_regbuf(
                grpdat,
                regbuf_clients,
                regbuf_client_keys,
                grp_cldata,
                grpdat_hostnames,
                sessions_hostnames
            )
            regbuf.client_ct = 0
            regbuf_queue.put(regbuf)
    else:
        regbuf_queue.put(regbuf)

    grpdat_ungrouped_clients = grpdat.ungrouped_clients
    # host_addresses = [session.host.address for session in grpdat_sessions]
    for client in grpdat_ungrouped_clients:
        if client.lat_status < LAT_TOP:
            client.lat_ctr += delta_time
            if client.lat_ctr >= LAT_TURNOVER:
                client.lat_status += 1
                client.lat_ctr = 0

    # -- try to fill currently grouping sessions with ungrouped clients --

    grpdat_session_ct = grpdat.session_ct
    grouped_clients = []

    # TODO: can handle this more efficiently (like below)
    for i in range(len(grpdat_ungrouped_clients)):
        for j in range(grpdat_session_ct):
            client = grpdat_ungrouped_clients[i]
            session = grpdat_sessions[j]
            host_address = session.host.address
            client_host_latencies = client.host_latencies
            if host_address in client.host_latencies \
            and client_host_latencies[host_address] < LATCHECK[client.lat_status]:
                session_client_max = session.client_max
                session_clients = session.clients
                session_known_name = session.known_name
                if session.client_ct < session_client_max and session_known_name is None:
                    grouped_clients.append(client)
                    session_clients.append(client)
                    session.client_ct += 1
                    session.addresses.add(client.address)
                    # TODO: func for generating group IP list
                    # TODO: func for generating host & unmatched IP list
                    iplist_bytes = grp_iplist_to_bytes((host_address, ))
                    cldata_ctr = grp_cldata_iplist_add(
                        grp_cldata,
                        cldata_ctr,
                        STATUS_GROUPING,
                        client.address,
                        iplist_bytes
                    )
                    break
    for client in grouped_clients:
        grp_rem_client_from_ungrouped(grpdat, client)
    grouped_clients.clear()

    # -- try to fill currently running sessions --

    ungrouped_start_i = 0
    len_ungrouped = len(grpdat_ungrouped_clients)
    for key in sessions_hostnames.keys():
        session_peek = sessions_hostnames[key]
        space_avail = session_peek[0]
        join_request_list = session_peek[1]
        for i in range(ungrouped_start_i, len_ungrouped):
            if space_avail > 0:
                join_request_list.append(client)
                grouped_clients.append(client)
                cldata_ctr = \
                    grp_cldata_basic_add(grp_cldata, cldata_ctr, STATUS_GROUPING, client.address)
                space_avail -= 1
            else:
                ungrouped_start_i = i
                break
        session_peek[0] = space_avail
    for client in grouped_clients:
        grp_rem_client_from_ungrouped(grpdat, client)
    grouped_clients.clear()

    # -- send back errors to those who did not make the cut --

    len_ungrouped = len(grpdat_ungrouped_clients)
    if len_ungrouped > 0:
        for i in range(ungrouped_start_i, len_ungrouped):
            client = grpdat_ungrouped_clients[i]
            grouped_clients.append(client)
            cldata_ctr = \
                grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_INTAKE_MAXED, client.address)
    for client in grouped_clients:
        grp_rem_client_from_ungrouped(grpdat, client)


def main_incoming_sort(
    udp_socket,
    tcp_socket,
    resp_queue,
    connect_log,
    connect_lock,
    handler_pipe,
    incoming,
    incoming_lock
):
    """
    Parse socket messages, log connections, handle flags, send back some errors, and
    pipe sorted data to handler processes.
    """
    # TODO: remove Client and create SessClient when transitioning to session
    # TODO: rn this allows for a user to create multiple client entries throughout
    #       the process, including in multiple sessions. solution: just drop them when the intake
    #       client gets to session and refuse their connection for a while.
    # TODO: maybe forget one-way data. subprocesses are mostly session data agnostic, so there is no
    #       reason to shove all of that through the pipes. Just have a sender thread. main process
    #       needs more to do anyway

    error_cldata = CLData()
    error_cldata.status |= ERROR_BAD_STATUS
    cldata = CLData()

    incoming_lock_acquire = incoming_lock.acquire
    incoming_lock_release = incoming_lock.release
    udp_socket_sendto = udp_socket.sendto
    connect_log_log_ip = connect_log.log_ip
    connect_log_get_client = connect_log.get_client
    connect_lock_acquire = connect_lock.acquire
    connect_lock_release = connect_lock.release
    resp_queue_put = resp_queue.put
    resp_queue_get = resp_queue.get
    handler_pipe_send = handler_pipe.send
    cldata_unpacket_udp = cldata.unpacket_udp

    while True:

        # pop() is atomic, but it throws an exception if the list is empty. Haven't tested a 
        # try/except, but I suspect throwing an exception is worse than using a lock
        incoming_lock_acquire()
        while len(incoming) == 0:
            pass
        msg = incoming.popleft()
        incoming_lock_release()

        # -- log connection and refuse if log maxed or if client polling too often --

        ip_address = msg[1]
        if ip_address[1] not in ACCEPT_TRAFFIC_PORTS:
            continue
        connect_lock_acquire()
        error = connect_log_log_ip(ip_address)
        connect_lock_release()
        if error > 0:
            error_cldata.status = error
            error_cldata.time_stamp = time()
            key = resp_queue_get()
            udp_socket_sendto(pack_udp(error_cldata), ip_address)
            resp_queue_put(key)
            continue

        cldata_unpacket_udp(msg[0])

        # TODO: handle admin key and flags on cldata

        remote_status = cldata.status
        if remote_status == STATUS_KEEP_ALIVE:
            # client is pinging server ports to keep connections alive
            continue
        elif remote_status & STATUS_REG_MASK:
            client = Client(cldata.name, ip_address, remote_status)
            if remote_status == STATUS_REG_HOST or remote_status == STATUS_REG_HOST_KNOWNHOST:
                success = set_group_size(cldata, client)
                if not success:
                    error_cldata.status = ERROR_BAD_GROUP_SIZE
                    error_cldata.time_stamp = time()
                    key = resp_queue_get()
                    udp_socket_sendto(pack_udp(error_cldata), ip_address)
                    resp_queue_put(key)
                    continue
            connect_log.ip_to_client[ip_address] = client # atomic
            handler_pipe_send(client)
        else:
            connect_lock_acquire()
            client = connect_log_get_client(ip_address)
            connect_lock_release()
            if client is None:
                error_cldata.status = ERROR_NO_CLIENT
                error_cldata.time_stamp = time()
                key = resp_queue_get()
                udp_socket_sendto(pack_udp(error_cldata), ip_address)
                resp_queue_put(key)
            elif remote_status <= STATUS_TRANSFER_AGAIN:
                client.latency = time() - cldata.time_stamp
                client.status = remote_status
                handler_pipe_send(client)
            else:
                error_cldata.status |= ERROR_BAD_STATUS
                error_cldata.time_stamp = time()
                key = resp_queue_get()
                udp_socket_sendto(pack_udp(error_cldata), ip_address)
                resp_queue_put(key)


def main_incoming(udp_socket, tcp_socket, incoming, buffer_size):
    """
    buffer incoming data
    """
    udp_socket_recvfrom = udp_socket.recvfrom

    while True:
        try:
            incoming.append(udp_socket_recvfrom(buffer_size))
        except WindowsError: 
            # probably incoming package too big; ignore
            # TODO: get more details
            continue
        except Exception as e:
            print('ERROR matchmaker.py main_incoming():: passed exception from udp_socket_recvfrom()')
            print(e)
            continue


def handler_incoming(client_pipe, incoming):
    incoming_append = incoming.append
    client_pipe_recv = client_pipe.recv
    while True:
        try:
            incoming_append(client_pipe_recv())
        except Exception as e:
            print('ERROR matchmaker.py handler_incoming():: passed exception from client_pipe_recv()')
            print(e)
            continue


# --------------------------------------------------------------------------------------------------
# -----------------------------------------------------------------------------:process entry points
# --------------------------------------------------------------------------------------------------

def main(_verbose, _subprocess_ct, port_start):
    udp_ports = [i for i in range(port_start, port_start + _subprocess_ct)]
    socket_ct = len(udp_ports)
    udp_bufsize = 1500
    tcp_port = 17777
    tcp_bufsize = 1500
    local_ip = '192.168.0.203'
    udp_sockets = [
        socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM) for _ in range(socket_ct)
    ]
    for i in range(socket_ct):
        udp_sockets[i].bind((local_ip, udp_ports[i]))
    tcp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
    tcp_socket.bind((local_ip, tcp_port))

    local_port_str = ', '.join([str(port) for port in udp_ports])
    remote_port_str = ', '.join([str(port) for port in ACCEPT_TRAFFIC_PORTS])
    # NOTE: currently just using udp
    while True:
        try:
            print(f'Meet Your Match server loading at {local_ip} on ports:\n{local_port_str}')
            print(f'accepting traffic from ports:\n{remote_port_str}')
            main_proc(tcp_socket, udp_sockets, udp_bufsize, socket_ct, _verbose)
        except KeyboardInterrupt:
            for c in active_children():
                c.kill()
            return
        except Exception as e:
            # TODO dump exception to log
            traceback.print_exc()
            for c in active_children():
                c.kill()
        sleep(5)

# ----------------------------------------------------------------------------------------:main proc

def main_proc(tcp_socket, udp_sockets, buffer_size, udp_socket_ct, _verbose):
    subproc_ct = udp_socket_ct
    ip_turnover_time = 15
    ip_turnover_update = 5
    max_poll_rate = 0.099
    incoming = deque()
    max_sessions = 100
    verbose_print_time = 10

    connect_log = ConnectionLog(max_poll_rate, ip_turnover_time)

    incsort_handler_pipes = [Pipe() for _ in range(subproc_ct)]
    incsort_handler_pipes_rem = [incsort_handler_pipes[i][0] for i in range(subproc_ct)]
    incsort_handler_pipes_loc = [incsort_handler_pipes[i][1] for i in range(subproc_ct)]
    main_handler_pipes = [Pipe() for _ in range(subproc_ct)]
    main_handler_pipes_rem = [main_handler_pipes[i][0] for i in range(subproc_ct)]
    main_handler_pipes_loc = [main_handler_pipes[i][1] for i in range(subproc_ct)]
    multi_manager = Manager()
    resp_queues = [multi_manager.Queue() for _ in range(subproc_ct)]
    regbuf_queue = multi_manager.Queue()
    print_queue = multi_manager.Queue()
    connect_lock = Lock()
    incoming_lock = Lock()
    for queue in resp_queues:
        queue.put((0,))
    print_queue.put((0,))

    # TODO: consider encoding and decoding these structures if piping is slow
    central_regbuf = RegisterBuffer()
    grpdat = GroupingData()
    regbuf_queue.put(central_regbuf)

    handler_args = [
        (
            udp_sockets[i],
            tcp_socket,
            regbuf_queue,
            resp_queues[i],
            grpdat if i == 0 else False,
            incsort_handler_pipes_rem[i],
            main_handler_pipes_rem[i],
            max_sessions,
            subproc_ct,
            True if i == 0 else False,
            print_queue,
            _verbose
        )
        for i in range(subproc_ct)
    ]
    incsort_args = [
        (
            udp_sockets[i],
            tcp_socket,
            resp_queues[i],
            connect_log,
            connect_lock,
            incsort_handler_pipes_loc[i],
            incoming,
            incoming_lock
        )
        for i in range(subproc_ct)
    ]
    incbuf_args = [
        (udp_sockets[i], tcp_socket, incoming, buffer_size)
        for i in range(subproc_ct)
    ]

    handlers = [Process(target=handle_clients, args=handler_args[i]) for i in range(subproc_ct)]
    incsort_t = [Thread(target=main_incoming_sort, args=incsort_args[i]) for i in range(subproc_ct)]
    incbuf_t = [Thread(target=main_incoming, args=incbuf_args[i]) for i in range(subproc_ct)]

    for i in range(subproc_ct):
        incsort_t[i].start()
        handlers[i].start()
        incbuf_t[i].start()

    # optimization, avoids dict lookups
    connect_log_turnover = connect_log.turnover
    connect_lock_acquire = connect_lock.acquire
    connect_lock_release = connect_lock.release

    ip_turnover_ctr = 0
    verbose_turnover_ctr = 0
    prev_time = time()

    print('running...')
    while True:

        # -- drop stale connections periodically --

        new_time = time()
        delta_time = new_time - prev_time
        ip_turnover_ctr += delta_time
        verbose_turnover_ctr += delta_time
        prev_time = new_time
        if ip_turnover_ctr >= ip_turnover_update:
            # connect_lock_acquire()
            # dropped = connect_log_turnover()
            # connect_lock_release()
            # for pipe in main_handler_pipes_loc:
            #     pipe.send(dropped)
            ip_turnover_ctr = 0
        if _verbose and verbose_turnover_ctr >= verbose_print_time:
            print_key = print_queue.get()
            regbuf = regbuf_queue.get()
            print(regbuf)
            regbuf_queue.put(regbuf)
            print_queue.put(print_key)
            verbose_turnover_ctr = 0

# -----------------------------------------------------------------------------------:secondary proc

def handle_clients(
    udp_socket, 
    tcp_socket, 
    regbuf_queue,
    resp_queue,
    grpdat,
    client_pipe,
    drop_pipe, 
    max_sessions,
    subproc_ct,
    group_duty,
    print_queue,
    _verbose
):
    # TODO:
    # drop_list = drop_pipe.recv()
    regbuf_local = RegisterBuffer()
    main_cldata = [[CLData(), None] for _ in range(SES_MAX*subproc_ct)]
    if group_duty:
        grp_cldata = [[CLData(), None] for _ in range(SES_MAX)]
    else:
        grp_cldata = None

    # TODO: sessions proc updates; each name points to a list of clients that request to join
    sessions_hostnames = dict()
    regbuf_turnover_ctr = 0
    regbuf_turnover_time = 3
    grpdat_turnover_ctr = 0
    grpdat_turnover_time = 4
    verbose_turnover_ctr = 0
    verbose_turnover_time = 10
    prev_time = time()

    # TODO: switch back to having a registration & grouping process and two sesion processes

    # instantiating this twice before the first start() call so we can just use is_alive() without
    # a None check
    if group_duty:
        grouping_thread = Thread(
            target=grp_handle,
            args=(grpdat, regbuf_queue, grp_cldata, sessions_hostnames)
        )
    else:
        grouping_thread = None

    # TODO: (speed) static buffer size?
    incoming_clients = []
    buffer_incoming_clients = Thread(
        target=handler_incoming,
        args=(client_pipe, incoming_clients)
    )
    buffer_incoming_clients.start()

    while True:
        cld_i = 0
        new_time = time()
        delta_time = new_time - prev_time
        regbuf_turnover_ctr += delta_time
        verbose_turnover_ctr += delta_time
        prev_time = new_time

        # -- the first subprocess does grouping work regularly --
        # -- otherwise & others copy the local register buffer into the central registry --

        if group_duty:
            grpdat_turnover_ctr += delta_time
            if grpdat_turnover_ctr >= grpdat_turnover_time:
                if not grouping_thread.is_alive():
                    grouping_thread = Thread(
                        target=grp_handle,
                        args=(grpdat, regbuf_queue, grp_cldata, sessions_hostnames, delta_time)
                    )
                    grouping_thread.start()
                grpdat_turnover_ctr = 0

                resp_key = resp_queue.get()
                for cldata_tup in grp_cldata:
                    cldata = cldata_tup[0]
                    if cldata.status == STATUS_NONE:
                        break
                    udp_socket.sendto(pack_udp(cldata), cldata_tup[1])
                    cldata.status = STATUS_NONE
                    cldata_tup[1] = None
                resp_queue.put(resp_key)
        if regbuf_turnover_ctr >= regbuf_turnover_time and regbuf_local.client_ct > 0:
            # TODO: This should be elif unless grouping gets its own process
            regbuf_central = regbuf_queue.get()
            regbuf_copy_local_to_central(regbuf_local, regbuf_central)
            regbuf_queue.put(regbuf_central)
            regbuf_turnover_ctr = 0

        for i in range(len(incoming_clients)):
            client = incoming_clients[i]
            client_status = client.status

            # TODO: encode-decode with shared memory objects like Value and Array

            if client_status & STATUS_TRANSFER:
                pass
            elif client_status == STATUS_HOST_READY:
                pass
            elif client_status == STATUS_HOST_PREPARING:
                pass
            elif client_status == STATUS_CLIENT_WAITING:
                pass
            elif client_status == STATUS_CLIENT_JOINING:
                pass
            elif client_status & STATUS_REG_MASK:
                cld_i = regbuf_add_client_to_local(client, regbuf_local, main_cldata, cld_i)
            else: # STATUS_GROUPING
                # add to data structure handled by grouping process, pipe occasionally
                pass
        incoming_clients.clear()

        if _verbose and verbose_turnover_ctr > verbose_turnover_time:
            print_key = print_queue.get()
            print(grpdat)
            print_queue.put(print_key)
            verbose_turnover_ctr = 0

        resp_key = resp_queue.get()
        for i in range(cld_i):
            cldata_tup = main_cldata[i]
            cldata = cldata_tup[0]
            udp_socket.sendto(pack_udp(cldata), cldata_tup[1])
        resp_queue.put(resp_key)

# -------------------------------------------------------------------------------------:python entry

VA_HELP     = 0
VA_PORT     = 1
VA_VERBOSE  = 2
VA_SUBPROC  = 3

VERBOSE_UPDATE_TIME = 10

valid_argnames = (("-h", "--help"), ("-p", "--port"), ("-v", "--verbose"), ('-s', '--subproc'))
valid_argnames_info = (
    "see names and explanations of arguments",
    "specifies the first port on which the server will listen; remaining ports will follow sequentially",
    f"prints out connected clients every {VERBOSE_UPDATE_TIME} seconds",
    "specifies both the number of subprocesses and number of ports the server will run"
)

VALID_ARGS = \
"------------\n" + "".join([
    f"{valid_argnames[i][0]}, {valid_argnames[i][1]} :\t{valid_argnames_info[i]}\n"
    for i in range(len(valid_argnames))
]) + "------------\n"
ERRNAME_BAD_ARGNAME = """
------------
__main__(): ERROR: malformed arg name
example(1): python matchmaker.py 
(creates a udp matchmaking server with default settings)
example(2): python3 matchmaker.py --help
(see valid arguments, specifies python3, which may be necessary on linux)
------------
"""
ERRNAME_PORT_MALFORMED = """
------------
__main__(): ERROR: malformed port arg value
example(1): python3 matchmaker.py --port 7777
(creates a udp matchmaking server that listens on port 7777 and..., specifies python3)
------------
"""
ERRNAME_SUBPROC_MALFORMED = """
------------
__main__(): ERROR: malformed subproc arg value
example(1): python matchmaker.py --subproc 3
(creates a udp matchmaking server with three subprocesses, listening on 3 ports)
------------
"""
ERRNAME_SUBPROC_SMALL = """
------------
__main__(): ERROR: subproc arg value must be at least 1
example(1): python matchmaker.py --subproc 3
(creates a udp matchmaking server with three subprocesses, listening on 3 ports)
------------
"""


if __name__ == '__main__':
    with open('log.txt', 'w') as f:
        pass # overwriting previous log file

    # -- default args --
    verbose = False
    subprocess_ct = 3
    port = 7777

    arg_ct = len(argv)
    if arg_ct > 1:
        i = 1
        while True:
            if argv[i] in valid_argnames[VA_PORT]:
                i += 1
                if i >= arg_ct:
                    print(ERRNAME_PORT_MALFORMED)
                    exit(1)
                try:
                    port = int(argv[i])
                    i += 1
                except ValueError:
                    print(ERRNAME_PORT_MALFORMED)
                    exit(1)
            elif argv[i] in valid_argnames[VA_SUBPROC]:
                i += 1
                if i >= arg_ct:
                    print(ERRNAME_SUBPROC_MALFORMED)
                    exit(1)
                try:
                    subprocess_ct = int(argv[i])
                    assert subprocess_ct >= 1
                    i += 1
                except ValueError:
                    print(ERRNAME_SUBPROC_MALFORMED)
                    exit(1)
                except AssertionError:
                    print(ERRNAME_SUBPROC_SMALL)
                    exit(1)
            elif argv[i] in valid_argnames[VA_VERBOSE]:
                verbose = True
                i += 1
            elif argv[i] in valid_argnames[VA_HELP]:
                print(VALID_ARGS)
                i += 1
            else:
                print(ERRNAME_BAD_ARGNAME)
                exit(1)
            if i >= arg_ct:
                break

    main(verbose, subprocess_ct, port)
