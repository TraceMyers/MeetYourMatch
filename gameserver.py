"""
A meticulous and lightweight HTTP TURN server for demo-ing my game's 2p multiplayer. 

It isn't made to be extended or generalized - only to exactly suit the needs of my game. However, it 
may be useful to you if you want a two client data relay with matchmaking that is fairly simple and 
has a multiple-step synchronization validation process during user connection.

The server handles two-player matchmaking on a first-come-first-serve basis as well as pre-paired 
sessions. Once players are paired, this server relays data between the players. The language of the 
C_MSG codes below assumes a client-server architecture wherein one player runs the game server & 
client, and the other runs client only. However, this server makes (almost) no assumptions about the
data being passed between players. So, your game or application could employ a p2p model, then treat 
C_MSG_START_SERVER and C_MSG_START_CLIENT as meaning the same thing.

By validating client state, the server supports sending data that represents changes to the game/app
state. So, the entire state of the dataset does not always need to be sent. It does so by
accruing data from one's partner until one's player_state changes. The data cache will stop growing 
at a maximum of MAX_CACHE_LEN, at which point 'change only' data is no longer valid.
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

MAX_CONTENT_LEN = 4096
MAX_CACHE_LEN = 16384

PAIRING_MAX_KEYS = 100
pairing_registry = [None for i in range(PAIRING_MAX_KEYS)]
pairing_key_assign_ctr = [0]

GAME_MAX_KEYS = 100
game_registry = [None for i in range(GAME_MAX_KEYS)]
game_key_assign_ctr = [0]
game_msg_table = [[[-1, None, 0], [-1, None, 0]] for i in range(GAME_MAX_KEYS)]

purge_timeout = 20
bibbybabbis_timeout = 180
map_load_timeout = 45
game_timeout = 30
verbose_update_time = 10

# -- internal symbols --

TABLE_NONE =    0
TABLE_GAME =    2

ROLE_NONE =     0
ROLE_SERVER =   1
ROLE_CLIENT =   2

STATUS_REGISTERED =     0
STATUS_PAIRED =         1
STATUS_LOADING =        2
STATUS_READY =          3
STATUS_PLAYING_INIT =   4
STATUS_PLAYING =        5

REGISTER_ME_KEY =   -1
BIBBY_KEY =         -2 # debug cheat code, adds time to pairing timeout

# -- incoming symbols -- 

NOTIFY_REGISTER =       0
NOTIFY_UNREGISTER =     1
NOTIFY_REQUEST_PAIR =   2
NOTIFY_MAP_INIT =       3
NOTIFY_MAP_READY =      4
NOTIFY_GAME_QUIT =      5
NOTIFY_GAME_UPDATE =    6

# -- outgoing symbols -- 

C_MSG_REGISTER_OK =     "0/0/"
C_MSG_UNREGISTER_OK =   "0/1/*\n"
C_MSG_PAIRING =         "0/2/*\n"
C_MSG_START_SERVER =    "0/3/"
C_MSG_START_CLIENT =    "0/4/"
C_MSG_INIT_SERVER =     "0/5/"
C_MSG_INIT_CLIENT =     "0/6/"
C_MSG_PARTNER_LOAD =    "0/7/*\n"
C_MSG_START_PLAY =      "0/8/"
C_MSG_GAME_DATA =       "0/9/"
C_MSG_GAME_NO_DATA =    "0/10/*\n"

ERROR_BAD_CONTENT_LEN =     "1/*/*\n"
ERROR_NO_POST_DATA =        "2/*/*\n"
ERROR_NO_CLIENT_ADDRESS =   "3/*/*\n"
ERROR_POST_DATA_FORMAT =    "4/*/*\n"
ERROR_NOT_REGISTERED =      "5/*/*\n"
ERROR_BAD_REGISTER_SYMBOL = "6/*/*\n"
ERROR_REGISTER_FAIL =       "7/*/*\n"
ERROR_KEEP_ALIVE_FAIL =     "8/*/*\n"
ERROR_PARTNER_DROP =        "9/2/*\n"
ERROR_DROPPED =             "10/*/*\n"
ERROR_PAIRING_KEYS_MAXED =  "11/*/*\n"
ERROR_GAME_KEYS_MAXED =     "12/*/*\n"
ERROR_NO_GAME =             "13/*/*\n"
ERROR_NO_PLAYER_SELF =      "14/*/*\n"
ERROR_NO_PLAYER_PARTNER =   "15/*/*\n"
ERROR_BAD_PARTNER_NAME =    "16/*/*\n"
ERROR_KNOWN_PARTNER_DROP =  "17/*/*\n"
ERROR_PLAYER_STATE_BEHIND = "18/*/*\n"
ERROR_PLAYER_STATE_AHEAD =  "19/*/*\n"
ERROR_OVER_CONTENT_LEN =    "20/*/*\n"
ERROR_GAME_CACHE_MAXED =    "21/*/"


#---------------------------------------------------------------------------------------------------
#--------------------------------------------------------------------------------------:class player
#---------------------------------------------------------------------------------------------------


class Player:

    def __init__(self, args):
        self.name = args[1]
        self.partner_key = -1
        self.partner_name = None
        self.bad_partner_names = set() # any partner who previously dropped during pairing
        self.server_status = STATUS_REGISTERED
        self.role = ROLE_NONE
        self.address = args[2]
        self.timeout_len = args[3]
        self.timer = Timer(self.timeout_len, pairing_purge_entry, args=[args[0]])
        self.timer.start()
        self.pairing_key = args[0]
        self.game_key = None

    def __repr__(self):
        pre_paired_partner = '*' if self.partner_name == None else self.partner_name
        return (
            f'{self.name} / {self.address} / server_status={self.server_status}'
            f' / join partner={pre_paired_partner} / partner key={self.partner_key}'
        )

    def _role(self):
        if self.role == ROLE_SERVER:
            return "server"
        if self.role == ROLE_CLIENT:
            return "client"
        return "none"


#---------------------------------------------------------------------------------------------------
#----------------------------------------------------------------------------------------:class game
#---------------------------------------------------------------------------------------------------


class Game:

    def __init__(self, args):
        self.players = [args[1], args[2]]
        self.data = [[], []]
        self.player_state[0, 0]
        self.updated = [False, False]
        self.purged_pairing_entries = False
        self.timer = Timer(game_timeout, game_purge_entry, args=[args[0]])
        self.timer.start()

    def __repr__(self):
        p0 = self.players[0]
        p0_updated = 'yes' if self.updated[0] else 'no'
        p1 = self.players[1]
        p1_updated = 'yes' if self.updated[1] else 'no'
        return (
            f'P0: {p0.name} / {p0.address} / {p0._role()} / state={self.player_state[0]}'
            f' / updated={p0_updated}\n'
            f'data="{self.data[0]}"\n'
            f'P1: {p1.name} / {p1.address} / {p1._role()} / state={self.player_state[1]}'
            f' / updated={p0_updated}\n'
            f'data="{self.data[1]}"'
        )


#---------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------:class game notify handler
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
        if content_length > MAX_CONTENT_LEN:
            log(f"{dt}\nERROR: over content length")
            self._set_response(400)
            self.wfile.write(ERROR_OVER_CONTENT_LEN)
            return;
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

        http_response = 400
        record_to = TABLE_NONE
        parse_validate_success, return_msg = self.parse_and_validate(post_data, ip_address)

        if parse_validate_success:
            if self.notify_type >= NOTIFY_GAME_QUIT:
                # a table for sending the same data + new data back if we get the same message in, as 
                # well as validating the states of the players during data transfer
                table_entry = game_msg_table[self.key][self.player_key]
                if self.player_state == table_entry[0]:
                    return_msg = self.game_redundant_msg_update(table_entry)
                    http_response = table_entry[2]
                elif self.player_state > table_entry[0] + 1:
                    return_msg = ERROR_PLAYER_STATE_AHEAD
                elif self.player_state < table_entry[0]:
                    return_msg = ERROR_PLAYER_STATE_BEHIND
                else:
                    game_working, return_msg = self.game_update()
                    if game_working:
                        record_to = TABLE_GAME
                        http_response = 200
            else:
                pair_working, return_msg = self.pair_player()
                if pair_working:
                    self._set_response(200)
                        
        log(f"{dt}\n{return_msg}\n{post_data}\n{ip_address}")

        if record_to == TABLE_GAME and game_working:
            table_entry = game_msg_table[self.key][self.player_key]
            table_entry[0] += 1
            table_entry[1] = return_msg
            table_entry[2] = http_response

        self.wfile.write(return_msg.encode('utf-8'))
        self._set_response(http_response)


    def parse_and_validate(self, post_data, ip_address):
        err_switch_unregistered = False
        try:
            data_parts = post_data.split(",")
            self.notify_type = int(data_parts[0])
            assert 0 <= self.notify_type <= NOTIFY_GAME_UPDATE
            self.post_data = data_parts[1]
            _key = data_parts[2]
            if self.notify_type >= NOTIFY_GAME_QUIT:
                self.player_key = int(data_parts[3])
                assert self.player_key == 0 or self.player_key == 1
                self.state = int(data_parts[4])
                assert self.state >= 0
            else:
                self.player_key = data_parts[3]

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
                    player = \
                        Player((self.key, self.post_data, self.ip_address, purge_timeout))
                else: # BIBBY_KEY
                    player = \
                        Player((self.key, self.post_data, self.ip_address, bibbybabbis_timeout))
                # when registering, anything other than '*' in the player_key field will tell the 
                # server that the client wants to be paired with whoever has a name that matches 
                # player_key
                if self.player_key != '*':
                    player.partner_name = self.player_key
                pairing_registry[self.key] = player
                return True, f"{C_MSG_REGISTER_OK}{self.key}\n"
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
                    if player.partner_name is None:
                        for partner_key in range(pairing_key_assign_ctr[0]):
                            partner = pairing_registry[partner_key]
                            if partner_key != self.key \
                            and partner is not None \
                            and partner.server_status == STATUS_REGISTERED \
                            and player.name not in partner.bad_partner_names \
                            and partner.name not in player.bad_partner_names:
                                # if either player drops before the game starts, we decide not to
                                # attempt to pair them again
                                player.bad_partner_names.add(partner.name)
                                partner.bad_partner_names.add(player.name)
                                player.partner_key = partner_key
                                partner.partner_key = self.key
                                player.server_status = STATUS_PAIRED
                                partner.server_status = STATUS_PAIRED
                                player.role = ROLE_SERVER
                                partner.role = ROLE_CLIENT
                                return True, f'{C_MSG_START_SERVER}{partner.name}\n'
                    else:
                        for partner_key in range(pairing_key_assign_ctr[0]):
                            partner = pairing_registry[partner_key]
                            if partner_key != self.key \
                            and partner is not None \
                            and partner.server_status == STATUS_REGISTERED \
                            and player.partner_name == partner.name \
                            and partner.partner_name == player.name:
                                player.partner_key = partner_key
                                partner.partner_key = self.key
                                player.server_status = STATUS_PAIRED
                                partner.server_status = STATUS_PAIRED
                                player.role = ROLE_SERVER
                                partner.role = ROLE_CLIENT
                                return True, f'{C_MSG_START_SERVER}{partner.name}\n'
                    return True, C_MSG_PAIRING
                elif player.server_status == STATUS_PAIRED:
                    pair_valid, msg, partner = self.pair_validate(player)
                    if not pair_valid:
                        return False, msg   
                    if player.role == ROLE_CLIENT:
                        return True, f'{C_MSG_START_CLIENT}{partner.name}\n'
                    else:
                        # just in case they didn't get the msg earlier
                        return True, f'{C_MSG_START_SERVER}{partner.name}\n'
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
                            return True, f'{C_MSG_START_PLAY}{game_key}0\n'
                    else:
                        player.server_status = STATUS_READY
                        return True, C_MSG_PARTNER_LOAD
                elif player.server_status == STATUS_PLAYING_INIT:
                    msg = f'{C_MSG_START_PLAY}{player.game_key[0]}{player.game_key[1]}\n'
                    return True, msg

        # gets NOTIFY_UNREGISTER and other potential client-server misaligned cases
        pairing_purge_entry(self.key)
        return False, ERROR_DROPPED


    def pair_validate(self, player):
        restarted_timer = pairing_keep_alive(self.key, map_load_timeout)
        if not restarted_timer:
            pairing_purge_entry(self.key)
            return False, ERROR_KEEP_ALIVE_FAIL, None
        partner = pairing_registry[player.partner_key]
        if partner is None:
            if player.partner_name is None:
                partner_drop_reset(player)
                return False, ERROR_PARTNER_DROP, None
            else:
                pairing_purge_entry(self.key)
                return False, ERROR_KNOWN_PARTNER_DROP, None
        return True, None, partner


    def game_update(self):
        game_valid, msg = self.game_validate() 
        if not game_valid:
            return False, msg
            
        self.game.updated[self.player_key] = True
        self.game.data[self.player_key][0].append(self.post_data)

        if self.game.updated[self.partner_key]:
            if not self.game.purged_pairing_entries:
                pairing_purge_entry(self.player.pairing_key)
                pairing_purge_entry(self.partner.pairing_key)
                self.player.server_status = STATUS_PLAYING
                self.partner.server_status = STATUS_PLAYING
                self.game.purged_pairing_entries = True
            
            partner_data = '|'.join(self.game.data[self.partner_key])
            self.game.updated[self.partner_key] = False
            self.game.data[self.partner_key].clear()

            return True, f'{C_MSG_GAME_DATA}{partner_data}\n'
        return True, C_MSG_GAME_NO_DATA
            

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


    def game_redundant_msg_update(self, table_entry):
        game = game_registry[self.key]
        partner_key = 0 if self.player_key == 1 else 1
        old_data = table_entry[1]
        new_data = game.data[partner_key]
        combined_data = old_data + "|" + new_data

        game.data[partner_key].clear()
        game.updated[partner_key] = False

        if len(combined_data) <= MAX_CACHE_LEN:
            game_msg_table[self.key][self.player_key][1] = combined_data
            return f'{C_MSG_GAME_DATA}{combined_data}\n'
        else:
            return f'{ERROR_GAME_CACHE_MAXED}{old_data}\n'


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
    game = game_registry[key]
    game.timer.cancel()
    game.players.clear()
    game.data.clear()
    game.timer = None
    game_registry[key] = None
    game_msg_table[key] = [[None, None, 0], [None, None, 0]]
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
            print(f'{key}: {client_data}')
    print(f'\n---\ngame registry:')
    for key in range(GAME_MAX_KEYS):
        game_data = game_registry[key]
        if game_data is not None:
            print(f'{key}:\n{game_data}')
    print('\n---\n')
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
