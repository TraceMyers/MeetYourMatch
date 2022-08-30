# --------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------:constants
# --------------------------------------------------------------------------------------------------

# -------------------------------------------------------------------------------------------:status

STATUS_NONE                 = 0x0000
STATUS_REG_CLIENT           = 0x0001
STATUS_REG_MASK             = STATUS_REG_CLIENT
STATUS_REG_HOST             = 0x0003
STATUS_REG_CLIENT_KNOWNHOST = 0x0005
STATUS_REG_HOST_KNOWNHOST   = 0x0007
STATUS_GROUPING             = 0x0008
STATUS_HOST_PREPARING       = 0x000a
STATUS_HOST_READY           = 0x000c
STATUS_CLIENT_WAITING       = 0x000e
STATUS_CLIENT_JOINING       = 0x0010
STATUS_LATCHECK_HOST        = 0x0020
STATUS_LATCHECK_CLIENT      = 0x0030
STATUS_IN_GROUP             = 0x0040
STATUS_JOIN_SESSION         = 0x0050
STATUS_PING                 = 0x0060
STATUS_PINGBACK             = 0x0070
STATUS_PORT_OPEN            = 0x0080

ERROR_MASK                  = 0xff00
ERROR_DATA_FORMAT           = 0x0100
ERROR_REGISTER_FAIL         = 0x0200
ERROR_INTAKE_MAXED          = 0x0300
ERROR_TRANSFERS_MAXED       = 0x0400
ERROR_NO_SESSION            = 0x0500
ERROR_NO_CLIENT             = 0x0600
ERROR_NO_PARTNER            = 0x0700
ERROR_BAD_STATUS            = 0x0800
ERROR_FAST_POLL_RATE        = 0x0900
ERROR_IP_LOG_MAXED          = 0x0a00
ERROR_CLIENT_LOG_MAXED      = 0x0b00
ERROR_NO_HOST               = 0x0c00
ERROR_HOST_NAME_TAKEN       = 0x0d00
ERROR_SESSION_MAXED         = 0x0e00
ERROR_SESSIONS_MAXED        = 0x0f00
ERROR_ALREADY_REGISTERED    = 0x1000
ERROR_BAD_GROUP_SIZE		= 0x2000
ERROR_GROUPING_TIMEOUT      = 0x3000

COM_STUN = 0
COM_TURN = 1
COM_MIXD = 2

# --------------------------------------------------------------------------------------------:flags

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

# ----------------------------------------------------------------------------------:other constants

SES_MAX = 600 # max number of sessions
MAX_CLIENT_CT = 5
SES_CLIENT_MAX = SES_MAX * 2 # max number clients in all sessions
GAP = b'\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0'
STUN_LOW_LAT = 0.07
STUN_MID_LAT = 0.13
STUN_OOF_LAT = 0.20
TURN_LOW_LAT = 0.10
TURN_MID_LAT = 0.18
TURN_OOF_LAT = 0.30
ACCEPT_TRAFFIC_PORTS = (
	7777, 7778, 7779, 7780, 7781, 7782, 7783, 7784, 7785, 7786, 7787, 7788, 7789, 7780, 7781,
	7782, 7783, 7784, 7785, 7786, 7787, 7789, 7790, 7791, 7792, 7793, 7794, 7795, 7796, 7797,
	7798, 7799
)
LAT_TURNOVER = 8
CONNECT_TURNOVER = LAT_TURNOVER * 4
CONNECT_TURNOVER_HOST = CONNECT_TURNOVER * 20

LAT_LOW = 0
LAT_MID = 1
LAT_OOF = 2
LAT_TOP = 3
LATCHECK = (STUN_LOW_LAT, STUN_MID_LAT, STUN_OOF_LAT, 9999999.9)
LAT_DEFAULT = 10000000.0
MAX_CLBYTES = 464
MAX_IP_PACK = MAX_CLBYTES // 6
MAX_GROUP_PACK = MAX_CLBYTES // 18