"""
Registers n users and tries to update them on average 5 times per second. A 2019 core i5 machine
can pretend to be 

Also functions as example code for how to interact with the server. May update in the future to
provide a simple command-line client for arbitrary data passing.
"""

import requests
from requests.structures import CaseInsensitiveDict
from time import sleep, time
from random import choice, randint
from sys import argv
import numpy as np
from matplotlib import pyplot as plt
from multiprocessing import Process, Pipe
from pandas import DataFrame
from statsmodels.api import OLS, add_constant
import socket


with open('url.txt') as f:
    url = f.readline()
headers = CaseInsensitiveDict()
headers["Accept"] = "application/json"
headers["Content-Type"] = "application/json"


class Client:

    def __init__(self):
        self.pair_key = None
        self.session_key = None
        self.prev_server_reply = None
        self.next_post = None
        self.has_recieved_error = False
        self.state = 0

    def __repr__(self):
        return (
            f'player\n' \
            f'pair_key: {self.pair_key}\n' \
            f'session_key: {self.session_key}\n' \
            f'prev_server_reply: {self.prev_server_reply}\n' \
            f'next_post: {self.next_post}\n' \
            f'has_recieved_error: {self.has_recieved_error}\n' \
            f'state: {self.state}' 
        )


def get_user_count_data():
    user_ct = 30
    if len(argv) > 1:
        try:
            user_ct = int(argv[1])
        except:
            print(
                'call format: "python stresstest.py 50" where "50" is the number of clients being'
                ' simulated at 10 updates/sec.'
            )
            exit(1)
    return user_ct


def run_client(
    pnum, 
    step_ct, 
    client, 
    sender,
    finished,
    wait=0.2
):
    global strings
    global names
    
    BUFSIZE = 100

    response_buf = [-2 for _ in range(BUFSIZE)]
    compute_buf = [None for _ in range(BUFSIZE)]
    network_buf = [None for _ in range(BUFSIZE)]
    error_buf = [-2 for _ in range(BUFSIZE)]
    unique_buf = 0
    success_buf = [-2 for _ in range(BUFSIZE)]
    
    buf_ctr = -1

    step_ct_m1 = step_ct - 1
    for step in range(step_ct):
        tick_start = time()
        request_code = None
        if client.next_post is None:
            client.next_post = f'0,{choice(names)},*,*,*'
        try:
            start = time()
            post_resp = requests.post(url, headers=headers, data=client.next_post)
            total_time = time() - start
            request_code = int(client.next_post[0])
        except:
            continue
        try:
            get_resp = requests.get(url, headers=headers)
            # these times are sometimes not accurate due to async, but are still helpful
            server_compute_time = float(get_resp.text)
            network_time = total_time - server_compute_time
            compute_buf[buf_ctr] = (request_code, server_compute_time)
            network_buf[buf_ctr] = (request_code, network_time)
        except:
            pass
        data = post_resp.text.split('/')
        server_op_code = int(data[0])
        server_op_success = server_op_code == 0
        if data[1].isnumeric(): 
            server_op_extra_code = int(data[1])
        else:
            server_op_extra_code = None
        server_op_return_data = data[2]
        if server_op_success:
            success_buf[buf_ctr] = server_op_extra_code
            if server_op_extra_code in (9, 10):
                client.state += 1
                client.next_post = f'6,{choice(strings)},{client.session_key},{client.pair_key},{client.state}'
            elif server_op_extra_code == 11:
                client.next_post = f'6,{choice(strings)},{client.session_key},{client.pair_key},{client.state}'
            elif server_op_extra_code == 0:
                client.pair_key = server_op_return_data
                client.next_post = f'2,*,{client.pair_key},*,*'
            elif server_op_extra_code == 2:
                client.next_post = f'2,*,{client.pair_key},*,*'
            elif server_op_extra_code in (3, 4):
                client.next_post = f'3,*,{client.pair_key},*,*'
            elif server_op_extra_code in (5, 6):
                client.next_post = f'4,*,{client.pair_key},*,*'
            elif server_op_extra_code == 7:
                client.next_post = f'4,*,{client.pair_key},*,*'
            elif server_op_extra_code == 8:
                game_keys = server_op_return_data.split('|')
                client.session_key = game_keys[0]
                client.pair_key = game_keys[1]
                client.next_post = f'6,{choice(strings)},{client.session_key},{client.pair_key},0'
        else:
            if not client.has_recieved_error:
                client.has_recieved_error = True
                unique_buf += 1
            client.next_post = f'0,{choice(names)},*,*,*'
            client.state = 0
            client.session_key = None
            client.pair_key = None
            error_buf[buf_ctr] = server_op_code
        response_buf[buf_ctr] = server_op_code

        client.prev_server_reply = post_resp.text

        buf_ctr += 1
        if buf_ctr == BUFSIZE or step == step_ct_m1:
            buf_ctr = 0
            sender.send((
                response_buf,
                compute_buf,
                network_buf,
                error_buf,
                unique_buf,
                success_buf
            ))
            response_buf = [-2 for _ in range(BUFSIZE)]
            compute_buf = [None for _ in range(BUFSIZE)]
            network_buf = [None for _ in range(BUFSIZE)]
            error_buf = [-2 for _ in range(BUFSIZE)]
            unique_buf = 0
            success_buf = [-2 for _ in range(BUFSIZE)]

        tick_end = time()
        tick_time_passed = tick_end - tick_start
        wait_time = wait - tick_time_passed
        if wait_time > 0:
            sleep(wait_time)

    finished.send(1)
    finished.close()
    return


def main():
    global names
    global data
    # TODO: args
    max_user_ct = 50
    # 20 per variable is ok
    trial_ct = 5
    step_ct = 180 
    user_cts = [randint(2, max_user_ct) for _ in range(trial_ct)]
    mean_compute_times = []
    mean_network_times = []
    mean_local_compute_times = []

    # ----------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------:test loop
    # ----------------------------------------------------------------------------------------------
    
    print("Running test...")
    for i in range(trial_ct):
        user_ct = user_cts[i]
        
        errors = []
        compute_times = []
        network_times = []
        response_codes = []
        success_codes = []
        unique_recieved_error = 0

        pipes = [Pipe() for _ in range(user_ct)]
        recievers = [pipes[j][0] for j in range(user_ct)]
        senders = [pipes[j][1] for j in range(user_ct)]
        finished_pipe = [Pipe() for _ in range(user_ct)]
        finished_recv = [finished_pipe[j][0] for j in range(user_ct)]
        finished_send = [finished_pipe[j][1] for j in range(user_ct)]

        clients = [Client() for _ in range(user_ct)]

        # clearing clients on server (just send anything that returns an error)
        print('telling server to clear client cache')
        requests.post(url, headers=headers, data="0,nada,0,*,*")
        sleep(0.02)

        test_start = time()
        started_ct = 0
        user_ct_strlen = len(str(user_ct))
        print(f'Running trial {i+1} of {trial_ct}')
        for u in range(user_ct):
            client = clients[u]
            args = (
                u, 
                step_ct,
                client, 
                senders[u],
                finished_send[u]
            )
            p = Process(target=run_client, args=args)
            p.start()
            started_ct += 1
            print_started(started_ct, user_ct, user_ct_strlen)
            sleep(0.1)
        print()
        finished_ct = 0
        pipe_closed = [False for _ in range(user_ct)]
        while finished_ct < user_ct:
            sleep(0.2)
            for u in range(user_ct):
                reciever = recievers[u]
                packages = []
                while reciever.poll():
                    try:
                        packages.append(reciever.recv())
                    except EOFError:
                        break
                for p in packages:
                    response_codes.extend(p[0])
                    compute_times.extend(p[1])
                    network_times.extend(p[2])
                    errors.extend(p[3])
                    unique_recieved_error += p[4]
                    success_codes.extend(p[5])
                finished_reciever = finished_recv[u]
                if not pipe_closed[u] and finished_reciever.poll():
                    # poll() is 'unreliable' according to the documentation; not sure if 
                    # this is necessary
                    try:
                        finished_ct += finished_reciever.recv()
                        pipe_closed[u] = True
                    except:
                        pass
            print_finished(finished_ct, user_ct, user_ct_strlen)
        test_end = time()
        print()
        
        # ----------------------------------------------------------------------------------------------
        # ---------------------------------------------------------------------------:summary statistics
        # ----------------------------------------------------------------------------------------------

        compute_times = code_times_process(compute_times)
        network_times = code_times_process(network_times)
        compute_times_flat = [item for sublist in compute_times for item in sublist]
        network_times_flat = [item for sublist in network_times for item in sublist]
        error_counts = get_error_counts(errors)

        compute_arr = np.array(compute_times_flat)
        compute_arr.sort()
        median_compute = compute_arr[compute_arr.shape[0] // 2]
        mean_compute = compute_arr.mean()
        max_compute = compute_arr.max()
        min_compute = compute_arr.min()
        network_arr = np.array(network_times_flat)
        network_arr.sort()
        median_network = network_arr[network_arr.shape[0] // 2]
        mean_network = network_arr.mean()
        max_network = network_arr.max()
        min_network = network_arr.min()

        total_time = test_end - test_start
        print(f'Stress test took {total_time:.2f} seconds with {user_ct} users')
        print(
            # f'\nmedian compute time: {median_compute:.05f}\n'
            f'mean compute time: {mean_compute:.05f}'
            # f'max compute time: {max_compute:.05f}\n'
            # f'min compute time: {min_compute:.05f}'
        )
        print(
            # f'\nmedian network time: {median_network:.05f}\n'
            f'mean network time: {mean_network:.05f}'
            # f'max network time: {max_network:.05f}\n'
            # f'min network time: {min_network:.05f}\n'
        )
        mean_local_compute = total_time - mean_compute - mean_network
        f'mean local compute time: {mean_local_compute:.05f}'
        mean_compute_times.append(mean_compute)
        mean_network_times.append(mean_network)
        # mean_local_compute_times.append(mean_local_compute)
        if i != trial_ct - 1:
            print('waiting for client drop timeout...')
            sleep(30)

    # correlations regression: (user ct) ~ (affine transformation of times spent)
    # sort of like testing each time spent as a function of number of users one at a time
    x = DataFrame({
        'mean server compute time' : mean_compute_times,
        'mean network time' : mean_network_times,
        'mean local compute time' : mean_local_compute_times
    })
    y = DataFrame({'user count' : user_cts})
    # going from 0 users to 1 user incurs some constant overhead, so we need an intercept
    x = add_constant(x)
    model = OLS(y, x).fit()
    print(model.summary())

    plt.plot(user_cts, mean_compute_times, 'o', alpha=0.6)
    plt.xlabel('client count')
    plt.xlim(0, max_user_ct + 1)
    plt.xticks([i for i in range(max_user_ct + 1)])
    plt.ylabel('mean compute time')
    plt.title('Mean Server Compute Time ~ Client Count')
    plt.show()

    plt.plot(user_cts, mean_local_compute_times, 'o', alpha=0.6)
    plt.xlabel('client count')
    plt.xlim(0, max_user_ct + 1)
    plt.xticks([i for i in range(max_user_ct + 1)])
    plt.ylabel('mean local compute time')
    plt.title('Mean Local Compute Time ~ Client Count')
    plt.show()

    plt.plot(user_cts, mean_network_times, 'o', alpha=0.6)
    plt.xlabel('client count')
    plt.xlim(0, max_user_ct + 1)
    plt.xticks([i for i in range(max_user_ct + 1)])
    plt.ylabel('mean network time')
    plt.title('Mean Network Time ~ Client Count')
    plt.show()
    
    return

    for error_code in range(1, 22):
        print(f'error {error_code:02d} occurences: {error_counts[error_code]}')
    print(f'Total error count: {sum(error_counts)}')
    print(f'Percent of clients that recieved at least one error: {unique_recieved_error/user_ct*100:.1f}%')

    plt.hist(compute_times_flat)
    plt.xlabel('seconds')
    plt.ylabel('frequency')
    plt.title('Server Compute Times')
    plt.show()

    plt.hist(network_times_flat)
    plt.xlabel('seconds')
    plt.ylabel('frequency')
    plt.title('Network Times')
    plt.show()

    plt.hist(errors)
    plt.xlabel('error codes')
    plt.xlim(-2, 22)
    plt.ylabel('frequency')
    plt.title('Error Counts')
    plt.xticks([i for i in range(-2, 22)])
    plt.show()

    plt.plot([i for i in range(len(response_codes))], response_codes, '.', alpha=0.2)
    plt.xlabel('time step')
    plt.ylabel('code')
    plt.ylim(-2, 22)
    plt.yticks([i for i in range(-2, 22)])
    plt.title('Server Op Codes Over Time (roughly)')
    plt.show()

    plt.plot([i for i in range(len(success_codes))], success_codes, '.', alpha=0.2)
    plt.xlabel('time step')
    plt.ylabel('code')
    plt.ylim(0, 12)
    plt.yticks([i for i in range(0, 12)])
    plt.title('Server Success Codes Over Time (roughly)')
    plt.show()

    mean_compute_times = [np.mean(item) if len(item) > 0 else 0 for item in compute_times]
    mean_network_times = [np.mean(item) if len(item) > 0 else 0 for item in network_times]

    plt.bar([i for i in range(7)], mean_compute_times)
    plt.xlabel('request code')
    plt.xticks([i for i in range(7)])
    plt.ylabel('seconds')
    plt.title('Mean Compute Times by Request')
    plt.show()

    plt.bar([i for i in range(7)], mean_network_times)
    plt.xlabel('request code')
    plt.xticks([i for i in range(7)])
    plt.ylabel('seconds')
    plt.title('Mean Network Times by Request')
    plt.show()

    max_compute_times = [np.max(item) if len(item) > 0 else 0 for item in compute_times]
    max_network_times = [np.max(item) if len(item) > 0 else 0 for item in network_times]

    plt.bar([i for i in range(7)], max_compute_times)
    plt.xlabel('request code')
    plt.xticks([i for i in range(7)])
    plt.ylabel('seconds')
    plt.title('Max Compute Times by Request')
    plt.show()

    plt.bar([i for i in range(7)], max_network_times)
    plt.xlabel('request code')
    plt.xticks([i for i in range(7)])
    plt.ylabel('seconds')
    plt.title('Max Network Times by Request')
    plt.show()

# --------------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------------:data
# --------------------------------------------------------------------------------------------------

def print_started(started_ct, user_ct, digit_ct):
    if digit_ct >= 4:
        print(f'\rprocesses started:  {started_ct:04d}/{user_ct} ', end='')
    elif digit_ct == 3:
        print(f'\rprocesses started:  {started_ct:03d}/{user_ct} ', end='')
    elif digit_ct >= 2:
        print(f'\rprocesses started:  {started_ct:02d}/{user_ct} ', end='')
    else:
        print(f'\rprocesses started:  {started_ct}/{user_ct} ', end='')

def print_finished(finished_ct, user_ct, digit_ct):
    if digit_ct >= 4:
        print(f'\rprocesses finished: {finished_ct:04d}/{user_ct} ', end='')
    elif digit_ct == 3:
        print(f'\rprocesses finished: {finished_ct:03d}/{user_ct} ', end='')
    elif digit_ct >= 2:
        print(f'\rprocesses finished: {finished_ct:02d}/{user_ct} ', end='')
    else:
        print(f'\rprocesses finished: {finished_ct}/{user_ct} ', end='')

def code_times_process(pair_list):
    times_by_index = [[] for _ in range(22)]
    for item in pair_list:
        if item is not None:
            times_by_index[item[0]].append(item[1])
    return times_by_index

def get_error_counts(errors):
    error_counts = [0 for _ in range(-2, 22)]
    for error in errors:
        error_counts[error] += 1
    return error_counts

names = [
    'fishbones',
    'clarabelle',
    'stella',
    'martha stewart',
    'bilbo baggins',
    '0134mysmarthomedevice',
    'anonymous',
    'anonymous2',
    'cryptids... attack!',
    'alex jones',
    'the real bibby',
    'the actual diddy',
    'smash mouth',
    'beck'
]
strings = [
    'wish you were here',
    'time flies',
    'texting sucks',
    'aint life grand',
    'tippy tappy dippy dappy',
    'dang yall',
    'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers' \
        'goobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobersgoobers',
    'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ' \
        'i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! i\'d buy that for a dollar! ',
    'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' \
        'Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. Frankly my dear I don\'t give a damn. ' 
]


if __name__ == '__main__':
    main()