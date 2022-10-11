# ---------------------------------------------------------------------------------- User parameters

# this server's default IP
DEFAULT_IP = "192.168.1.1"
# maximum allowed users in a match
MAX_MATCH_SIZE = 2
# maximum number of users concurrently in registration phase (pre-matchmaking)
MAX_REGISTERING = 1000
# maximum number of sessions concurrently matchmaking
MAX_MATCHMAKING_SESSIONS = 300
# maximum number of sessions concurrently in-session
MAX_RUNNING_SESSIONS = 10000
# which ports your clients will connect to on the server
REGISTRATION_PORT = 7778
MATCHMAKING_PORT = 7779
SESSION_PORT = 7780
# seconds client records stay alive between queries during matchmaking
MATCHMAKING_ALIVE_TIME = 25
# roughly how often matchmaking is run, in seconds (smaller = less time to respond)
MATCHMAKE_ROUND_TIME = 3
# which ports the clients can send messages from; keeping a small range in uncommonly used ports is
# better for not getting too much crawly-spammy traffic
# range min is included, max is excluded; range(7777, 8000) is all ports from 7777 to 7799
ACCEPT_TRAFFIC_PORTS = [port for port in range(7777, 8000)]

# --------------------------------------------------------------------------- Not meant to be edited

# CL_STATUS_REGISTER -> SV_STATUS_REGISTER_OK
# CL_STATUS_MATCHING -> SV_STATUS_MATCHING_OK
# -> SV_STATUS_LAT_CHECK
# CL_STATUS_LAT_CHECK -> (SV_STATUS_MATCHED, SV_STATUS_LAT_CHECK)
# CL_STATUS_MATCHED -> (SV_STATUS_WAIT, SV_STATUS_JOIN)

# CL_STATUS_REGISTER_HOST -> SV_STATUS_REGISTER_OK
# CL_STATUS_MATCHING_HOST -> SV_STATUS_MATCHING_OK
# CL_STATUS_LAT_CHECK_HOST -> SV_

CL_STATUS_NONE					= 0x0000

CL_STATUS_REGISTER				= 0x0001

CL_STATUS_MATCHING				= 0x0010
CL_STATUS_MATCHING_HOST			= 0x0030
CL_STATUS_LAT_CHECK				= 0x0050
CL_STATUS_INITIALIZING_HOST		= 0x0070
CL_STATUS_IN_MATCH				= 0x0090
CL_STATUS_IN_MATCH_HOST			= 0x00b0

SV_ERROR					= 0xff00
SV_ERROR_IP_BANNED          = 0x0100
SV_ERROR_NOT_REGISTERING	= 0x0200
SV_ERROR_FAST_POLL_RATE     = 0x0300
SV_ERROR_IP_LOG_MAXED       = 0x0400
SV_ERROR_BAD_GROUP_SIZE		= 0x0500
SV_ERROR_ALREADY_MATCHING	= 0x0600
SV_ERROR_MM_SESSIONS_MAXED	= 0x0700
SV_ERROR_NOT_MATCHING		= 0x0800
SV_ERROR_MATCHING_NOT_FOUND = 0x0900
SV_ERROR_USERS_MAXED		= 0x0a00

SV_STATUS					= 0x00ff
SV_STATUS_REGISTER_OK		= 0x0001
SV_STATUS_MATCHING_OK		= 0x0002
SV_STATUS_IN_GROUP			= 0x0004
SV_STATUS_LAT_CHECK			= 0x0008
SV_STATUS_GROUP_UPDATE		= 0x0010
SV_STATUS_INITIALIZING_OK	= 0x0020
SV_STATUS_IN_MATCH			= 0x0040

COM_STUN = 0
COM_TURN = 1
COM_MIXD = 2

# any client options
CL_ENCRYPTED            = 0x0001    # passed along to inform receivers of my data that some or all
                                    # of the data is encrypted; clients figure out the rest
CL_LAT_MAX_LOW          = 0x0002
CL_LAT_MAX_MID          = 0x0004
CL_LAT_MAX_OOF          = 0x0008
CL_ADDRESSES_LATENCIES  = 0x0010
# host options
CL_SET_GROUP_SIZE       = 0x0020    # if hosting, override default group size of 2, pass group size
                                    # in as first int16 in data
# group options
CL_RELAY_ONLY           = 0x0040    # session starts without preparing, waiting, joining, etc
# admin options
CL_ADMIN                = 0x0100            # password required for flags & CL_ADMIN > 0
CL_UNLOCK_POLL_RATE     = 0x0200 | CL_ADMIN # unlock poll rate lock for this client
CL_ONLY_MY_SESSIONS     = 0x0400 | CL_ADMIN # kick&refuse any client not connecting to my session
CL_MULTI_SESSION        = 0x0800 | CL_ADMIN # allow this client to enter mutliple sessions
CL_SET_PASSWORD         = 0x1000 | CL_ADMIN # set the admin password
CL_ONLY_MY_TRAFFIC      = 0x2000 | CL_ADMIN # kick&refuse anybody but me
CL_RESTORE_DEFAULTS     = 0x8000 | CL_ADMIN # turn off anything changed by flags (can be combined
                                            # with other changes)

GAP = b'\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0'
STUN_LOW_LAT = 0.07
STUN_MID_LAT = 0.13
STUN_OOF_LAT = 0.20
TURN_LOW_LAT = 0.10
TURN_MID_LAT = 0.18
TURN_OOF_LAT = 0.30


LAT_TURNOVER = 8
CONNECT_TURNOVER = LAT_TURNOVER * 4
CONNECT_TURNOVER_HOST = CONNECT_TURNOVER * 20
IP_TURNOVER_TIME = 15
IP_TURNOVER_UPDATE = 5
MAX_POLL_RATE = 0.3

LAT_LOW = 0
LAT_MID = 1
LAT_OOF = 2
LAT_TOP = 3
LATCHECK = (STUN_LOW_LAT, STUN_MID_LAT, STUN_OOF_LAT, 9999999.9)
LAT_DEFAULT = 10000000.0
MAX_CLBYTES = 460
MAX_IP_PACK = MAX_CLBYTES // 6
MAX_GROUP_PACK = MAX_CLBYTES // 22
