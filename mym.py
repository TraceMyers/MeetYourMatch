from multiprocessing import Process, Pipe, active_children, Manager
from threading import Thread, Lock
from sys import argv
from time import time, sleep
import socket
from collections import deque
import traceback

from constants import *
from register import *
from match import *
from sessions import *


def main_proc(r_sock, m_sock, s_sock, bufsiz, verbose):
    incoming = deque()
    reg_connect_log = ConnectionLog(MAX_POLL_RATE, IP_TURNOVER_TIME, MAX_REGISTERING)
    rm_pipe_out, rm_pipe_in = Pipe(False) # False = simplex
    ms_pipe_out, ms_pipe_in = Pipe(False)
    multi_manager = Manager()
    drop_queue = multi_manager.Queue()
    drop_key = multi_manager.Queue()
    drop_key.put((1, ))

    reg_inc_args = [
        r_sock,
        bufsiz,
        incoming,
        'register'
    ]
    reg_args = [
        r_sock,
        incoming,
        reg_connect_log,
        rm_pipe_out
    ]
    m_args = [
        m_sock,
        bufsiz,
        rm_pipe_in,
        ms_pipe_out,
        drop_queue,
        drop_key,
        verbose
    ]
    s_args = [
        s_sock,
        bufsiz,
        ms_pipe_in,
        drop_queue,
        drop_key,
        verbose
    ]

    # each process responds on its own socket
    reg_inc = Thread(target=buffer_incoming, args=reg_inc_args)
    reg_t = Thread(target=register_clients, args=reg_args)
    m_proc = Process(target=match_clients, args=m_args)
    s_proc = Process(target=manage_sessions, args=s_args)

    reg_inc.start()
    reg_t.start()
    m_proc.start()
    s_proc.start()

    print('running...')
    while True:
        pass


def main(_verbose, _ip):
    udp_bufsize = 576
    local_ip = _ip
    register_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    register_socket.bind((local_ip, REGISTRATION_PORT))
    matchmaking_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    matchmaking_socket.bind((local_ip, MATCHMAKING_PORT))
    session_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    session_socket.bind((local_ip, SESSION_PORT))

    while True:
        try:
            print(
                f'Meet Your Match server loading at {local_ip}\n'
            )
            print(f'accepting registration on port {REGISTRATION_PORT}')
            print(f'accepting matchmaking on port {MATCHMAKING_PORT}')
            print(f'accepting sessions on port {SESSION_PORT}')
            main_proc(register_socket, matchmaking_socket, session_socket, udp_bufsize, _verbose)
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

# --------------------------------------------------------------------------------------:entry point

VA_HELP     = 0
VA_IP       = 1
VA_VERBOSE  = 2

VERBOSE_UPDATE_TIME = 10

valid_argnames = (("-h", "--help"), ("-i", "--ip") ("-v", "--verbose"))
valid_argnames_info = (
    "see names and explanations of arguments",
    "specifies the server's public ip address (default can be set in constants.py)",
    f"prints out connected clients every {VERBOSE_UPDATE_TIME} seconds",
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
ERRNAME_IP_MALFORMED = """
------------
__main__(): ERROR: malformed ip arg value
example(1): python3 matchmaker.py --ip 255.254.253.252
(creates a udp matchmaking server listed at public ip 255.254.253.252, specifies python3)
------------
"""


if __name__ == '__main__':
    with open('log.txt', 'w') as f:
        pass # overwriting previous log file

    # -- default args --
    verbose = False
    local_ip = DEFAULT_IP

    arg_ct = len(argv)
    if arg_ct > 1:
        i = 1
        while True:
            if argv[i] in valid_argnames[VA_IP]:
                i += 1
                if i == arg_ct:
                    print(ERRNAME_IP_MALFORMED)
                    break
                ip = argv[i]
                try:
                    ip_list = [int(val) for val in ip.split('.')]
                    assert len(ip_list) == 4
                    for j in range(4):
                        assert ip_list[j] >= 0 and ip_list[j] <= 255
                except:
                    print(ERRNAME_IP_MALFORMED)
                    exit(1)
                i += 1
            elif argv[i] in valid_argnames[VA_VERBOSE]:
                verbose = True
                i += 1
            elif argv[i] in valid_argnames[VA_HELP]:
                print(VALID_ARGS)
                exit(0)
            else:
                print(ERRNAME_BAD_ARGNAME)
                exit(1)
            if i >= arg_ct:
                break

    main(verbose, local_ip)