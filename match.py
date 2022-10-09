from multiprocessing import Process, Pipe, active_children, Manager
from threading import Thread, Lock
from sys import argv
from time import time, sleep
import socket
from struct import pack, unpack
from collections import deque
import traceback
from constants import *
from common import *


def register_intake(in_pipe, match_data, match_lock, responses, responses_lock, verbose):

    return_pdata = PacketData()

    while True:
        client = in_pipe.recv()

        already_matching = False
        match_lock.acquire()
        if client.address in match_data.addresses:
            already_matching = True
        match_lock.release()
        if already_matching:
            continue

        if client.status == CL_STATUS_REGISTER:
            m_client = MatchingClient(client)
            match_lock.acquire()
            match_data.unmatched_clients.append(m_client)
            match_data.addresses.add(m_client.address)
            match_lock.release()
        elif match_data.session_ct < MAX_MATCHMAKING_SESSIONS:
            m_host = MatchingHost(client)
            match_lock.acquire()
            match_data.hosts.append(m_host)
            match_data.addresses.add(m_host.address)
            match_lock.release()
        else:
            return_pdata.status = SV_ERROR_MM_SESSIONS_MAXED
            return_pdata.time_stamp = time()
            responses_lock.acquire()
            responses.append((return_pdata.pack_udp(), client.address))
            responses_lock.release()


def matchmake(connect_log, match_data, out_pipe, drop_queue, drop_key, verbose):
    pass


def match_clients(sock, bufsiz, reg_pipe, ses_pipe, drop_queue, drop_key, verbose):
    incoming = deque()
    connect_log = ConnectionLog()
    match_data = MatchingData()
    match_lock = Lock()
    responses = []
    responses_lock = Lock()

    match_inc_args = [
        sock,
        bufsiz,
        incoming,
        "match" 
    ]
    reg_in_args = [
        reg_pipe,
        match_data,
        match_lock,
        responses,
        responses_lock,
        verbose
    ]

    match_inc = Thread(target=buffer_incoming, args=match_inc_args)
    reg_in = Thread(target=register_intake, args=reg_in_args)

    match_inc.start()
    reg_in.start()
    matchmake(connect_log, match_data, ses_pipe, drop_queue, drop_key, verbose)