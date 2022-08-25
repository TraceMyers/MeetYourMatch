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
        self.client_data = DEFAULT_CLDATA   # 468 (udp)
                                            # 508 total

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
        # NOTE: to make this one-way, other processes will have to do more sorting
        # take out check against local status
        # processes need a SMALL central record of who belongs where
        self.name = name
        self.status = status
        self.address = address
        self.latency = latency
        self.group_size = group_size


class GrpClient(Client):

    def __init__(self, client, index):
        super().__init__(client.name, client.address, client.status, 0, client.group_size)
        self.index = index
        self.avg_latency = 0
        self.avg_latency_ctr = 0

# -------------------------------------------------------------------------------------:handler data

class RegisterBuffer:

    __slots__ = ('clients', 'client_ct')
    def __init__(self):
        self.clients = {}
        self.client_ct = 0


class GroupingData:

    __slots__ = ('ungrouped_clients', 'client_ct', 'addresses', 'sessions', 'session_ct')
    def __init__(self):
        self.ungrouped_clients = []
        self.client_ct = 0
        self.addresses = set()
        self.sessions = []
        self.session_ct = 0


class SessionData:

    def __init__(self):
        pass


class Session:

    def __init__(self, host, client_max=2):
        # TODO: set client max
        # TODO: probably make a GrpSession w/out addresses
        self.host = host
        self.clients = []
        self.client_ct = 1
        self.client_max = client_max
        self.com = COM_STUN
        self.addresses = set() # used after grouping

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


def set_group_size(client): 
    client.group_size = unpack('<H', client.data[0:2])[0]

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
    grpdat_addresses_add = grpdat_addresses.add
    grpdat_client_ct = grpdat.client_ct
    grpdat_ungrouped_clients = grpdat.ungrouped_clients
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
            grpdat_ungrouped_clients.append(client)
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
            grp_cldata_basic_add(grp_cldata, cldata_ctr, STATUS_GROUPING, address)
            grpdat_sessions.append(Session(client))
            grpdat_session_ct += 1
        elif client_status == STATUS_REG_CLIENT_KNOWNHOST:
            hostname_index = \
                grp_hostname_index(grpdat_hosts, grpdat_session_ct, client_name)
            if hostname_index > 0:
                session = grpdat_sessions[hostname_index]
                if session.client_ct >= session.client_max:
                    cldata_ctr = \
                        grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_SESSION_MAXED, address)
                    continue
                # TODO: password check; just have default password None
                session.clients.append(client)
                session.client_ct += 1
                cldata_ctr = \
                    grp_cldata_basic_add(grp_cldata, cldata_ctr, STATUS_CLIENT_WAITING, address)
            else:
                join_request_list = get_session_jrq(session_hosts, client_name)
                if join_request_list is None:
                    cldata_ctr = \
                        grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_NO_SESSION, address)
                    continue
                join_request_list.append(client)
                cldata_ctr = grp_cldata_basic_add(grp_cldata, cldata_ctr, STATUS_GROUPING, address)
                continue
        grpdat_addresses_add(address)
        grpdat_client_ct += 1

    regbuf_clients.clear()
    grpdat.client_ct = grpdat_client_ct
    grpdat.session_ct = grpdat_session_ct
    return cldata_ctr


def grp_cldata_basic_add(cldata_list, cldata_i, status, address):
    cldata_tup = cldata_list[cldata_i]
    cldata_tup[0].status = status
    cldata_tup[1] = address
    return cldata_i + 1


def grp_cldata_iplist_add(cldata_list, cldata_i, status, address, iplist):
    cldata_tup = cldata_list[cldata_i]
    cldata = cldata_tup[0]
    cldata.status = status
    ip_ct = len(iplist)
    ip_bytes = b''.join([bytes([int(item) for item in ip_str.split('.')]) for ip_str in iplist])
    byte_ct = ip_ct * 4
    cldata.client_data[:byte_ct] = pack(f'{ip_ct}I', ip_bytes)
    cldata_tup[1] = address
    return cldata_i + 1


def get_session_jrq(hostnames, name):
    if name in hostnames:
        return hostnames[name]
    return None


def grp_hostname_index(hostnames, session_ct, name):
    for i in range(session_ct):
        if hostnames[i] == name:
            return i
    return -1


# --------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------:thread entry points
# --------------------------------------------------------------------------------------------------

def grp_handle(grpdat, regbuf_queue, grp_cldata, sessions_hostnames):
    cldata_ctr = 0
    regbuf = regbuf_queue.get()
    if regbuf.client_ct > 0:
        regbuf_clients = regbuf.clients
        regbuf_client_keys = regbuf_clients.keys()
        # avoiding piping a list we can just decompress from existing data here
        grpdat_sessions = grpdat.sessions
        grpdat_hostnames = [session.host.name for session in grpdat_sessions]
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

    # TODO: ping process; go through all ungrouped clients and all grpdat sessions
    #       and create revolving, chunked ping groups. each host gets a list of clients to
    #       ping until they get one response, then just return each incoming msg;
    #       each client gets a list of hosts to ping until they record a good
    #       measure of average latency. include timeout.
    #       TURN must be used for any client-host pair with no result
    #       hosts must also report whether or not any connections were made, which
    #       would mark them as STUN-compatible if true

    # for now, just fill every session with ungrouped clients and hurry them over to sessiondata
    grpdat_session_ct = grpdat.session_ct
    grpdat_ungrouped_clients = grpdat.ungrouped_clients
    ungrouped_clients_len = len(grpdat_ungrouped_clients)
    if grpdat_session_ct == 0:
        out_of_room = True
    else:
        session_i = 0
        session = grpdat_sessions[session_i]
        session_client_max = session.client_max
        session_clients = session.clients
        out_of_room = False
    for i in range(ungrouped_clients_len):
        if out_of_room:
            client = grpdat_ungrouped_clients[i]
            cldata_ctr = \
                grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_INTAKE_MAXED, client.address)
        elif session.client_ct < session_client_max:
            client = grpdat_ungrouped_clients.pop(i)
            session_clients.append(client)
            session.client_ct += 1
            host_address = session.host.address
            iplists = ([host_address[0], ], [client.address[0], ])
            cldata_ctr = grp_cldata_iplist_add(
                grp_cldata,
                cldata_ctr,
                STATUS_GROUPING,
                client.address,
                iplists[0]
            )
            cldata_ctr = grp_cldata_iplist_add(
                grp_cldata,
                cldata_ctr,
                STATUS_GROUPING,
                host_address,
                iplists[1]
            )
        else:
            session_i += 1
            if session_i >= grpdat_session_ct:
                cldata_ctr = \
                    grp_cldata_basic_add(grp_cldata, cldata_ctr, ERROR_INTAKE_MAXED, client.address)
                out_of_room = True
                continue
            session = grpdat_sessions[session_i]
            session_client_max = session.client_max
            session_clients = session.clients

    grp_cldata[cldata_ctr][0].status = STATUS_NONE


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
    # the process, including in multiple sessions. solution: just drop them when the intake client 
    # gets to session and refuse their connection for a while.
    # TODO: forget one-way data. subprocesses are mostly session data agnostic, so there is no
    # reason to shove all of that through the pipes. Just have a sender thread. main process needs
    # more to do anyway

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
        connect_lock_acquire()
        error = connect_log_log_ip(ip_address)
        connect_lock_release()
        if error > 0:
            error_cldata.status |= error
            error_cldata.time_stamp = time()
            key = resp_queue_get()
            udp_socket_sendto(pack_udp(error_cldata), ip_address)
            resp_queue_put(key)
            continue

        cldata_unpacket_udp(msg[0])

        # TODO: handle admin key and flags on cldata

        remote_status = cldata.status

        if remote_status & STATUS_REG_MASK:
            client = Client(cldata.name, ip_address, remote_status)
            connect_log.ip_to_client[ip_address] = client # atomic
            handler_pipe_send(client)
        else:
            connect_lock_acquire()
            client = connect_log_get_client(ip_address)
            connect_lock_release()
            if client is None:
                error_cldata.status |= ERROR_NO_CLIENT
                error_cldata.time_stamp = time()
                key = resp_queue_get()
                udp_socket_sendto(pack_udp(error_cldata), ip_address)
                resp_queue_put(key)
            elif remote_status <= STATUS_TRANSFER_AGAIN:
                if remote_status == STATUS_REG_HOST or remote_status == STATUS_REG_HOST_KNOWNHOST:
                    set_group_size(client)
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
    # TODO: have multiple sockets + multiple threads so the server doesn't lag with every bad packet
    #       and/or figure out how to do my own exception handling that isn't so catastrophic
    udp_socket_recvfrom = udp_socket.recvfrom

    while True:
        try:
            incoming.append(udp_socket_recvfrom(buffer_size))
        except WindowsError: 
            # probably incoming package too big; ignore
            # TODO: get more details
            continue
        except Exception as e:
            print('ERROR turnserver.py main_incoming():: passed exception from udp_socket_recvfrom()')
            print(e)
            continue


def handler_incoming(client_pipe, incoming):
    incoming_append = incoming.append
    client_pipe_recv = client_pipe.recv
    while True:
        try:
            incoming_append(client_pipe_recv())
        except Exception as e:
            print('ERROR turnserver.py handler_incoming():: passed exception from client_pipe_recv()')
            print(e)
            continue


# --------------------------------------------------------------------------------------------------
# -----------------------------------------------------------------------------:process entry points
# --------------------------------------------------------------------------------------------------

def main():
    udp_ports = [7777, 7778, 7779]
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

    port_str = ', '.join(udp_ports)
    # NOTE: currently just using udp
    while True:
        try:
            print(f'Meet Your Match server loading on {local_ip}:{port_str}')
            main_proc(tcp_socket, udp_sockets, udp_bufsize, socket_ct)
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

def main_proc(tcp_socket, udp_sockets, buffer_size, udp_socket_ct):
    subproc_ct = udp_socket_ct
    ip_turnover_time = 15
    ip_turnover_update = 5
    max_poll_rate = 0.099
    incoming = deque()
    max_sessions = 100

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
    connect_lock = Lock()
    incoming_lock = Lock()
    for queue in resp_queues:
        queue.put((0,))

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
            True if i == 0 else False
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
    ip_turnover_ctr = 0

    # optimization, avoids dict lookups
    connect_log_turnover = connect_log.turnover
    connect_lock_acquire = connect_lock.acquire
    connect_lock_release = connect_lock.release

    prev_time = time()

    print('running...')
    while True:

        # -- drop stale connections periodically --

        new_time = time()
        ip_turnover_ctr += new_time - prev_time
        prev_time = new_time
        if ip_turnover_ctr >= ip_turnover_update:
            connect_lock_acquire()
            dropped = connect_log_turnover()
            connect_lock_release()
            for pipe in main_handler_pipes_loc:
                pipe.send(dropped)
            ip_turnover_ctr = 0


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
    group_duty
):
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
        grpdat_turnover_ctr += delta_time
        prev_time = new_time

        # -- the first subprocess does grouping work regularly --
        # -- otherwise & others copy the local register buffer into the central registry --

        if group_duty and grpdat_turnover_ctr >= grpdat_turnover_time:
            if not grouping_thread.is_alive():
                grouping_thread = Thread(
                    target=grp_handle,
                    args=(grpdat, regbuf_queue, grp_cldata, sessions_hostnames)
                )
                grouping_thread.start()
            grpdat_turnover_ctr = 0

            resp_key = resp_queue.get()
            for cldata_tup in grp_cldata:
                cldata = cldata_tup[0]
                if cldata.status == STATUS_NONE:
                    break
                udp_socket.sendto(pack_udp(cldata), cldata_tup[1])
            resp_queue.put(resp_key)

        elif regbuf_turnover_ctr >= regbuf_turnover_time and regbuf_local.client_ct > 0:
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

        resp_key = resp_queue.get()
        for i in range(cld_i):
            cldata_tup = main_cldata[i]
            cldata = cldata_tup[0]
            udp_socket.sendto(pack_udp(cldata), cldata_tup[1])
        resp_queue.put(resp_key)


if __name__ == '__main__':
    # interpreter needs to read EOF before starting new processes, so while it looks silly to just
    # call the entry point nakedly, it's necessary
    main()
