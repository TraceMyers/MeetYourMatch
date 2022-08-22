from multiprocessing import Process, Pipe, active_children
import multiprocessing # for Manager()
from threading import Thread, Lock
from sys import argv
from time import time
import socket
from struct import pack, unpack
import traceback


STATUS_NONE                 = 0x00
STATUS_REG_CLIENT           = 0x01
STATUS_REG_HOST             = 0x02
STATUS_GROUPING             = 0x03
STATUS_SESSION_PREPARING    = 0x04
STATUS_SESSION_READY        = 0x05
STATUS_TRANSFER             = 0x08 
STATUS_TRANSFER_NO_DATA     = 0x09 
STATUS_TRANSFER_AGAIN       = 0x0a 

ERROR_MASK                  = 0xf0
ERROR_DATA_FORMAT           = 0x10
ERROR_REGISTER_FAIL         = 0x20
ERROR_INTAKE_MAXED          = 0x30
ERROR_TRANSFERS_MAXED       = 0x40
ERROR_NO_SESSION            = 0x50
ERROR_NO_CLIENT             = 0x60
ERROR_NO_PARTNER            = 0x70
ERROR_BAD_STATUS            = 0x80
ERROR_FAST_POLL_RATE        = 0x90
ERROR_IP_LOG_MAXED          = 0xa0
ERROR_CLIENT_LOG_MAXED      = 0xb0
ERROR_NO_HOST               = 0xc0

SORT_HOST = 0
SORT_CLNT = 1
SORT_PAIR = 2
SORT_INIT = 3
SORT_REDY = 4
SORT_TFER = 5
SORT_KICK = 6

ROLE_CLIENT = 0
ROLE_HOST   = 1
ROLE_NONE   = 2

# always ok
CL_NAME_IS_HOST         = 0x0001
CL_PRE_GROUPED          = 0x0002
CL_ENCRYPTED            = 0x0004
# admin
CL_ADMIN                = 0x0100
CL_UNLOCK_POLL_RATE     = 0x0200 | CL_ADMIN
CL_ONLY_MY_SESSION      = 0x0400 | CL_ADMIN
CL_VALIDATE_ALL_TFERS   = 0x0800 | CL_ADMIN
CL_SET_TCP              = 0x1000 | CL_ADMIN
CL_SET_UDP              = 0x2000 | CL_ADMIN
CL_LAT_NEAREST          = 0x4000 | CL_ADMIN
CL_RESTORE_DEFAULTS     = 0x8000 | CL_ADMIN

KEY_CT = 200
MAX_IP = KEY_CT * 2 # maximum number of clients in session
GAP = b'\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0'


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
        elif len(self.ip_log.keys()) >= MAX_IP:
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
                del ip_log[key]
                if key in ip_to_client:
                    del ip_to_client[key]
        return dropped_ips

    def forget_client(self, ip_address):
        del self.ip_log[ip_address]
        del self.ip_to_client[ip_address]


class Client:
    """
    Data passed from main process down pipes once sorted. Used for pre-session work.
    """

    __slots__ = ('name', 'status', 'address', 'latency')
    def __init__(self, name, address):
        # NOTE: to make this one-way, other processes will have to do more sorting
        # take out check against local status
        # processes need a SMALL central record of who belongs where
        self.name = name
        self.status = STATUS_NONE
        self.address = address
        self.latency = 0.0


class SessClient(Client):
    """
    Data passed from main process down pipes once sorted. Used in sessions.
    """

    __slots__ = ('data', )
    def __init__(self, name, address):
        super().__init__(name, address)
        self.data = None


class LocalClient:

    def __init__(self):
        pass


class GroupingData:

    def __init__(self):
        self.clients = [None for i in range(KEY_CT)]
        self.client_ct = 0


class SessionData:

    def __init__(self):
        pass


class CLData:

    __slots__ = (
        'status', 'error', 'flags', 'time_stamp', 'name', 'admin_key', 'client_data', 'local_i'
    )
    def __init__(self):
        self.status = None
        self.error = 0
        self.flags = 0
        self.time_stamp = 0
        self.name = 'JoeErrname'
        self.admin_key = None
        self.client_data = b'\x00\x00\x00\x00' * 111

    def unpacket_udp(self, data):
        # self.status = unpack('<B', data[0]) # no need to pipe
        # self.error = unpack('<B', data[1]) # no need to pipe
        # self.flags = unpack('<H', data[2:4]) # no need to pipe
        # self.time_stamp = unpack('<f', data[4:8]) # no need to pipe
        # self.name = data[8:48].decode() # copy to client
        # self.admin_key = unpack('<16s', data[48:64])[0].decode() # no need to pipe
        # self.client_data = data[64:] # copy to client
        self.status, self.error, self.flags, self.time_stamp, \
        self.name, self.admin_key, self.client_data = unpack('<2BHf10s16s444s', data)


def get_timestamp():
    return time.time() * 1000 % 10000000 # milliseconds for 32 bits


def pack_udp(cl_data):
    return pack(
        f'<2BHf10s16s444s',
        cl_data.status, cl_data.error, cl_data.flags, cl_data.time_stamp, 
        bytes(cl_data.name, 'utf-8'), GAP, cl_data.client_data
    )


def pack_tcp(cl_data):
    return pack(
        f'<2BHf10s16s1316s',
        cl_data.status, cl_data.error, cl_data.flags, cl_data.time_stamp, 
        bytes(cl_data.name, 'utf-8'), GAP, cl_data.client_data
    )


def intake_unassign_clients(clients, from_struct):
    pass


def intake_assign_clients(clients, to_struct):
    """
    moves client into an intake struct
    intake process includes registration, pairing and session init
    """
    # struct_client_ct = to_struct.client_data.client_
    # struct_clients = to_struct.client_data.clients
    # if to_struct.client_data.client_ct >= 
    # if struct_key >= KEY_CT:
    #     return False, ERROR_INTAKE_MAXED
    # for client in clients:
    #     struct_clients[struct_key] = client
    #     client.local_key = struct_key
    #     while struct_clients[struct_key] != None:
    #         struct_key += 1
    #         if struct_key >= KEY_CT:
    #             to_struct.client_data.key_ct = struct_key
    #             return False, ERROR_INTAKE_MAXED
    # to_struct.client_data.key_ct = struct_key
    # return True, 0
    pass


def register_clients():
    pass


def pair_clients():
    # subprocess keeps running until no more clients can be paired
    # called on regular interval (every 10 secs or so)
    # factors latency
    pass


def session_init():
    pass


def handle_clients(
    udp_socket, 
    tcp_socket, 
    resp_queue, 
    data_queue, 
    client_pipe, 
    drop_pipe, 
    max_sessions
):
    # client_data = client_pipe.recv()
    # drop_list = drop_pipe.recv()

    while True:
        # become grouping process if needed
        #   take register buffer and add all to grouping
        #   group clients until no longer possible, return

        client = client_pipe.recv()
        client_status = client.status

        if client_status == STATUS_REG_CLIENT or client_status == STATUS_REG_HOST:
            # check if client in register buffer
            # place in buffer if not
            pass
        elif client_status == STATUS_GROUPING:
            # check on grouping process status
            pass
        elif client_status
        data = data_queue.get()
        # TODO: decode


def incoming_sort(
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
    #TODO: remove Client and create SessClient when transitioning to session

    error_cldata = CLData()
    error_cldata.error = ERROR_BAD_STATUS
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
            error_cldata.error = error
            error_cldata.time_stamp = time()
            key = resp_queue_get()
            udp_socket_sendto(pack_udp(error_cldata), ip_address)
            resp_queue_put(key)
            continue

        cldata_unpacket_udp(msg[0])

        # TODO: handle admin key and flags on cldata

        remote_status = cldata.remote_status

        if remote_status == STATUS_NONE:
            client = Client(cldata.name, ip_address)
            if cldata.flags & CL_NAME_IS_HOST:
                client.status = STATUS_REG_HOST
            else:
                client.status = STATUS_REG_CLIENT
            connect_log.ip_to_client[ip_address] = client # atomic
            handler_pipe_send(client)
        else:
            connect_lock_acquire()
            client = connect_log_get_client(ip_address)
            connect_lock_release()
            if client is None:
                error_cldata.error = ERROR_NO_CLIENT
                error_cldata.time_stamp = time()
                key = resp_queue_get()
                udp_socket_sendto(pack_udp(error_cldata), ip_address)
                resp_queue_put(key)
                continue
            if remote_status <= STATUS_TRANSFER_AGAIN:
                client.latency = time() - cldata.time_stamp
                client.status = remote_status
                handler_pipe_send(client)
            else:
                error_cldata.error = ERROR_BAD_STATUS
                error_cldata.time_stamp = time()
                key = resp_queue_get()
                udp_socket_sendto(pack_udp(error_cldata), ip_address)
                resp_queue_put(key)


def incoming_buffer(
    udp_socket, 
    tcp_socket,
    incoming,
    buffer_size
):
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


def run_head():
    udp_port = 7777
    udp_bufsize = 576
    tcp_port = 17777
    tcp_bufsize = 1500
    local_ip = '192.168.0.203'
    buffer_size = udp_bufsize
    subproc_ct = 3
    ip_turnover_time = 15
    ip_turnover_update = 5
    max_poll_rate = 0.099
    incoming = []
    max_sessions = 100

    connect_log = ConnectionLog(max_poll_rate, ip_turnover_time)

    udp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    udp_socket.bind((local_ip, udp_port))
    tcp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
    tcp_socket.bind((local_ip, tcp_port))

    incsort_handler_pipes = (Pipe() for _ in range(subproc_ct))
    incsort_handler_pipes_rem = [pipe[0] for pipe in incsort_handler_pipes]
    incsort_handler_pipes_loc = [pipe[1] for pipe in incsort_handler_pipes]
    main_handler_pipes = (Pipe() for _ in range(subproc_ct))
    main_handler_pipes_rem = [pipe[0] for pipe in main_handler_pipes]
    main_handler_pipes_loc = [pipe[1] for pipe in main_handler_pipes]
    resp_queue = multiprocessing.Manager().Queue() # apparently faster than multiprocessing.Queue
    handler_data_queue = multiprocessing.Manager().Queue()
    resp_queue.put((1,))
    connect_lock = Lock()
    incoming_lock = Lock()

    # TODO: consider encoding and decoding these structures if this is slow
    handler_data = [GroupingData()]
    handler_data.append([SessionData() for _ in range(max_sessions)])
    handler_data_queue.put(handler_data)

    handler_args = (
        (
            udp_socket,
            tcp_socket,
            resp_queue,
            handler_data_queue,
            incsort_handler_pipes_rem[i], 
            main_handler_pipes_rem[i],
            max_sessions
        ) 
        for i in range(subproc_ct)
    )
    incsort_args = [
        (
            udp_socket, 
            tcp_socket,
            resp_queue,
            connect_log, 
            connect_lock,
            incsort_handler_pipes_loc[i],
            incoming,
            incoming_lock
        ) 
        for i in range(subproc_ct)
    ]
    incbuf_args = (udp_socket, tcp_socket, incoming, buffer_size)

    handlers = [Process(target=handle_clients, args=handler_args[i]) for i in range(subproc_ct)]
    incsort_t = [Thread(target=incoming_sort, args=incsort_args[i]) for i in range(subproc_ct)]
    incbuf_t = Thread(target=incoming_buffer, args=incbuf_args)

    try:
        incbuf_t.start()
        for i in range(subproc_ct):
            incsort_t[i].start()
            handlers[i].start()
        ip_turnover_ctr = 0

        # optimization, avoids dict lookups
        connect_log_turnover = connect_log.turnover
        connect_lock_acquire = connect_lock.acquire
        connect_lock_release = connect_lock.release
        pipe_send = pipe.send

        prev_time = time()

        print(f'UDP TURN server running on {local_ip}:{udp_port}')
        while True:

            # -- drop stale connections periodically --
            
            new_time = time()
            ip_turnover_ctr += new_time - prev_time
            if ip_turnover_ctr >= ip_turnover_update:
                connect_lock_acquire()
                dropped = connect_log_turnover()
                connect_lock_release()
                for pipe in main_handler_pipes_loc:
                    pipe_send(dropped)
                ip_turnover_ctr = 0
            prev_time = new_time

    except KeyboardInterrupt:
        for c in active_children():
            c.kill()
    except:
        traceback.print_exc()
        for c in active_children():
            c.kill()


if __name__ == '__main__':
    run_head()
