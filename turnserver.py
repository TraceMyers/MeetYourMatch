from multiprocessing import Process, Pipe, active_children, Manager
from threading import Thread, Lock
from sys import argv
from time import time
import socket
from struct import pack, unpack
import traceback

# TODO: name registering so that users can always expect to use the same name


STATUS_NONE                 = 0x00
STATUS_REG_CLIENT           = 0x01
STATUS_REG_HOST             = 0x02
STATUS_GROUPING             = 0x03
STATUS_HOST_PREPARING       = 0x04
STATUS_HOST_READY           = 0x05
STATUS_CLIENT_WAITING       = 0x06
STATUS_CLIENT_JOINING       = 0x07
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

ROLE_CLIENT = 0
ROLE_HOST   = 1
ROLE_NONE   = 2

# client options
CL_NAME_IS_HOST         = 0x0001    # if also PRE_GROUPED, this client will host and others will join 
                                    # by host name. else, requests to host in randomly matched session
CL_PRE_GROUPED          = 0x0002    # only match me
CL_ENCRYPTED            = 0x0004    # passed along to inform all clients in session that some or all
                                    # data is encrypted; clients figure out the rest
# group options
CL_RELAY_ONLY           = 0x0008    # session starts without preparing, waiting, joining, etc
# admin options
CL_ADMIN                = 0x0100
CL_UNLOCK_POLL_RATE     = 0x0200 | CL_ADMIN # unlock poll rate lock for this client
CL_ONLY_MY_SESSION      = 0x0400 | CL_ADMIN # dump/refuse any client without provided password
CL_RESTORE_DEFAULTS     = 0x0800 | CL_ADMIN # turn off anything changed by flags (can be combined
                                            # with other changes)
CL_MULTI_SESSION        = 0x1000 | CL_ADMIN # allow this client to enter mutliple sessions

KEY_CT = 200
MAX_IP = KEY_CT * 2 # maximum number of clients in session
MAX_GROUPSIZE = 16 # tentative
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
    def __init__(self, name, address, status=STATUS_NONE, latency=0.0):
        # NOTE: to make this one-way, other processes will have to do more sorting
        # take out check against local status
        # processes need a SMALL central record of who belongs where
        self.name = name
        self.status = status
        self.address = address
        self.latency = latency


class SessClient(Client):
    """
    Data passed from main process down pipes once sorted. Used in sessions.
    """

    __slots__ = ('data', )
    def __init__(self, name, address):
        super().__init__(name, address)
        self.data = None


class GrpClient(Client):

    def __init__(self, client):
        super().__init__(client.name, client.address, client.status, client.latency)
        self.client_index = -1
        self.group_index = -1
        self.max_groupsize = 2 # changed only by host to be < MAX_GROUPSIZE


class RegisterBuffer:

    __slots__ = ('clients', 'client_ct')
    def __init__(self):
        self.clients = {}
        self.client_ct = 0


class GroupingData:

    __slots__ = ('clients', 'client_ct')
    def __init__(self):
        self.ungrouped_clients = [None for _ in range(KEY_CT)]
        self.client_ct = 0
        self.addresses = set()
        self.groups = []


class SessionData:

    def __init__(self):
        pass


class CLData:

    __slots__ = (
        'status', 'error', 'flags', 'time_stamp', 'name', 'admin_key', 'client_data'
    )
    def __init__(self):
        self.status = STATUS_NONE
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
        self.name = self.name.decode()
        self.admin_key = self.admin_key.decode()


def get_timestamp():
    return time.time() * 1000 % 10000000 # milliseconds for 32 bits


def pack_udp(cl_data):
    global GAP
    return pack(
        f'<2BHf10s16s444s',
        cl_data.status, cl_data.error, cl_data.flags, cl_data.time_stamp, 
        bytes(cl_data.name, 'utf-8'), GAP, cl_data.client_data
    )


def pack_tcp(cl_data):
    global GAP
    return pack(
        f'<2BHf10s16s1316s',
        cl_data.status, cl_data.error, cl_data.flags, cl_data.time_stamp, 
        bytes(cl_data.name, 'utf-8'), GAP, cl_data.client_data
    )


def regbuf_add_client_to_local(client, register_buffer):
    buf_client_ct = register_buffer.client_ct
    client_address = client.address
    buf_clients = register_buffer.clients
    if buf_client_ct >= KEY_CT:
        return ERROR_INTAKE_MAXED
    elif client_address in buf_clients:
        return STATUS_NONE 
    buf_clients[client_address] = client
    register_buffer.client_ct += 1
    return STATUS_NONE


def regbuf_copy_local_to_central(local, central):
    local_keys = local.clients.keys()
    central_clients = central.clients
    local_clients = local.clients
    for address in local_keys():
        if address not in central_clients:
            central_clients[address] = local_clients[address]
    local_clients.clear()


def grpdat_merge_regbuf(grpdat, regbuf, cldata_list):
    regbuf_clients = regbuf.clients
    regbuf_client_keys = regbuf_clients.keys()
    grpdat_addresses = grpdat.addresses
    grpdat_addresses_add = grpdat_addresses.add
    grpdat_client_ct = grpdat.client_ct
    grpdat_ungrouped_clients = grpdat.ungrouped_clients
    cldata_ctr = 0
    for address in regbuf_client_keys:
        if address in grpdat_addresses:
            continue
        elif grpdat_client_ct >= KEY_CT:
            cldata_list[cldata_ctr].error = ERROR_INTAKE_MAXED
        grpdat_addresses_add(address)
        grpdat_ungrouped_clients[grpdat_client_ct] = regbuf_clients[address]
        grpdat_client_ct += 1
    regbuf_clients.clear()
    regbuf.client_ct = 0
    grpdat.client_ct = grpdat_client_ct
    cldata_list[cldata_ctr].error = STATUS_NONE # marks end


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
    regbuf_queue,
    grpdat_queue,
    resp_queue, 
    client_pipe, 
    drop_pipe, 
    max_sessions,
    subproc_ct
):
    # drop_list = drop_pipe.recv()
    regbuf_local = RegisterBuffer()
    cldata_list = [CLData() for _ in range(KEY_CT*subproc_ct)]

    regbuf_turnover_ctr = 0
    regbuf_turnover_time = 3
    grpdat_turnover_ctr = 0
    grpdat_turnover_time = 4
    prev_time = time()

    while True:
        new_time = time()
        regbuf_turnover_ctr += new_time - prev_time
        grpdat_turnover_ctr += new_time - prev_time
        prev_time = new_time

        # -- one process draws the short straw to do grouping work --

        if grpdat_turnover_ctr >= grpdat_turnover_time:
            # I see no other solution than eating the exception here. checking for empty
            # will reduce the number of exceptions thrown, but it's still not guaranteed to have the
            # item on the next instruction. I don't want any processes specializing, so I'm stuck
            # with this. Alternatively, this could use something I'm calling a 'straw gate', wherein
            # processes draw from shared memory to see who gets the short straw, but that seems
            # unnecessary.
            if not grpdat_queue.empty():
                try:
                    grpdat = grpdat_queue.get_nowait()
                    regbuf_central = regbuf_queue.get()
                    grpdat_merge_regbuf(grpdat, regbuf_central, cldata_list)
                except:
                    pass
        # become grouping process if needed
        #   take central register buffer and add all to grouping
        #   group clients until no longer possible, return

        # -- copy the local register buffer into the central registry --

        if regbuf_turnover_ctr >= regbuf_turnover_time and regbuf_local.client_ct > 0:
            regbuf_central = regbuf_queue.get()
            status = regbuf_copy_local_to_central(regbuf_local, regbuf_central)
            regbuf_queue.put(regbuf_central)
            regbuf_turnover_ctr = 0

        client = client_pipe.recv()
        client_status = client.status

        # data = data_queue.get()
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
        elif client_status == STATUS_REG_CLIENT or client_status == STATUS_REG_HOST:
            status = regbuf_add_client_to_local(client, regbuf_local)
            if status & ERROR_MASK:
                # return error
                pass
        else: # STATUS_GROUPING
            # check on grouping process status
            pass


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
    #TODO: rn this allows for a user to create multiple client entries throughout
    # the process, including in multiple sessions. solution: just drop them when the intake client 
    # gets to session and refuse their connection for a while.
    #TODO: make sure name not in use

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
            elif remote_status <= STATUS_TRANSFER_AGAIN:
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
    multi_manager = Manager()
    resp_queue = multi_manager.Queue() # apparently faster than multiprocessing.Queue
    regbuf_queue = multi_manager.Queue()
    grpdat_queue = multi_manager.Queue()
    resp_queue.put((0,))
    connect_lock = Lock()
    incoming_lock = Lock()

    # TODO: consider encoding and decoding these structures if this is slow
    central_regbuf = RegisterBuffer()
    central_grpdat = GroupingData()
    regbuf_queue.put(central_regbuf)
    grpdat_queue.put(central_grpdat)

    handler_args = (
        (
            udp_socket,
            tcp_socket,
            resp_queue,
            incsort_handler_pipes_rem[i], 
            main_handler_pipes_rem[i],
            max_sessions,
            subproc_ct
        ) 
        for i in range(subproc_ct)
    )
    incsort_args = [
        (
            udp_socket, 
            tcp_socket,
            regbuf_queue,
            grpdat_queue,
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
            prev_time = new_time
            if ip_turnover_ctr >= ip_turnover_update:
                connect_lock_acquire()
                dropped = connect_log_turnover()
                connect_lock_release()
                for pipe in main_handler_pipes_loc:
                    pipe_send(dropped)
                ip_turnover_ctr = 0

    except KeyboardInterrupt:
        for c in active_children():
            c.kill()
    except:
        traceback.print_exc()
        for c in active_children():
            c.kill()


if __name__ == '__main__':
    run_head()
