"""
A Simple HTTP TURN server for demo-ing my game's 2p multiplayer.

Players connect to this server and the server handles matchmaking on a first-come-first-serve basis. 
Once players are paired, this server relays data between the players. One player runs server + 
client and the other runs client only. Data is then hand-replicated and verified in the game, 
since data are sent with text.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from threading import Timer
from sys import argv


#---------------------------------------------------------------------------------------------------
#-----------------------------------------------------------------------------------------:init vars
#---------------------------------------------------------------------------------------------------


#TODO: make more robust, don't allow too many requests from one IP address
#TODO: unsafe states - susceptible to spam; should create hashes for keys

PAIRING_MAX_KEYS = 100
pairing_registry = [None for i in range(PAIRING_MAX_KEYS)]
pairing_key_assign_ctr = [0]

GAME_MAX_KEYS = 100
game_registry = [None for i in range(GAME_MAX_KEYS)]
game_key_assign_ctr = [0]

purge_timeout = 15
bibbybabbis_timeout = 180
map_load_timeout = 30
game_timeout = 30
verbose_update_time = 10

# -- internal symbols --

ROLE_NONE = 0
ROLE_SERVER = 1
ROLE_CLIENT = 2

STATUS_REGISTERED = 0
STATUS_PAIRED = 1
STATUS_LOADING = 2
STATUS_READY = 3
STATUS_PLAYING_INIT = 4
STATUS_PLAYING = 5

REGISTER_ME_KEY = -1
BIBBY_KEY = -2 # (debug) register with 'bibbybabbis' in the key field and get extra time to pair

# -- incoming symbols -- 

NOTIFY_REGISTER = 0
NOTIFY_UNREGISTER = 1
NOTIFY_REQUEST_PAIR = 2
NOTIFY_MAP_INIT = 3
NOTIFY_MAP_READY = 5

NOTIFY_GAME_UPDATE = 6
NOTIFY_GAME_QUIT = 7

# -- outgoing symbols -- 

C_MSG_REGISTER_OK = "0/0/"
C_MSG_UNREGISTER_OK = "0/1/*".encode('utf-8')
C_MSG_PAIRING = "0/2/*".encode('utf-8')
C_MSG_START_SERVER = "0/3/"
C_MSG_START_CLIENT = "0/4/"
C_MSG_INIT_SERVER = "0/5/".encode('utf-8')
C_MSG_INIT_CLIENT = "0/6/".encode('utf-8')
C_MSG_PARTNER_LOAD = "0/7/*".encode('utf-8')
C_MSG_START_PLAY = "0/8/"
C_MSG_GAME_DATA = "0/9/"
C_MSG_GAME_NO_DATA = "0/10/*".encode('utf-8')

ERROR_BAD_CONTENT_LEN = "1/*/*".encode('utf-8')
ERROR_NO_POST_DATA = "2/*/*".encode('utf-8')
ERROR_NO_CLIENT_ADDRESS = "3/*/*".encode('utf-8')
ERROR_POST_DATA_FORMAT = "4/*/*".encode('utf-8')
ERROR_NOT_REGISTERED = "5/*/*".encode('utf-8')
ERROR_BAD_REGISTER_SYMBOL = "6/*/*".encode('utf-8')
ERROR_REGISTER_FAIL = "7/*/*".encode('utf-8')
ERROR_KEEP_ALIVE_FAIL = "8/*/*".encode('utf-8')
ERROR_PARTNER_DROP = "9/2/*".encode('utf-8')
ERROR_DROPPED_BY_SERVER = "10/*/*".encode('utf-8')
ERROR_PAIRING_KEYS_MAXED = "11/*/*".encode('utf-8')
ERROR_GAME_KEYS_MAXED = "12/*/*".encode('utf-8')
ERROR_NO_GAME = "13/*/*".encode('utf-8')
ERROR_NO_PLAYER_SELF = "14/*/*".encode('utf-8')
ERROR_NO_PLAYER_PARTNER = "15/*/*".encode('utf-8')


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
        self.timer = Timer(self.timeout_len, pairing_purge_entry, args=[args[0]])
        self.timer.start()
        self.pairing_key = args[0]
        self.game_key = None


class Game:

    def __init__(self, args):
        self.players = [args[1], args[2]]
        self.data = [[[], ''], [[], '']]
        self.recieved_switch[False, False]
        self.updated = [False, False]
        self.purged_pairing_entries = False
        self.timer = Timer(game_timeout, game_purge_entry, args=[args[0]])
        self.timer.start()
        self.ga


#---------------------------------------------------------------------------------------------------
#-----------------------------------------------------------------------------:class request handler
#---------------------------------------------------------------------------------------------------


class GameNotifyHandler(BaseHTTPRequestHandler):

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
            self.post_data = data_parts[1]
            _key = data_parts[2]
            self.player_key = int(data_parts[3])
            assert self.player_key == 0 or self.player_key == 1
            self.recieved_switch = int(data_parts[4])
            assert self.recieved_switch == 0 or self.recieved_switch == 1

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
                        Player((self.key, self.post_data, self.ip_address, purge_timeout))
                else:
                    pairing_registry[self.key] = \
                        Player((self.key, self.post_data, self.ip_address, bibbybabbis_timeout))
                return True, f"{C_MSG_REGISTER_OK}/{self.key}".encode('utf-8')
            except:
                return False, ERROR_REGISTER_FAIL
        else:
            player = self.player
            if self.notify_type == NOTIFY_REQUEST_PAIR:
                if player.server_status == STATUS_REGISTERED:
                    restarted_timer = pairing_keep_alive(self.key)
                    if not restarted_timer:
                        pairing_purge_entry(self.key)
                        return False, ERROR_KEEP_ALIVE_FAIL
                    for partner_key in range(pairing_key_assign_ctr[0]):
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
                            return True, f'{C_MSG_START_SERVER}{partner.name}'.encode('utf-8')
                    return True, C_MSG_PAIRING
                elif player.server_status == STATUS_PAIRED:
                    pair_valid, msg, partner = self.pair_validate(player)
                    if not pair_valid:
                        return False, msg   
                    if player.role == ROLE_CLIENT:
                        return True, f'{C_MSG_START_CLIENT}{partner.name}'.encode('utf-8')
                    else:
                        # just in case they didn't get the msg
                        return True, f'{C_MSG_START_SERVER}{partner.name}'.encode('utf-8')
            elif self.notify_type == NOTIFY_MAP_INIT and player.server_status == STATUS_PAIRED:
                pair_valid, msg, partner = self.pair_validate(player)
                if not pair_valid:
                    return False, msg
                player.server_status = STATUS_LOADING
                if player.role == ROLE_CLIENT:
                    return True, C_MSG_INIT_CLIENT
                else:
                    return True, C_MSG_INIT_SERVER 
            elif self.notify_type == NOTIFY_MAP_READY:
                pair_valid, msg, partner = self.pair_validate(player)
                if not pair_valid:
                    return False, msg
                if player.server_status == STATUS_LOADING or player.server_status == STATUS_READY:
                    if partner.server_status == STATUS_READY:
                        if game_key_assign_ctr[0] >= GAME_MAX_KEYS:
                            pairing_purge_entry(player)
                            pairing_purge_entry(partner)
                            return False, ERROR_GAME_KEYS_MAXED
                        else:
                            game_key = prepare_game(player, partner)
                            player.server_status = STATUS_PLAYING_INIT
                            partner.server_status = STATUS_PLAYING_INIT
                            return True, f'{C_MSG_START_PLAY}{game_key}0'.encode('utf-8')
                    else:
                        player.server_status = STATUS_READY
                        return True, C_MSG_PARTNER_LOAD
                elif player.server_status == STATUS_PLAYING_INIT:
                    msg = f'{C_MSG_START_PLAY}{player.game_key[0]}{player.game_key[1]}'
                    return True, msg.encode('utf-8')

        # gets NOTIFY_UNREGISTER and other potential client-server misaligned cases
        pairing_purge_entry(self.key)
        return False, ERROR_DROPPED_BY_SERVER


    def pair_validate(self, player):
        restarted_timer = pairing_keep_alive(self.key, map_load_timeout)
        if not restarted_timer:
            pairing_purge_entry(self.key)
            return False, ERROR_KEEP_ALIVE_FAIL, None
        partner = pairing_registry[player.partner_key]
        if partner is None:
            partner_drop_reset(player)
            return False, ERROR_PARTNER_DROP, None
        return True, None, partner


    def game_update(self):
        game_valid, msg = self.game_validate() 
        if not game_valid:
            return False, msg
            
        self.game.updated[self.player_key] = True
        self.game.data[self.player_key][0].append(self.post_data)

        partner_data_buffer = self.game.data[self.partner_key]
        recieved_back_buffer = self.recieved_switch == self.game.recieved_switch[self.player_key]
        if len(partner_data_buffer[1]) > 0:
            if recieved_back_buffer:
                partner_data = ''
            else:
                partner_data = partner_data_buffer[1]
        else:
            partner_data = ''

        if self.game.updated[self.partner_key]:
            if not self.game.purged_pairing_entries:
                pairing_purge_entry(self.player.pairing_key)
                pairing_purge_entry(self.partner.pairing_key)
                self.player.server_status = STATUS_PLAYING
                self.partner.server_status = STATUS_PLAYING
                self.game.purged_pairing_entries = True
            
            new_data_str = '|'.join(self.game.data[self.partner_key][0])
            partner_data += new_data_str

            if recieved_back_buffer:
                self.game.data[self.partner_key][1] = new_data_str
                self.game.received_switch = 0 if self.game.recieved_switch == 1 else 0
            else:
                self.game.data[self.partner_key][1] += new_data_str
            self.game.updated[self.partner_key] = False
            self.game.data[self.partner_key][0].clear()

            return True, f'{C_MSG_GAME_DATA}{partner_data}'.encode('utf-8')
        elif recieved_back_buffer:
            return True, C_MSG_GAME_NO_DATA
        return True, f'{C_MSG_GAME_DATA}{partner_data}'.encode('utf-8')
            

    def game_validate(self):
        self.game = game_registry[self.key]
        if self.game is None:
            return False, ERROR_NO_GAME
        self.player = self.game.players[self.player_key]
        if self.player is None:
            game_purge_entry(self.key)
            return False, ERROR_NO_PLAYER_SELF
        self.partner_key = (0 if self.player_key == 1 else 0)
        self.partner = self.game.players[self.partner_key]
        if self.partner is None:
            game_purge_entry(self.key)
            return False, ERROR_NO_PLAYER_PARTNER
        return True, 0


    def _set_response(self, val):
        self.send_response(val)
        self.send_header('Content-type', 'text/html')
        self.end_headers()


#---------------------------------------------------------------------------------------------------
#----------------------------------------------------------------------------------:helper functions
#---------------------------------------------------------------------------------------------------


def partner_drop_reset(player):
    player.bad_partner_keys.add(player.partner_key)
    player.partner_key = -1
    player.server_status = STATUS_REGISTERED
    player.role = ROLE_NONE


def prepare_game(player, partner):
    game_key = game_key_assign_ctr[0]
    game_registry[game_key] = Game(game_key, player, partner)
    player.game_key = (game_key, 0)
    partner.game_key = (game_key, 1)

    game_key_assign_ctr[0] += 1
    while game_key_assign_ctr[0] < GAME_MAX_KEYS \
    and game_registry[game_key_assign_ctr[0]] != None:
        game_key_assign_ctr[0] += 1

    return game_key


def pairing_purge_entry(key):
    pairing_registry[key].timer.cancel()
    # releasing player timer memory 'directly' since otherwise players would hold onto pairing 
    # timers when games start
    pairing_registry[key].timer = None 
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


def game_purge_entry(key):
    game_registry[key].timer.cancel()
    game_registry[key] = None
    if key < game_key_assign_ctr[0]:
        game_key_assign_ctr[0] = key


def game_keep_alive(key):
    try:
        entry = game_registry[key]
        entry.timer.cancel()
        timer = Timer(game_timeout, game_purge_entry, args=[key])
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

    server = HTTPServer(('', port), GameNotifyHandler)
    print(f'server running on port {port}, verbose={"true" if verbose else "false"}')
    if verbose:
        print_registry()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
