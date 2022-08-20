"""
An admittedly imperfect stress test for my TURN server. Registers n users and tries to update
them on average 10 times per second. On my computer, it does a very bad job at emulating an 
idealized version of this scenario after ~50 clients. A better test would be multithreaded or
multi-headed, for a few reasons. But, it appears to verify that the server handles multiple clients
well.
"""

import requests
from requests.structures import CaseInsensitiveDict
from time import sleep, time
from random import choice
from sys import argv
import numpy as np
from matplotlib import pyplot as plt
from multiprocessing import Process, Queue

url = "http://154.12.226.174:80"
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


def get_user_count_data():
    user_ct = 10
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


def run_client(step_ct, client, response_codes, rc_comp, rc_net, error_counts, error_list, counts, finished, wait_delta=0.1):
    global strings
    for _ in range(step_ct):
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
            cts = counts.get()
            cts[1] += 1
            counts.put(cts)
            rc = response_codes.get()
            rc.append(-2)
            response_codes.put_nowait(rc)
            continue
        try:
            get_resp = requests.get(url, headers=headers)
            server_compute_time = float(get_resp.text)
            network_time = total_time - server_compute_time
            response_code_compute_time = rc_comp.get()
            response_code_network_time = rc_net.get()
            response_code_compute_time[request_code].append(server_compute_time)
            response_code_network_time[request_code].append(network_time)
            rc_comp.put(response_code_compute_time)
            rc_net.put(response_code_network_time)
        except:
            cts = counts.get()
            cts[0] += 1
            counts.put(cts)

        client.prev_server_reply = post_resp.text
        data = post_resp.text.split('/')
        server_op_code = int(data[0])
        server_op_success = server_op_code == 0
        server_op_extra_code = None
        try:
            server_op_extra_code = int(data[1])
        except:
            pass
        server_op_return_data = data[2]
        if server_op_success:
            if server_op_extra_code in (9, 10):
                client.state += 1
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
                cts = counts.get()
                cts[2] += 1
                counts.put(cts)
            client.next_post = f'0,{choice(names)},*,*,*'
            ec = error_counts.get()
            ec[server_op_code] += 1
            error_counts.put(ec)
            el = error_list.get()
            el.append(server_op_code)
            error_list.put(el)
        rc = response_codes.get()
        rc.append(server_op_code)
        response_codes.put(rc)

        tick_end = time()
        tick_time_passed = tick_end - tick_start
        wait_time = wait_delta - tick_time_passed
        if wait_time > 0:
            sleep(wait_time)
    f = finished.get()
    f[0] += 1
    finished.put(f)
    return


def main():
    global names
    global data
    user_ct = get_user_count_data() 
    error_counts = Queue()
    error_counts.put([0 for _ in range(22)])
    request_code_compute_times = Queue()
    request_code_compute_times.put([[] for _ in range(7)])
    request_code_network_times = Queue()
    request_code_network_times.put([[] for _ in range(7)])
    response_codes = Queue()
    response_codes.put([])
    error_list = Queue()
    error_list.put([])
    # time_measure_failure_ct = 0
    # post_failure_ct = 0
    # unique_recieved_error_ct = 0
    counts = Queue()
    counts.put([0, 0, 0])
    finished_ct = Queue()
    finished_ct.put([0])
    clients = [Client() for _ in range(user_ct)]

    # ----------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------:test loop
    # ----------------------------------------------------------------------------------------------

    print("Running test...")
    step_ct = 100
    test_start = time()
    for client in clients:
        args = (
            step_ct, 
            client, 
            response_codes, 
            request_code_compute_times, 
            request_code_network_times, 
            error_counts, 
            error_list, 
            counts, 
            finished_ct
        )
        p = Process(target=run_client, args=args)
        p.start()
    while True:
        sleep(1)
        finished = finished_ct.get()
        print(finished)
        finished_ct.put(finished)
        if finished[0] == user_ct:
            break
    test_end = time()
    
    # ----------------------------------------------------------------------------------------------
    # ---------------------------------------------------------------------------:summary statistics
    # ----------------------------------------------------------------------------------------------

    request_code_compute_times = request_code_compute_times.get()
    request_code_network_times = request_code_network_times.get()
    error_counts = error_counts.get()
    error_list = error_list.get()
    response_codes = response_codes.get()
    counts = counts.get()
    time_measure_fail_ct = counts[0]
    post_failure_ct = counts[1]
    unique_recieved_error_ct = counts[2]
    
    server_compute_times = [item for sublist in request_code_compute_times for item in sublist]
    network_times = [item for sublist in request_code_network_times for item in sublist]
    server_compute_times = np.array(server_compute_times)
    server_compute_times.sort()
    median_compute = server_compute_times[server_compute_times.shape[0] // 2]
    mean_compute = server_compute_times.mean()
    max_compute = server_compute_times.max()
    min_compute = server_compute_times.min()
    network_times = np.array(network_times)
    network_times.sort()
    median_network = network_times[network_times.shape[0] // 2]
    mean_network = network_times.mean()
    max_network = network_times.max()
    min_network = network_times.min()

    print(f'Stress test took {test_end - test_start:.1f} seconds')
    print(
        f'\nmedian compute time: {median_compute:.05f}\n'
        f'mean compute time: {mean_compute:.05f}\n'
        f'max compute time: {max_compute:.05f}\n'
        f'min compute time: {min_compute:.05f}'
    )
    print(
        f'\nmedian network time: {median_network:.05f}\n'
        f'mean network time: {mean_network:.05f}\n'
        f'max network time: {max_network:.05f}\n'
        f'min network time: {min_network:.05f}\n'
    )
    for error_code in range(1, 22):
        print(f'error {error_code:02d} occurences: {error_counts[error_code]}')
    print(f'Total error count: {sum(error_counts)}')
    print(f'Percent of clients that recieved at least one error: {unique_recieved_error_ct/user_ct*100:.1f}%')

    plt.hist(server_compute_times)
    plt.xlabel('seconds')
    plt.ylabel('frequency')
    plt.title('Server Compute Times')
    plt.show()

    plt.hist(network_times)
    plt.xlabel('seconds')
    plt.ylabel('frequency')
    plt.title('Network Times')
    plt.show()

    plt.hist(error_list)
    plt.xlabel('error codes')
    plt.xlim(-2, 22)
    plt.ylabel('frequency')
    plt.title('Error Counts')
    plt.xticks([i for i in range(-2, 22)])
    plt.show()

    plt.plot([i for i in range(len(response_codes))], response_codes, '.')
    plt.xlabel('time step')
    plt.ylabel('code')
    plt.ylim(-2, 22)
    plt.yticks([i for i in range(-2, 22)])
    plt.title('Server Op Codes Over Time')
    plt.show()

    mean_request_code_compute_times = [np.mean(item) if len(item) > 0 else 0 for item in request_code_compute_times]
    mean_request_code_network_times = [np.mean(item) if len(item) > 0 else 0 for item in request_code_network_times]

    plt.bar([i for i in range(7)], mean_request_code_compute_times)
    plt.xlabel('request code')
    plt.xticks([i for i in range(7)])
    plt.ylabel('seconds')
    plt.title('Mean Request Code Compute Times')
    plt.show()

    plt.bar([i for i in range(7)], mean_request_code_network_times)
    plt.xlabel('request code')
    plt.xticks([i for i in range(7)])
    plt.ylabel('seconds')
    plt.title('Mean Request Code Network Times')
    plt.show()

    max_request_code_compute_times = [np.max(item) if len(item) > 0 else 0 for item in request_code_compute_times]
    max_request_code_network_times = [np.max(item) if len(item) > 0 else 0 for item in request_code_network_times]

    plt.bar([i for i in range(7)], max_request_code_compute_times)
    plt.xlabel('request code')
    plt.xticks([i for i in range(7)])
    plt.ylabel('seconds')
    plt.title('Max Request Code Compute Times')
    plt.show()

    plt.bar([i for i in range(7)], max_request_code_network_times)
    plt.xlabel('request code')
    plt.xticks([i for i in range(7)])
    plt.ylabel('seconds')
    plt.title('Max Request Code Network Times')
    plt.show()

# --------------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------------:data
# --------------------------------------------------------------------------------------------------

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