from multiprocessing import Process, Pipe
from time import time, sleep
from random import randint, choices
import numpy as np
from pandas import DataFrame as df


def run_pipe(pipe, ticks, _type='number'):
    if _type == 'number':
        for _ in range(ticks):
            pipe.send(1)
        pipe.close()
    elif _type == 'tuple':
        for i in range(ticks):
            pipe.send((
                1, 
                'fish', 
                {'ten':[0,2,3], 'meant':0, 'twenty':2})
            )
        pipe.close()
    elif _type == 'large tuple':
        for i in range(ticks):
            pipe.send((
                1, 
                'fish', 
                0, 
                {'ten':[0,2,3], 'meant':0, 'twenty':2, 'fence':{'fish': 0}},
                20,
                'twenty-nine fish',
                [[0,2,3],[0,3],(1,2)],
                'pippypipe',
                3.14159,
                'i\'d buy that for a dollar!'
            ))
        pipe.close()

def run_pipe_buffered(pipe, ticks):
    buffsize = 100
    buf = [0 for _ in range(buffsize)]
    bufctr = 0
    for _ in range(ticks):
        buf[bufctr] = 1
        bufctr += 1
        if bufctr == buffsize:
            pipe.send(buf)
            buf = [0 for _ in range(buffsize)]
            bufctr = 0
    pipe.close()


def test_pipes(testname, ticks=100000):
    print(f"running test_pipes(): {testname}...")
    processes = 7
    target_sum = ticks * processes

    if testname == 'buffer':
        # pipes unbuffered
        pipes = [Pipe() for _ in range(processes)]
        recievers = [pipes[i][0] for i in range(processes)]
        senders = [pipes[i][1] for i in range(processes)]
        _sum = 0
        start = time()
        for i in range(processes):
            p = Process(target=run_pipe, args=(senders[i], ticks))
            p.start()
        while _sum < target_sum:
            for i in range(processes):
                reciever = recievers[i]
                while reciever.poll():
                    try:
                        val = reciever.recv()
                        _sum += val
                    except EOFError:
                        break
        end = time()
        print(f'pipes unbuffered: {end - start:.3f} seconds')
        sleep(0.1)

        # pipes buffered
        pipes = [Pipe() for _ in range(processes)]
        recievers = [pipes[i][0] for i in range(processes)]
        senders = [pipes[i][1] for i in range(processes)]
        _sum = 0
        start = time()
        for i in range(processes):
            p = Process(target=run_pipe_buffered, args=(senders[i], ticks))
            p.start()
        while _sum < target_sum:
            for i in range(processes):
                reciever = recievers[i]
                while reciever.poll():
                    try:
                        val = reciever.recv()
                        _sum += sum(val)
                    except EOFError:
                        break
        end = time()
        print(f'pipes buffered: {end - start:.3f} seconds')
    elif testname == 'tuple':
        pipes = [Pipe() for _ in range(processes)]
        recievers = [pipes[i][0] for i in range(processes)]
        senders = [pipes[i][1] for i in range(processes)]
        _sum = 0
        start = time()
        for i in range(processes):
            p = Process(target=run_pipe, args=(senders[i], ticks, 'tuple'))
            p.start()
        while _sum < target_sum:
            for i in range(processes):
                reciever = recievers[i]
                while reciever.poll():
                    val = reciever.recv()
                    _sum += val[0]
        end = time()
        print(f'pipes passing tuples: {end - start:.3f} seconds')

        sleep(0.1)

        pipes = [Pipe() for _ in range(processes)]
        recievers = [pipes[i][0] for i in range(processes)]
        senders = [pipes[i][1] for i in range(processes)]
        _sum = 0
        start = time()
        for i in range(processes):
            p = Process(target=run_pipe, args=(senders[i], ticks))
            p.start()
        while _sum < target_sum:
            for i in range(processes):
                reciever = recievers[i]
                while reciever.poll():
                    val = reciever.recv()
                    _sum += val
        end = time()
        print(f'pipes passing numbers: {end - start:.3f} seconds')
        sleep(0.1)

        pipes = [Pipe() for _ in range(processes)]
        recievers = [pipes[i][0] for i in range(processes)]
        senders = [pipes[i][1] for i in range(processes)]
        _sum = 0
        start = time()
        for i in range(processes):
            p = Process(target=run_pipe, args=(senders[i], ticks, 'large tuple'))
            p.start()
        while _sum < target_sum:
            for i in range(processes):
                reciever = recievers[i]
                while reciever.poll():
                    val = reciever.recv()
                    _sum += val[0]
        end = time()
        print(f'pipes passing large tuples: {end - start:.3f} seconds')
        sleep(0.1)
    else:
        print(f'no test by the name {testname}')


def make_ip_address():
    ip_str = str(randint(0, 255))
    for _ in range(3):
        ip_str += '.'
        ip_str = str(randint(0, 255))
    return ip_str


class ConnectionLogList:

    def __init__(self, max_poll_rate, MAX_IP, turnover_time):
        self.MAX_IP = MAX_IP
        self.turnover_time = turnover_time
        self.ip_log = [None for _ in range(MAX_IP)]
        self.avail_key = 0
        self.top_key = 1
        self.max_poll_rate = max_poll_rate
        self.turnover_begin = 0
        self.turnover_size = MAX_IP if MAX_IP < 100 else 100

    def log_ip(self, ip_address):
        cur_time = time()
        for _key in range(self.top_key):
            entry = self.ip_log[_key]
            if entry is not None and ip_address == entry[0]:
                refuse_entry = 0
                prev_time = entry[1]
                if cur_time - prev_time < self.max_poll_rate:
                    refuse_entry = 1
                self.ip_log[_key] = (ip_address, cur_time)
                return refuse_entry
        if self.avail_key >= self.MAX_IP:
            return 1
        self.ip_log[self.avail_key] = (ip_address, cur_time)
        self.avail_key += 1
        if self.avail_key == self.top_key:
            self.top_key += 1
            return 0
        while self.avail_key < self.MAX_IP: 
            if self.avail_key == self.top_key: # will be None
                self.top_key += 1
                return 0
            if self.ip_log[self.avail_key] == None:
                return 0
            self.avail_key += 1
        return 1

    def turnover(self):
        turnover_end = self.turnover_begin + self.turnover_size
        restart_turnover = False
        if turnover_end > self.MAX_IP:
            turnover_end = self.MAX_IP
            restart_turnover = True
        for _key in range(self.turnover_begin, turnover_end):
            entry = self.ip_log[_key]
            if entry is not None:
                entry_delta_time = time() - entry[1]
                if entry_delta_time > self.turnover_time:
                    self.ip_log[_key] = None
                    if _key < self.avail_key:
                        self.avail_key = _key
                    if _key + 1 >= self.top_key:
                        _key -= 1
                        while _key > 0 and self.ip_log[_key] is None:
                            key -= 1
                        self.top_key = _key + 1
                        restart_turnover = True
                        break
        if restart_turnover:
            self.turnover_begin = 0
        else:
            self.turnover_begin = turnover_end


class ConnectionLogDict:

    def __init__(self, max_poll_rate, MAX_IP, turnover_time):
        self.MAX_IP = MAX_IP
        self.turnover_time = turnover_time
        self.ip_log = {}
        self.max_poll_rate = max_poll_rate

    def log_ip(self, ip_address):
        cur_time = time()
        if ip_address in self.ip_log:
            prev_time = self.ip_log[ip_address]
            if cur_time - prev_time < self.max_poll_rate:
                return 1
        self.ip_log[ip_address] = cur_time
        return 0

    def turnover(self):
        for key, value in self.ip_log.items():
            entry_delta_time = time() - value
            if entry_delta_time > self.turnover_time:
                del self.ip_log[key]


def test_ip_dict_vs_list():
    print("running test_ip_dict_vs_list()...")
    ip_addresses = [make_ip_address() for _ in range(3000)]
    counts = (30, 100, 300, 1000, 3000)
    list_results = np.array([[0 for a in range(len(counts))] for b in range(len(counts))], dtype=np.float32)
    dict_results = np.array([[0 for a in range(len(counts))] for b in range(len(counts))], dtype=np.float32)

    for i in range(len(counts)):
        max_ip = counts[i]
        for j in range(len(counts)):
            client_ct = counts[j]
            print(f'max ip={max_ip}, client ct={client_ct}')
            wait_time_rough = 1/(client_ct*10)
            wait_time_rough += wait_time_rough * 0.05
            connection_ct = client_ct * 10 * 60
            clients = ip_addresses[:client_ct]
            incoming_addresses = choices(clients, k=connection_ct)

            connection_log_list = ConnectionLogList(0.1, max_ip, 15)
            connection_log_dict = ConnectionLogDict(0.1, max_ip, 15)

            start = time()
            turnover_ctr = start
            turnover_delay = 1
            for _ in range(connection_ct):
                connection_log_list.log_ip(incoming_addresses[i])
                delta_time = time() - turnover_ctr
                if delta_time >= turnover_delay:
                    connection_log_list.turnover()
                    turnover_ctr = 0
            end = time()
            list_results[i, j] = end - start

            sleep(0.5)

            start = time()
            turnover_ctr = start
            turnover_delay = 1
            for _ in range(connection_ct):
                connection_log_dict.log_ip(incoming_addresses[i])
                delta_time = time() - turnover_ctr
                if delta_time >= turnover_delay:
                    connection_log_dict.turnover()
                    turnover_ctr = 0
            end = time()
            dict_results[i, j] = end - start
    
    list_results = np.round(list_results, 3)
    list_df = df(list_results)
    list_df.columns = [f'max ip={ct}' for ct in counts]
    list_df.index = [f'clients={ct}' for ct in counts]
    dict_results = np.round(dict_results, 3)
    dict_df = df(dict_results)
    dict_df.columns = [f'max ip={ct}' for ct in counts]
    dict_df.index = [f'clients={ct}' for ct in counts]
    print(list_results)
    print(dict_results)
    print("results list - dict:")
    print(list_results - dict_results)
    

def test_list():
    ticks = 100000

    a = [i for i in range(200)]
    a.extend([None for i in range(500)])
    ASSIGN = 0
    REMOVE = 1
    ops = choices([ASSIGN, REMOVE], k=ticks)
    start = time()
    optargets = [None for _ in range(ticks)]
    for i in range(ticks):
        op = ops[i]
        if op == REMOVE:
            try:
                b = optargets[i]
                a.pop(30)
            except:
                pass
        else:
            a.append(1)
    method_time = time() - start
    print(f'method time: {method_time:.3f}')

    sleep(0.1)

    indices = [i for i in range(160)]
    optargets = choices(indices, k=ticks)
    a = [i for i in range(200)]
    a.extend([None for i in range(500)])
    ctr = 200
    start = time()
    for i in range(ticks):
        if op == REMOVE:
            a[optargets[i]] = None
            if ctr < i:
                ctr = i
        elif ctr < 400:
            a[ctr] = 1
            while a[ctr] is not None:
                ctr += 1
    
    search_time = time() - start
    print(f'search time: {search_time}')
    




if __name__ == '__main__':
    # result: unbuffered is O(n), buffered is O(log(n))
    # test_pipes('tuple') 

    # result: dict roughly 6x faster with 3000 clients and 3000 max clients, about the same for 100,100
    #test_ip_dict_vs_list() 

    # result: searching wins over methods
    # test_list()
    pass

