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

        if client.status == CL_STATUS_REGISTER: # CLIENT
            m_client = MatchingClient(client)
            match_lock.acquire()
            match_data.unmatched_clients.append(m_client)
            match_data.addresses.add(m_client.address)
            match_lock.release()
        elif match_data.session_ct < MAX_MATCHMAKING_SESSIONS: # HOST
            m_host = MatchingHost(client)
            match_lock.acquire()
            match_data.sessions.append(Session(m_host))
            match_data.addresses.add(m_host.address)
            match_lock.release()
        else:
            return_pdata.status = SV_ERROR_MM_SESSIONS_MAXED
            return_pdata.time_stamp = time()
            responses_lock.acquire()
            responses.append((return_pdata.packit(), client.address))
            responses_lock.release()

        
def packet_update(sock, incoming, connect_log, match_data):
    return_pdata = PacketData()
    pdata = PacketData()

    while True:
        while len(incoming) == 0:
            pass
        msg = incoming.popleft()

        ip_address = msg[1]
        port = ip_address[1]
        if port not in ACCEPT_TRAFFIC_PORTS:
            continue
        pdata.unpackit(msg[0])
        remote_status = pdata.status

        error = connect_log.log_ip(ip_address, remote_status)
        if error & SV_ERROR:
            return_pdata.status = error
            return_pdata.time_stamp = time()
            sock.sendto(return_pdata.packit(), ip_address)
            continue

        if remote_status == CL_STATUS_MATCHING:
            
        elif remote_status == CL_STATUS_MATCHING_HOST:
            pass
        else:
            return_pdata.status = SV_ERROR_NOT_MATCHING
            return_pdata.time_stamp = time()
            sock.sendto(return_pdata.packit(), ip_address)


def matchmake(sock, incoming, connect_log, match_data, out_pipe, drop_queue, drop_key, verbose):
    while True:
        pass


def match_clients(sock, bufsiz, reg_pipe, ses_pipe, drop_queue, drop_key, verbose):
    incoming = deque()
    connect_log = ConnectionLog(MAX_POLL_RATE, IP_TURNOVER_TIME, MAX_MATCHMAKING_SESSIONS * MAX_MATCH_SIZE)
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
    p_update_args = [
        sock, 
        incoming, 
        connect_log, 
        match_data
    ]

    match_inc = Thread(target=buffer_incoming, args=match_inc_args)
    reg_in = Thread(target=register_intake, args=reg_in_args)
    p_update = Thread(target=packet_update, args=p_update_args)

    match_inc.start()
    reg_in.start()
    p_update.start()
    matchmake(sock, incoming, connect_log, match_data, ses_pipe, drop_queue, drop_key, verbose)
