"""
An HTTP TURN server for demo-ing my game's 2p multiplayer.

The game uses Unreal engine 4.27. Players connect to this server and the server handles matchmaking
on a first-come-first-serve basis. Once players are paired, this server relays data between the
players. One player runs server + client and the other runs client only. Data is then 
hand-replicated and verified in the game, since data are sent without Unreal net code.

(1) Pairing Process:

Clients send http POST requests to the server's public IP + whatever port is specified at startup 
(or default port is 80). The requests are simple text formatted like so:

"[incoming symbol],[formatted data],[key]"

-- [incoming symbol]: Tells the server what the client wants, and what kind of formatted data to 
expect. All of these symbols can be found under the comment below reading "incoming symbols"

-- [formatted data]: Game data related to the incoming symbol, or nothing. If the incoming symbol is 
NOTIFY_REGISTER, the data will be a user name. If the incoming symbol is 
NOTIFY_GAME_UPDATE, the data will be game data. Otherwise, this field is unused.

-- [key]: If the incoming symbol is NOTIFY_REGISTER, the valid keys are '*' and 'bibbybabbis', which
respectively give a normal and a long amount of time to wait between requests. '*' is hard-coded,
so the latter is for debug purposes. For any other incoming symbol, the key represents the unique
pairing registry ID *or* game_registry ID supplied by the server.

examples:

0,Davey Jones,*
... or
2,,30
... or etc.

Players send these requests at a fixed interval in order to keep their registration alive.

Players are first registered and then they request to be paired. Once players are paired 
first-come-first-serve, they are moved from the pairing registry to the game registry.

# 4,K1/X2003.5/Y19.22,19
# ... or etc.

command line arguments are detailed above __main__

"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from threading import Timer
from sys import argv


#---------------------------------------------------------------------------------------------------
#-----------------------------------------------------------------------------------------:init vars
#---------------------------------------------------------------------------------------------------


#TODO: make more robust, don't allow too many requests from one IP address

PAIRING_MAX_KEYS = 100
pairing_registry = [None for i in range(PAIRING_MAX_KEYS)]
pairing_key_assign_ctr = [0]

GAME_MAX_KEYS = 100
game_registry = [None for i in range(GAME_MAX_KEYS)]
game_key_assign_ctr = [0]

purge_timeout = 15
bibbybabbis_timeout = 180
map_load_timeout = 30
verbose_update_time = 10

# -- internal symbols --

ROLE_NONE = 0
ROLE_SERVER = 1
ROLE_CLIENT = 2

STATUS_REGISTERED = 0
STATUS_PAIRED = 1
STATUS_LOADING = 2
STATUS_READY = 3
STATUS_PLAYING = 4

REGISTER_ME_KEY = -1
BIBBY_KEY = -2 # (debug) register with 'bibbybabbis' in the key field and get extra time to pair

# -- incoming symbols -- 

NOTIFY_REGISTER = 0
NOTIFY_UNREGISTER = 1
NOTIFY_REQUEST_PAIR = 2
NOTIFY_MAP_INIT = 3
NOTIFY_MAP_READY = 4

NOTIFY_GAME_UPDATE = 4
NOTIFY_GAME_QUIT = 5

# -- outgoing symbols -- 

C_MSG_REGISTER_OK = "0/0".encode('utf-8')
C_MSG_UNREGISTER_OK = "0/1".encode('utf-8')
C_MSG_PAIRING = "0/2".encode('utf-8')
C_MSG_START_SERVER = "0/3".encode('utf-8')
C_MSG_START_CLIENT = "0/4".encode('utf-8')
C_MSG_PARTNER_LOAD = "0/5".encode('utf-8')
C_MSG_START_PLAY = "0/5".encode('utf-8')

ERROR_BAD_CONTENT_LEN = "1/*".encode('utf-8')
ERROR_NO_POST_DATA = "2/*".encode('utf-8')
ERROR_NO_CLIENT_ADDRESS = "3/*".encode('utf-8')
ERROR_POST_DATA_FORMAT = "4/*".encode('utf-8')
ERROR_NOT_REGISTERED = "5/*".encode('utf-8')
ERROR_BAD_REGISTER_SYMBOL = "6/*".encode('utf-8')
ERROR_REGISTER_FAIL = "7/*".encode('utf-8')
ERROR_pairing_keep_alive_FAIL = "8/*".encode('utf-8')
ERROR_PARTNER_DROP = "9/2".encode('utf-8')
ERROR_DROPPED_BY_SERVER = "10/*".encode('utf-8')
ERROR_PAIRING_KEYS_MAXED = "11/*".encode('utf-8')
ERROR_GAME_KEYS_MAXED = "12/*".encode('utf-8')


#---------------------------------------------------------------------------------------------------
#--------------------------------------------------------------------------------------:class player
#---------------------------------------------------------------------------------------------------


class Player:

    def __init__(self, args):
        self.name = args[1]
        self.partner_key = -1
        self.bad_partner_keys = set()
        self.server_status = STATUS_REGISTERED
        self.role = ROLE_NONE
        self.address = args[2]
        self.timeout_len = args[3]
        self.timer = Timer(self.timeout_len, self.pairing_purge_entry, args=[args[0]])
        self.timer.start()


#---------------------------------------------------------------------------------------------------
#-----------------------------------------------------------------------------:class request handler
#---------------------------------------------------------------------------------------------------


class RequestHandler(BaseHTTPRequestHandler):

    # Unused
    def do_GET(self):
        self._set_response(200);


    def do_POST(self):
        dt = datetime.now().strftime("%d/%m/%y %H:%M:%S")
        try:
            content_length = int(self.headers['Content-Length'])
        except:
            log(f"{dt}\nERROR: bad content length")
            self._set_response(400)
            self.wfile.write(ERROR_BAD_CONTENT_LEN)
            return
        try:
            post_data = self.rfile.read(content_length).decode('utf-8')
        except:
            log(f"{dt}\nERROR: bad post data")
            self._set_response(400)
            self.wfile.write(ERROR_NO_POST_DATA)
            return
        try:
            ip_address = self.client_address[0]
        except:
            log(f"{dt}\nERROR: bad ip address\n{post_data}")
            self._set_response(400)
            self.wfile.write(ERROR_NO_CLIENT_ADDRESS)
            return;

        parse_validate_success, return_msg = self.parse_and_validate(post_data, ip_address)
        if not parse_validate_success:
            self._set_response(400)
        else:
            if self.notify_type <= NOTIFY_MAP_READY:
                pair_working, return_msg = self.pair_player(self)
                if pair_working:
                    self._set_response(200)
                else :
                    self._set_response(400)
            else:
                game_working, return_msg = self.game_update(self)
                if game_working:
                    self._set_response(200)
                else:
                    self._set_response(400)
        log(f"{dt}\n{return_msg.decode('utf-8')}\n{post_data}\n{ip_address}")
        self.wfile.write(return_msg)


    def parse_and_validate(self, post_data, ip_address):
        err_switch_unregistered = False
        try:
            data_parts = post_data.split(",")
            self.notify_type = int(data_parts[0])
            assert 0 <= self.notify_type <= NOTIFY_GAME_QUIT
            self.name = data_parts[1]
            _key = data_parts[2]

            self.player = None
            if self.notify_type == NOTIFY_REGISTER:
                if _key == '*':
                    self.key = REGISTER_ME_KEY
                elif _key == 'bibbybabbis':
                    self.key = BIBBY_KEY
                else:
                    return False, ERROR_POST_DATA_FORMAT
            else:
                self.key = int(_key)
                assert 0 <= self.key < pairing_key_assign_ctr[0]
                self.player = pairing_registry[self.key]
                err_switch_unregistered = (self.player == None)
        except:
            return False, ERROR_POST_DATA_FORMAT
        if err_switch_unregistered:
            return False, ERROR_NOT_REGISTERED
        
        self.ip_address = ip_address
        return True, ''


    def pair_player(self):
        if self.notify_type == NOTIFY_REGISTER:
            if self.key != REGISTER_ME_KEY and self.key != BIBBY_KEY:
                return False, ERROR_BAD_REGISTER_SYMBOL
            if (pairing_key_assign_ctr[0] >= PAIRING_MAX_KEYS):
                return False, ERROR_PAIRING_KEYS_MAXED
            try:
                in_key = self.key
                self.key = pairing_key_assign_ctr[0]
                pairing_key_assign_ctr[0] += 1
                while pairing_key_assign_ctr[0] < PAIRING_MAX_KEYS \
                and pairing_registry[pairing_key_assign_ctr[0]] != None:
                    pairing_key_assign_ctr[0] += 1
                if in_key == REGISTER_ME_KEY: 
                    pairing_registry[self.key] = \
                        Player((self.key, self.name, self.ip_address, purge_timeout))
                else:
                    pairing_registry[self.key] = \
                        Player((self.key, self.name, self.ip_address, bibbybabbis_timeout))
                return True, C_MSG_REGISTER_OK
            except:
                return False, ERROR_REGISTER_FAIL
        else:
            player = self.player
            if self.notify_type == NOTIFY_REQUEST_PAIR:
                if player.server_status == STATUS_REGISTERED:
                    restarted_timer = pairing_keep_alive(self.key)
                    if not restarted_timer:
                        pairing_purge_entry(self.key)
                        return False, ERROR_pairing_keep_alive_FAIL
                    for partner_key in range(0, pairing_key_assign_ctr[0]):
                        partner = pairing_registry[partner_key]
                        if partner_key != self.key \
                        and partner is not None \
                        and partner.server_status == STATUS_REGISTERED \
                        and self.key not in partner.bad_partner_keys \
                        and partner_key not in player.bad_partner_keys:
                            player.partner_key = partner_key
                            partner.partner_key = self.key
                            player.server_status = STATUS_PAIRED
                            partner.server_status = STATUS_PAIRED
                            player.role = ROLE_SERVER
                            partner.role = ROLE_CLIENT
                            return True, C_MSG_START_SERVER
                    return True, C_MSG_PAIRING
                elif player.server_status == STATUS_PAIRED:
                    restarted_timer = pairing_keep_alive(self.key)
                    if not restarted_timer:
                        pairing_purge_entry(self.key)
                        return False, ERROR_pairing_keep_alive_FAIL
                    if pairing_registry[player.partner_key] is None:
                        self.partner_drop_reset(player)
                        return False, ERROR_PARTNER_DROP
                    elif player.role == ROLE_CLIENT:
                        return True, C_MSG_START_CLIENT
                    else:
                        return True, C_MSG_START_SERVER # just in case they didn't get the msg
            elif self.notify_type == NOTIFY_MAP_INIT and player.server_status == STATUS_PAIRED:
                restarted_timer = pairing_keep_alive(self.key, map_load_timeout)
                if not restarted_timer:
                    pairing_purge_entry(self.key)
                    return False, ERROR_pairing_keep_alive_FAIL
                player.server_status = STATUS_LOADING
                if pairing_registry[player.partner_key] is None:
                    self.partner_drop_reset(player)
                    return False, ERROR_PARTNER_DROP
                elif player.role == ROLE_CLIENT:
                    return True, C_MSG_START_CLIENT
                else:
                    return True, C_MSG_START_SERVER 
            elif self.notify_type == NOTIFY_MAP_READY:
                restarted_timer = pairing_keep_alive(self.key, map_load_timeout)
                if not restarted_timer:
                    pairing_purge_entry(self.key)
                    return False, ERROR_pairing_keep_alive_FAIL
                partner = pairing_registry[player.partner_key]
                if partner is None:
                    self.partner_drop_reset(player)
                    return False, ERROR_PARTNER_DROP
                if player.server_status == STATUS_LOADING or player.server_status == STATUS_READY:
                    if partner.server_status == STATUS_READY:
                        player.server_status = STATUS_PLAYING
                        partner.server_status = STATUS_PLAYING
                        return True, C_MSG_START_PLAY
                    else:
                        player.server_status = STATUS_READY
                        return True, C_MSG_PARTNER_LOAD
                elif player.server_status == STATUS_PLAYING:
                    return True, C_MSG_START_PLAY

        # gets NOTIFY_UNREGISTER and other potential client-server misaligned cases
        pairing_purge_entry(self.key)
        return False, ERROR_DROPPED_BY_SERVER


    def game_update(self):
        pass


    def partner_drop_reset(self, player):
        player.bad_partner_keys.add(player.partner_key)
        player.partner_key = -1
        player.server_status = STATUS_REGISTERED
        player.role = ROLE_NONE

    
    def _set_response(self, val):
        self.send_response(val)
        self.send_header('Content-type', 'text/html')
        self.end_headers()


#---------------------------------------------------------------------------------------------------
#----------------------------------------------------------------------------------:helper functions
#---------------------------------------------------------------------------------------------------


def pairing_purge_entry(key):
    pairing_registry[key].timer.cancel()
    pairing_registry[key] = None
    if key < pairing_key_assign_ctr[0]:
        pairing_key_assign_ctr[0] = key


def pairing_keep_alive(key, timeout=0):
    try:
        entry = pairing_registry[key]
        entry.timer.cancel()
        if timeout > 0:
            timer = Timer(timeout, pairing_purge_entry, args=[key])
        else:
            timer = Timer(entry.timeout_len, pairing_purge_entry, args=[key])
        entry.timer = timer
        return True
    except:
        return False


def log(info):
    with open('log.txt', 'a') as f:
        f.write(f'{info}\n---\n')


def print_registry():
    print(f'pairing registry:')
    for key in range(PAIRING_MAX_KEYS):
        client_data = pairing_registry[key]
        if client_data is not None:
            print(f'{key}: {pairing_registry[key]}')
    print('---')
    Timer(verbose_update_time, print_registry).start()


#---------------------------------------------------------------------------------------------------
#----------------------------------------------------------------------------------------------:main
#---------------------------------------------------------------------------------------------------


VA_HELP = 0
VA_PORT = 1
VA_VERBOSE = 2

valid_argnames = (("-h", "--help"), ("-p", "--port"), ("-v", "--verbose"))
valid_argnames_info = (
    "see names and explanations of arguments",
    "specifies the port on which the server will listen", 
    f"prints out connected clients every {verbose_update_time} seconds"
)

ERRNAME_BAD_ARGNAME = """
------------
__main__(): ERROR: malformed arg name
example(1): python webserver.py 
(creates an http server that listens on port 8000 by default)
example(2): python3 webserver.py --help
(see valid arguments)
------------
"""
VALID_ARGS = \
    "------------\n" + "".join([
        f"{valid_argnames[i][0]}, {valid_argnames[i][1]} :\t{valid_argnames_info[i]}\n" 
        for i in range(len(valid_argnames))
    ]) + "------------\n"
ERRNAME_PORT_MALFORMED = """
------------
__main__(): ERROR: malformed port arg value
example(1): python3 webserver.py --port 22
(creates an http server that listens on port 22, specifies python3)
------------
"""


if __name__ == '__main__':
    with open('log.txt', 'w') as f:
        pass # overwriting previous log file

    # -- default args --
    port = 80
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
            elif argv[i] in valid_argnames[VA_HELP]:
                print(VALID_ARGS)
                i += 1
            else:
                print(ERRNAME_BAD_ARGNAME)
                exit(1)
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
