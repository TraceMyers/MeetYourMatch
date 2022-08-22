from multiprocessing import Process, Pipe, active_children
import multiprocessing # for Manager()
from threading import Thread, Lock
from sys import argv
from time import time
import socket
from struct import pack, unpack
import traceback


STATUS_MASK                 = 0x0f
STATUS_NONE                 = 0x00
STATUS_NET_TEST             = 0x01
STATUS_GROUPING             = 0x02
STATUS_SESSION_PREPARING    = 0x03
STATUS_SESSION_READY        = 0x04
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
ERROR_CLIENT_STATE_BEHIND   = 0x80 
ERROR_CLIENT_STATE_AHEAD    = 0x90
ERROR_BAD_STATUS            = 0xa0
ERROR_FAST_POLL_RATE        = 0xb0
ERROR_IP_LOG_MAXED          = 0xc0
ERROR_CLIENT_LOG_MAXED      = 0xd0
ERROR_NO_HOST               = 0xe0

SORT_REGI = 0
SORT_PAIR = 1
SORT_INIT = 2
SORT_REDY = 3
SORT_TFER = 4
SORT_KICK = 5

ROLE_CLIENT = 0
ROLE_HOST   = 1
ROLE_NONE   = 2

NO_CLDATA_I = 1

# always ok
CL_NAME_IS_HOST         = 0x0001
CL_PRE_GROUPED          = 0x0002
# admin
CL_ADMIN                = 0x0100
CL_UNLOCK_POLL_RATE     = 0x0200 | CL_ADMIN
CL_ONLY_MY_SESSION      = 0x0400 | CL_ADMIN
CL_VALIDATE_ALL_TFERS   = 0x0600 | CL_ADMIN
CL_SET_TCP              = 0x0800 | CL_ADMIN
CL_SET_UDP              = 0x0a00 | CL_ADMIN
CL_RESTORE_DEFAULTS     = 0x0c00 | CL_ADMIN

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
                # refuse connection, don't change log value
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

    __slots__ = (
        'name', 'address', 'local_key', 'partner_key', 'local_status', 'remote_status', 'in_data',
        'prev_time_stamp', 'latency', 'lat_ctr'
    )
    def __init__(self, name, address):
        self.name = name
        self.address = address
        self.local_key = -1
        self.partner_key = None
        self.local_status = STATUS_NONE
        self.remote_status = STATUS_NONE
        self.in_data = None
        self.latency = [0.2, 0.2, 0.2]
        self.lat_ctr = 0

    def update_latency(self, time_stamp):
        self.latency[self.lat_ctr] = time() - time_stamp
        self.lat_ctr += 1
        if self.lat_ctr == 3:
            self.lat_ctr = 0


class PairingData:

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
        self.local_i = -1

    def unpacket(self, data):
        self.status = unpack('<B', data[0])
        self.error = unpack('<B', data[1])
        self.flags = unpack('<H', data[2:4])
        self.time_stamp = unpack('<f', data[4:8])
        self.name = data[8:48].decode()
        self.admin_key = unpack('<16s', data[48:64])[0].decode()
        self.client_data = data[64:]


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


def proc_entry(pipe, reponses, is_handler):
    # TODO: this is wrong, would instantiate separately. pass them in instead
    # regi_data = Registry()
    # pair_data = PairingData()
    # sint_data = SessionInitData()
    # sess_data = SessionData()
    pass


def handle_clients(client_pipe, drop_pipe, responses):
    # TODO: lock function calls so access to their data structures
    client_data = client_pipe.recv()
    drop_list = drop_pipe.recv()
    pass


def receive_clients(
    udp_socket, 
    connect_log, 
    handler_pipes,
    responses,
    cldata_t,
    connect_lock,
    buffer_size,
    subproc_ct
):
    """
    read socket messages, parse sorting data and pipe sorted data to handler processes
    """
    pipe_i = -1

    # optimization
    udp_socket_recvfrom = udp_socket.recvfrom
    connect_log_log_ip = connect_log.log_ip
    connect_log_get_client = connect_log.get_client
    connect_lock_acquire = connect_lock.acquire
    connect_lock_release = connect_lock.release
    responses_put = responses.put

    # -- main process, secondary thread loop --

    while True:
        try:
            msg = udp_socket_recvfrom(buffer_size)
            
        except WindowsError: 
            # probably incoming package too big; ignore
            # TODO: get more details
            continue

        # -- log connection and refuse if log maxed or if client polling too often --

        ip_address = msg[1]
        connect_lock_acquire()
        error = connect_log_log_ip(ip_address)
        connect_lock_release()
        if error > 0:
            responses_put((error, ip_address, None))
            continue

        # -- get a cldata struct --

        cldata = None
        for i in range(len(cldata_t)):
            if cldata_avail[i]:
                cldata = cldata_t[i]
                cldata_avail[i] = False
                break
        if cldata is None:
            print(
                'ERROR recieve_clients(): cldata not available due to poor multithreading.'
                ' dropping packet.'
            )
            continue

        cldata.unpacket(msg[0])

        # TODO: handle admin key and flags on cldata

        remote_status = cldata.remote_status

        # -- verify valid client status and sort -- 

        pipe_i += 1
        if pipe_i >= subproc_ct:
            pipe_i = 0
        if remote_status == STATUS_NONE:
            c = Client(name=cldata.name, address=ip_address)
            handler_pipes[pipe_i].send((c, cldata, SORT_REGI))
        else:
            connect_lock_acquire()
            client = connect_log_get_client(ip_address)
            connect_lock_release()
            if client is None:
                responses_put((ERROR_NO_CLIENT, ip_address, None, NO_CLDATA_I))
                continue
            client.update_latency(cldata.time_stamp)
            if remote_status & STATUS_TRANSFER:
                if client.local_status & STATUS_TRANSFER:
                    handler_pipes[pipe_i].send((client, cldata, SORT_TFER))
                responses_put((ERROR_BAD_STATUS, ip_address, None, NO_CLDATA_I))
            elif remote_status == STATUS_GROUPING:
                if client.local_status == STATUS_GROUPING:
                    handler_pipes[pipe_i].send((client, cldata, SORT_PAIR))
                elif client.local_status == STATUS_SESSION_PREPARING:
                    handler_pipes[pipe_i].send((client, cldata, SORT_INIT))
                else:
                    responses_put((ERROR_BAD_STATUS, ip_address, None, NO_CLDATA_I))
                    continue
            elif remote_status == STATUS_SESSION_PREPARING:
                if client.local_status == STATUS_SESSION_PREPARING:
                    handler_pipes[pipe_i].send((client, cldata, SORT_INIT))
                else:
                    responses_put((ERROR_BAD_STATUS, ip_address, None, NO_CLDATA_I))
                    continue
            elif remote_status == STATUS_SESSION_READY:
                if client.local_status == STATUS_SESSION_PREPARING \
                or client.local_status == STATUS_SESSION_READY:
                    handler_pipes[pipe_i].send((client, cldata, SORT_REDY))
                elif client.local_status == STATUS_TRANSFER:
                    handler_pipes[pipe_i].send((client, cldata, SORT_TFER))
                else:
                    responses_put((ERROR_BAD_STATUS, ip_address, None, NO_CLDATA_I))
                    continue
            else:
                responses_put((ERROR_BAD_STATUS, ip_address, None, NO_CLDATA_I))


def main():

    # TODO: piped objects are copied, so just give each thread one cldata

    udp_port = 8192
    udp_bufsize = 576
    tcp_port = 16777
    tcp_bufsize = 1500
    local_ip = '192.168.0.203'
    buffer_size = udp_bufsize
    subproc_ct = 3
    ip_turnover_time = 15
    ip_turnover_update = 5
    max_poll_rate = 0.099
    cldata_ct = 160
    thread_per_proc_ct = 2
    thread_ct = (subproc_ct + 1) * thread_per_proc_ct
    cldata_ct_per_thread = cldata_ct // thread_ct

    connect_log = ConnectionLog(max_poll_rate, ip_turnover_time)

    udp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    udp_socket.bind((local_ip, udp_port))
    tcp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
    tcp_socket.bind((local_ip, tcp_port))

    print(f'UDP TURN server running on {local_ip}:{udp_port}')

    # preallocating plenty for everybody; each is only written to in the owning process
    cldata_all = [[CLData() for a in range(cldata_ct_per_thread)] for b in range(thread_ct)]

    reccl_handler_pipes = (Pipe() for _ in range(subproc_ct))
    reccl_handler_pipes_rem = [pipe[0] for pipe in reccl_handler_pipes]
    reccl_handler_pipes_loc = [pipe[1] for pipe in reccl_handler_pipes]
    main_handler_pipes = (Pipe() for _ in range(subproc_ct))
    main_handler_pipes_rem = [pipe[0] for pipe in main_handler_pipes]
    main_handler_pipes_loc = [pipe[1] for pipe in main_handler_pipes]
    responses = multiprocessing.Manager().Queue()
    connect_lock = Lock()

    handler_args = (
        (
            reccl_handler_pipes_rem[i], 
            main_handler_pipes_rem[i], 
            responses, 
            cldata_all[2*i:(2*(i+1))]
        ) 
        for i in range(subproc_ct)
    )
    reccl_args = (
        udp_socket, 
        connect_log, 
        reccl_handler_pipes_loc,
        responses,
        cldata_all[subproc_ct*thread_per_proc_ct],
        connect_lock,
        buffer_size,
        subproc_ct
    )

    handlers = [Process(target=handle_clients, args=handler_args[i]) for i in range(subproc_ct)]
    reccl_t = Thread(target=receive_clients, args=reccl_args)
    try:
        for i in range(subproc_ct):
            handlers[i].start()
        reccl_t.start()
        ip_turnover_ctr = 0
        cldata_t = cldata_all[len(cldata_t) - 1]
        cldata_error = CLData()

        # optimization, avoids dict lookups
        responses_empty = responses.empty
        udp_socket_sendto = udp_socket.sendto
        connect_log_turnover = connect_log.turnover
        connect_lock_acquire = connect_lock.acquire
        connect_lock_release = connect_lock.release
        pipe_send = pipe.send

        prev_time = time()

        # -- main process, main thread loop --

        while True:

            # -- send responses to clients --

            while not responses_empty():
                try:
                    response = responses.get()
                    status = response[0]
                    if status & ERROR_MASK:
                        cldata_error.time_stamp = time()
                        cldata_error.error = status
                        cldata_error.status = 0
                        udp_socket_sendto(pack_udp(cldata_error), response[1])
                    else:
                        # NOTE: probably don't need to send info back that the cldata recieved is
                        # writable again, as long as each process has enough of them
                        udp_socket_sendto(pack_udp(response[2]), response[1])
                except:
                    break

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
    main()
