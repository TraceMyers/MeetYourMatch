from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from threading import Timer
from sys import argv

#TODO: make more robust, don't allow too many requests from one IP address

MAX_KEYS = 10000
key_in_use = [False for _ in range(MAX_KEYS)]
registry = {i:None for i in range(MAX_KEYS)}
key_assign_ctr = [0]
request_types = [f'{i}' for i in range(5)]
purge_timeout = 20
bibbybabbis_timeout = 180

REQ_REGISTER = 0
REQ_PAIR_REQUEST = 1

SERVER = 0
CLIENT = 1
NONE = 2

REQUEST_PAIRING_REGISTER = '0'
REQUEST_PAIRING_UNREGISTER = '1'
REQUEST_PAIR = '2'
REQUEST_INIT_SUCCESS = '3'
REQUEST_SEND_GAME_UPDATE = '4'
REQUEST_RECEIVE_GAME_UPDATE = '5'


def log(info):
    with open('log.txt', 'a') as f:
        f.write(f'{info}\n---\n')


class RequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self._set_response(200);


    def do_POST(self):
        dt = datetime.now().strftime("%d/%m/%y %H:%M:%S")
        try:
            content_length = int(self.headers['Content-Length'])
        except:
            log(f"{dt}\nERROR: could not get content length")
            self._set_response(400)
            self.wfile.write("/ERROR,/1:no len".encode('utf-8'))
            return
        try:
            post_data = self.rfile.read(content_length).decode('utf-8')
        except:
            log(f"{dt}\nERROR: could not get post data")
            self._set_response(400)
            self.wfile.write("/ERROR,/2:no post".encode('utf-8'))
            return
        try:
            ip_address = self.client_address[0]
        except:
            log(f"{dt}\nERROR: could not get ip address\n{post_data}")
            self._set_response(400)
            self.wfile.write("/ERROR,/3:no ip".encode('utf-8'))
            return;

        react_success, return_msg = self.react(post_data, ip_address)
        if not react_success:
            self._set_response(400)
        else :
            self._set_response(200)
        log(f"{dt}\n{return_msg}\n{post_data}\n{ip_address}")
        self.wfile.write(return_msg.encode('utf-8'))

    def react(self, post_data, ip_address):
        try:
            data_parts = post_data.split(",")
            request_type = data_parts[0]
            assert request_type in request_types
            name = data_parts[1]
            key = data_parts[2]
            if key != '*' and key != 'bibbybabbis':
                key = int(key)
                assert 0 <= key < MAX_KEYS
        except:
            return False, "/ERROR,/4:post data not formatted correctly"
        
        if request_type != "register" and (key not in registry or key_in_use[key] == False):
            return False, "/ERROR,/5:client did not register first"
        return_msg = ""

        if request_type == "pair fail":
            request_type = "pair request"
            registry[key][3].add(registry[key][2])
            registry[key][2] = None
            registry[key][4] = REQ_PAIR_REQUEST
            registry[key][5] = NONE
        elif request_type == "unregister":
            self.purge_entry(key)
            return True, '/self drop,/'

        if request_type == "register":
            if key != '*' and key != 'bibbybabbis':
                return False, "/ERROR,/6:can't register with key"
            try:
                assert key_assign_ctr[0] < MAX_KEYS
                key = key_assign_ctr[0]
                key_in_use[key] = True
                key_assign_ctr[0] += 1
                while key_assign_ctr[0] < MAX_KEYS and key_in_use[key_assign_ctr[0]]:
                    key_assign_ctr[0] += 1
                if key == '*':
                    timer = Timer(purge_timeout, self.purge_entry, args=[key])
                    registry[key] = [name, timer, None, set(), REQ_REGISTER, NONE, ip_address, timeout_len == bibbybabbis_timeout]
                else:
                    timer = Timer(bibbybabbis_timeout, self.purge_entry, args=[key])
                    registry[key] = [name, timer, None, set(), REQ_REGISTER, NONE, ip_address, timeout_len == bibbybabbis_timeout]
                timer.start()
                return_msg = f"/register OK,/{key}"
            except:
                return False, "/ERROR,/7:server registration failure"
        elif request_type == "pair request" \
        and (registry[key][4] == REQ_PAIR_REQUEST or registry[key][4] == REQ_REGISTER):
            restarted_timer = self.keep_alive(key)
            if not restarted_timer:
                return False, "/ERROR,/8:could not keep alive(1)"
            registry[key][4] = REQ_PAIR_REQUEST
            found_other = False
            for other_key in range(0, key_assign_ctr[0]):
                if other_key != key and key_in_use[other_key]:
                    if registry[other_key][4] == REQ_PAIR_REQUEST \
                    and key not in registry[other_key][3] \
                    and other_key not in registry[key][3]:
                        registry[key][2] = other_key
                        registry[other_key][2] = key
                        registry[key][4] = REQ_ATTEMPTING_PAIR
                        registry[other_key][4] = REQ_ATTEMPTING_PAIR
                        registry[key][5] = SERVER
                        registry[other_key][5] = CLIENT
                        found_other = True
                        return_msg = f"/server,/{registry[other_key][0]}"
                        break
            if not found_other:
                return_msg = "/pairing,/"
        elif registry[key][4] == REQ_ATTEMPTING_PAIR:
            restarted_timer = self.keep_alive(key)
            if not restarted_timer:
                return False, "/ERROR,/8:could not keep alive(2)"
            other_key = registry[key][2]
            if other_key in registry and registry[other_key][2] == key:
                if registry[key][5] == SERVER:
                    return_msg = f"/server,/{registry[other_key][0]}"
                else:
                    return_msg = f"/client,/{registry[other_key][0]}/{registry[other_key][6]}"
            else:
                registry[key][2] = None
                registry[key][4] = REQ_PAIR_REQUEST
                registry[key][5] = NONE
                return_msg = "/partner drop,/"
        else:
            return False, "/ERROR,/9:bad request"

        return True, return_msg

    def purge_entry(self, key):
        try:
            registry[key][1].cancel()
            registry[key] = None
            key_in_use[key] = False
            if key < key_assign_ctr[0]:
                key_assign_ctr[0] = key
        except:
            pass

    def keep_alive(self, key):
        try:
            registry[key][1].cancel()
            bibbybabbis = registry[key][7]
            if bibbybabbis:
                timeout_len = bibbybabbis_timeout
            else:
                timeout_len = purge_timeout
            timer = Timer(timeout_len, self.purge_entry, args=[key])
            name = registry[key][0]
            pair_address = registry[key][2]
            pair_failures = registry[key][3]
            current_request = registry[key][4]
            connection_type = registry[key][5]
            ip_address = registry[key][6]
            registry[key] = [
                name, 
                timer, 
                pair_address, 
                pair_failures, 
                current_request, 
                connection_type,
                ip_address,
                bibbybabbis
            ]
            timer.start()
            return True
        except:
            return False

    def _set_response(self, val):
        self.send_response(val)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

verbose_update_time = 9
def print_registry():
    print(f'registry:')
    for key in registry.keys():
        client_data = registry[key]
        if client_data is not None:
            print(f'{key}: {registry[key]}')
    print('---')
    Timer(verbose_update_time, print_registry).start()


VA_PORT = 0
VA_VERBOSE = 1
valid_argnames = (("-p", '--port'), ("-v", '--verbose'))
valid_argnames_info = (
    "specifies the port on which the server will listen", 
    f"prints out connected clients every {verbose_update_time} seconds"
)

ERRNAME_BAD_ARGNAME = """
------------
__main__(): ERROR: malformed arg name
example(1): python webserver.py
(creates an http server that listens on port 8000 by default)
example(2): python3 webserver.py -p 22
(creates an http server that listens on port 22, specifies python3)
------------
"""
ERRNAME_BAD_ARGNAME_VALID_ARGS = \
    "------------\n" + "".join([
        f"{valid_argnames[i][0]}, {valid_argnames[i][1]} :\t{valid_argnames_info[i]}\n" 
        for i in range(len(valid_argnames))
    ]) + "------------\n"
ERRNAME_PORT_MALFORMED = """
------------
__main__(): ERROR: malformed port arg value
example(1): python webserver.py -p 80
(creates an http server that listens on port 80)
example(2): python3 webserver.py --port 22
(creates an http server that listens on port 22, specifies python3)
------------
"""


if __name__ == '__main__':
    with open('log.txt', 'w') as f:
        pass
    port = 8000
    verbose = False

    arg_ct = len(argv)
    if arg_ct > 1:
        i = 1
        while True:
            if argv[i] in valid_argnames[VA_PORT]:
                i += 1
                if i >= arg_ct:
                    print(ERRNAME_PORT_MALFORMED)
                    exit(1)
                try:
                    port = int(argv[i])
                    i += 1
                except:
                    print(ERRNAME_PORT_MALFORMED)
                    exit(1)
            elif argv[i] in valid_argnames[VA_VERBOSE]:
                verbose = True
                i += 1
            else:
                print(ERRNAME_BAD_ARGNAME)
                print(ERRNAME_BAD_ARGNAME_VALID_ARGS)
                quit(1)
            if i >= arg_ct:
                break

    server = HTTPServer(('', port), RequestHandler)
    print(f'server running on port {port}, verbose={"true" if verbose else "false"}')
    if verbose:
        print_registry()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
