from common import *
from constants import *
from time import time, sleep

# TODO: handle admin key and flags on pdata

def register_clients(sock, incoming, connect_log, match_pipe):
    return_pdata = PacketData()
    pdata = PacketData()

    while True:
        # pop() is atomic, but throws an exception if the list is empty. Haven't tested a try/except,
        # but it is probably catastrophically slow when the exception throws
        while len(incoming) == 0:
            sleep(0.05)
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

        if remote_status != CL_STATUS_REGISTER:
            return_pdata.status = SV_ERROR_NOT_REGISTERING
            return_pdata.time_stamp = time()
            sock.sendto(return_pdata.packit(), ip_address)
            continue
        client = Client(pdata, ip_address)
        success = client.set_group_size(pdata)
        if not success:
            return_pdata.status = SV_ERROR_BAD_GROUP_SIZE
            return_pdata.time_stamp = time()
            sock.sendto(return_pdata.packit(), ip_address)
            continue
        match_pipe.send(client)
        return_pdata.status = SV_STATUS_REGISTER_OK
        return_pdata.time_stamp = time()
        sock.sendto(return_pdata.packit(), ip_address)

        
        
