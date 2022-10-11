from collections import deque
from common import *
from time import sleep
from os import system
from threading import Thread

# NOTE: use simple game map structure s.t. main menu = lobby = play map, just switch out UI's; avoids
# complications with map load timeouts

def register_intake(in_pipe, match_data, responses, verbose):
    return_pdata = PacketData()

    while True:
        client = in_pipe.recv()

        match_data.acquire_lock()
        if match_data.record_exists(client.address):
            match_data.release_lock()
            continue
        if client.status == CL_STATUS_REGISTER: # CLIENT
            add_success = match_data.add_unmatched(client)
            match_data.release_lock()
            if not add_success:
                return_pdata.status = SV_ERROR_USERS_MAXED
                return_pdata.time_stamp = time()
                responses.append((return_pdata.packit(), client.address))
        elif match_data.session_ct < MAX_MATCHMAKING_SESSIONS: # HOST
            add_success = match_data.add_host(client)
            match_data.release_lock()
            if not add_success:
                return_pdata.status = SV_ERROR_USERS_MAXED
                return_pdata.time_stamp = time()
                responses.append((return_pdata.packit(), client.address))
        else:
            match_data.release_lock()
            return_pdata.status = SV_ERROR_MM_SESSIONS_MAXED
            return_pdata.time_stamp = time()
            responses.append((return_pdata.packit(), client.address))
            

def query_respond(incoming, connect_log, match_data, responses):
    return_pdata = PacketData()
    pdata = PacketData()

    msg = incoming.popleft()

    address = msg[1]
    port = address[1]
    if port not in ACCEPT_TRAFFIC_PORTS:
        return
    pdata.unpackit(msg[0])
    remote_status = pdata.status

    error = connect_log.log_ip(address, remote_status)
    if error & SV_ERROR:
        return_pdata.status = error
    else:
        match_data.acquire_lock()
        if remote_status == CL_STATUS_MATCHING:
            unmatched_index = match_data.find_client_unmatched(address)
            if unmatched_index >= 0:
                match_data.reset_alive_ctr_unmatched_client(unmatched_index)
                return_pdata.status = SV_STATUS_MATCHING_OK
            else:
                ses_i, client_i = match_data.find_client_matched(address)
                if ses_i >= 0:
                    match_data.reset_alive_ctr_matched_client(ses_i, client_i)
                    return_pdata.status = SV_STATUS_IN_GROUP
                else:
                    session_index = match_data.find_host(address)
                    if session_index >= 0:
                        match_data.reset_alive_ctr_host(session_index)
                        return_pdata.status = SV_STATUS_MATCHING_OK
                    else:
                        return_pdata.status = SV_ERROR_MATCHING_NOT_FOUND
        elif remote_status == CL_STATUS_MATCHING_HOST:
            session_index = match_data.find_host(address)
            if session_index >= 0:
                match_data.reset_alive_ctr_host(session_index)
                return_pdata.status = SV_STATUS_MATCHING_OK
            else:
                return_pdata.status = SV_ERROR_MATCHING_NOT_FOUND
        elif remote_status == CL_STATUS_IN_MATCH:
            ses_i, client_i = match_data.find_client_matched(address)
            if ses_i >= 0:
                match_data.set_client_in_match(ses_i, client_i)
                return_pdata.status = SV_STATUS_IN_MATCH
            else:
                return_pdata.status = SV_ERROR_MATCHING_NOT_FOUND
        elif remote_status == CL_STATUS_IN_MATCH_HOST:
            session_index = match_data.find_host(address)
            if session_index >= 0:
                match_data.set_host_in_match(session_index)
                return_pdata.status = SV_STATUS_IN_MATCH
            else:
                return_pdata.status = SV_ERROR_MATCHING_NOT_FOUND
        else:
            return_pdata.status = SV_ERROR_NOT_MATCHING
        match_data.release_lock()

    return_pdata.time_stamp = time()
    responses.append((return_pdata.packit(), address))


def print_matchmaking(unmatched_clients, sessions):
    system('cls')
    print("--\nUnmatched Clients\n--")
    for c in unmatched_clients:
        print(c)
    print("\n--\nSessions\n--")
    for s in sessions:
        print(s)


def matchmake(match_data, responses, out_pipe, drop_queue, drop_key, verbose):
    return_pdata = PacketData()
    # time out
    all_clients = list(match_data.address_to_record.values())
    for client in all_clients:
        client.alive_ctr -= MATCHMAKE_ROUND_TIME
        if client.alive_ctr <= 0:
            match_data.drop(client.address)

    # TODO: lat check
    # put unmatched in matches
    # previous version had functional latency checking, but this is simpler (less potential bugs)
    # and will work better for a demo
    ses_start = 0
    ses_ct = len(match_data.sessions)
    unmatched_clients = match_data.unmatched_clients
    unmatched_copy = list(unmatched_clients)
    for client in unmatched_copy:
        for ses_i in range(ses_start, ses_ct):
            session = match_data.sessions[ses_i]
            if len(session.clients) < session.client_max:
                session.clients.append(client)
                session.addresses.append(client.address)
                unmatched_clients.remove(client)
                ses_start = ses_i
                break

    # inform grouped clients of their current grouping
    return_pdata.status = SV_STATUS_GROUP_UPDATE
    sessions_copy = list(match_data.sessions)
    for i in range(len(sessions_copy)):
        all_in_match = True
        match_data.pack_session(i, return_pdata)
        session = match_data.sessions[i]
        return_pdata.time_stamp = time()
        packed = return_pdata.packit()
        host = session.host
        if not host.in_match:
            all_in_match = False
        responses.append((packed, host.address))
        for c in session.clients:
            responses.append((packed, c.address))
            if not c.in_match:
                all_in_match = False
        if all_in_match:
            # TODO: session transition
            pass

    if verbose:
        print_matchmaking(unmatched_clients, match_data.sessions)


def matchmake_and_respond(
    incoming,
    connect_log,
    match_data,
    responses,
    out_pipe,
    drop_queue,
    drop_key,
    verbose
):
    prev_time = time()
    matchmake_wait_ctr = 0

    while True:
        new_time = time()
        delta_time = new_time - prev_time 
        prev_time = new_time
        matchmake_wait_ctr += delta_time

        if matchmake_wait_ctr >= MATCHMAKE_ROUND_TIME:
            matchmake_wait_ctr = 0
            match_data.acquire_lock()
            matchmake(match_data, responses, out_pipe, drop_queue, drop_key, verbose)
            match_data.release_lock()
        elif len(incoming) > 0:
            query_respond(incoming, connect_log, match_data, responses)


def match_clients(sock, bufsiz, reg_pipe, ses_pipe, drop_queue, drop_key, verbose):
    incoming = deque()
    max_user_ct = MAX_MATCHMAKING_SESSIONS * MAX_MATCH_SIZE
    connect_log = ConnectionLog(MAX_POLL_RATE, IP_TURNOVER_TIME, max_user_ct)
    match_data = LockedMatchingData(max_user_ct)
    responses = LockedList()

    match_inc_args = [
        sock,
        bufsiz,
        incoming,
        "match" 
    ]
    reg_in_args = [
        reg_pipe,
        match_data,
        responses,
        verbose
    ]
    matchmake_t_args = [
        incoming,
        connect_log,
        match_data, 
        responses,
        ses_pipe, 
        drop_queue, 
        drop_key, 
        verbose
    ]

    match_inc = Thread(target=buffer_incoming, args=match_inc_args)
    reg_in = Thread(target=register_intake, args=reg_in_args)
    matchmake_t = Thread(target=matchmake_and_respond, args=matchmake_t_args)

    match_inc.start()
    reg_in.start()
    matchmake_t.start()

    while True:
        pass
        
