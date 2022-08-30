#pragma once

namespace MYM {
	enum CLStatus {
		STATUS_NONE                 = 0x0000,
		STATUS_REG_CLIENT           = 0x0001,
		STATUS_REG_MASK             = STATUS_REG_CLIENT,
		STATUS_REG_HOST             = 0x0003,
		STATUS_REG_CLIENT_KNOWNHOST = 0x0005,
		STATUS_REG_HOST_KNOWNHOST   = 0x0007,
		STATUS_GROUPING             = 0x0008,
		STATUS_HOST_PREPARING       = 0x000a,
		STATUS_HOST_READY           = 0x000c,
		STATUS_CLIENT_WAITING       = 0x000e,
		STATUS_CLIENT_JOINING       = 0x0010,
		STATUS_LATCHECK_HOST        = 0x0020,
		STATUS_LATCHECK_CLIENT      = 0x0030,
		STATUS_IN_GROUP             = 0x0040,
		STATUS_JOIN_SESSION         = 0x0050,
		STATUS_PING                 = 0x0060,
		STATUS_PINGBACK             = 0x0070,
		STATUS_PORT_OPEN            = 0x0080,

		ERROR_MASK                  = 0xff00,
		ERROR_DATA_FORMAT           = 0x0100,
		ERROR_REGISTER_FAIL         = 0x0200,
		ERROR_INTAKE_MAXED          = 0x0300,
		ERROR_TRANSFERS_MAXED       = 0x0400,
		ERROR_NO_SESSION            = 0x0500,
		ERROR_NO_CLIENT             = 0x0600,
		ERROR_NO_PARTNER            = 0x0700,
		ERROR_BAD_STATUS            = 0x0800,
		ERROR_FAST_POLL_RATE        = 0x0900,
		ERROR_IP_LOG_MAXED          = 0x0a00,
		ERROR_CLIENT_LOG_MAXED      = 0x0b00,
		ERROR_NO_HOST               = 0x0c00,
		ERROR_HOST_NAME_TAKEN       = 0x0d00,
		ERROR_SESSION_MAXED         = 0x0e00,
		ERROR_SESSIONS_MAXED        = 0x0f00,
		ERROR_ALREADY_REGISTERED    = 0x1000,
		ERROR_BAD_GROUP_SIZE		= 0x2000,
		ERROR_GROUPING_TIMEOUT      = 0x3000
	};

	enum CLFlag {
		// any client options
		CL_ENCRYPTED            = 0x0001,    // passed along to inform receivers of my data that some or all
											//  of the data is encrypted; clients figure out the rest
		CL_LAT_MAX_LOW          = 0x0002,
		CL_LAT_MAX_MID          = 0x0004,
		CL_LAT_MAX_OOF          = 0x0008,
		CL_ADDRESSES_LATENCIES  = 0x0010,
		// host options
		CL_SET_GROUP_SIZE       = 0x0020,   // if hosting, override default group size of 2, pass group size
											// in as first int16 in data
		// group options
		CL_RELAY_ONLY           = 0x0040,    // session starts without preparing, waiting, joining, etc
		// admin options
		CL_ADMIN                = 0x0100,            // password required for flags & CL_ADMIN > 0
		CL_UNLOCK_POLL_RATE     = 0x0200 | CL_ADMIN, // unlock poll rate lock for this client
		CL_ONLY_MY_SESSIONS     = 0x0400 | CL_ADMIN, // kick&refuse any client not connecting to my session
		CL_MULTI_SESSION        = 0x0800 | CL_ADMIN, // allow this client to enter mutliple sessions
		CL_SET_PASSWORD         = 0x1000 | CL_ADMIN, // set the admin password
		CL_ONLY_MY_TRAFFIC      = 0x2000 | CL_ADMIN, // kick&refuse anybody but me
		CL_RESTORE_DEFAULTS     = 0x8000 | CL_ADMIN 
	};
	
	static constexpr int DATAGRAM_SIZE = 576;
	static constexpr int RECV_BUFLEN = DATAGRAM_SIZE * 300;
	static constexpr int THREAD_NO_INFO = 0; // for paired threads
	
	static constexpr int NAME_LEN = 12;
	static constexpr int ADMIN_KEY_LEN = 16;
	static constexpr int CLIENT_DATA_LEN = 464;
	static constexpr int DATAGRAM_SAFE_LEN = 508;
	static constexpr int MAX_LATCHECK_CLIENTS = 464 / 6;
	static constexpr int MAX_PLAY_CLIENTS = 5;

	static constexpr uint32 THREAD_SUCCESS = 0;
	static constexpr uint32 THREAD_FAILURE = 1;
	static constexpr uint32 NO_PENDING = 2;
	static constexpr uint32 NULL_SOCKET = 3;
	static constexpr uint32 READ_FAILURE = 4;
	static constexpr double REGISTER_TIMEOUT = 50.0;
	static constexpr double NO_REPLY_TIMEOUT = 20.0;
	static constexpr double MATCHMAKING_TIMEOUT = 640.0;

	static constexpr uint8 NO_PREFIX = 0;
	static constexpr uint8 GROUP_PREFIX = 1;
	static constexpr uint8 IPLIST_PREFIX = 2;
	static constexpr uint8 SUFFIX = 3;

	static constexpr double LATCHECK_TIME = 8.0;
	
	struct CommData {
		FString name;
		FString address;
		FIPv4Endpoint endpoint;
		double latbuf[3];
		int latbuf_ctr;
		bool is_host;
		bool latbuf_full;
		uint32 server_order_ip;
		int32 _port;

		CommData() {
			is_host = false;
			reset_latency();
		}

		void reset_latency() {
			for (int i = 0; i < 3; i++) {
				latbuf[i] = -1.0;
			}
			latbuf_ctr = 0;
		}

		double latency() {
			double lat = 0.0;
			for (int i = 0; i < 3; i++) {
				lat += latbuf[i];
			}
			return lat * 0.333333333;
		}

		bool update_latency(double val) {
			latbuf[latbuf_ctr++] = val;
			if (latbuf_ctr == 3) {
				latbuf_full = true;
				latbuf_ctr = 0;
			}
			return latbuf_full;
		}

		void set_name(const char* in_name) {
			name = FString(in_name);
		}
		
		void set_local_address(int local_port) {
			endpoint = FIPv4Endpoint(FIPv4Address::Any, local_port);
			address = FString::Printf(TEXT("0.0.0.0:%d"), local_port);
			server_order_ip = 0;
			_port = local_port;
		}
		
		void set_address(uint32 ip, int32 port, bool net_order=true) {
			char address_buff[4*5+5]; // max needed bytes even if garbage values read
			if (net_order) {
				endpoint = FIPv4Endpoint(ip, port);
				server_order_ip =
					(0x000000ff & ip) << 24
					| (0x0000ff00 & ip) << 8
					| (0x00ff0000 & ip) >> 8
					| (0xff000000 & ip) >> 24;
				sprintf(
				address_buff,
					"%d.%d.%d.%d:%d\0",
					(0xff000000 & ip) >> 24,
					(0x00ff0000 & ip) >> 16,
					(0x0000ff00 & ip) >> 8,
					0x000000ff & ip,
					port
				);
			}
			else {
				server_order_ip = ip;
				uint32 net_order_ip =
					(0x000000ff & ip) << 24
					| (0x0000ff00 & ip) << 8
					| (0x00ff0000 & ip) >> 8
					| (0xff000000 & ip) >> 24;
				endpoint = FIPv4Endpoint(net_order_ip, port);
				sprintf(
					address_buff,
					"%d.%d.%d.%d:%d\0",
					0x000000ff & ip,
					(0x0000ff00 & ip) >> 8,
					(0x00ff0000 & ip) >> 16,
					(0xff000000 & ip) >> 24,
					port
				);
			}
			address = FString(address_buff);
			_port = port;
		}
		
		void set_address(const char* ip, int32 port) {
			FIPv4Address addr;	
			FIPv4Address::Parse(ip, addr);
			endpoint = FIPv4Endpoint(addr, port);
			address = FString::Printf(TEXT("%s:%d"), ip, port);
			uint32 _ip;
			endpoint.ToInternetAddr()->GetIp(_ip);
			server_order_ip =
				(0x000000ff & _ip) << 24
				| (0x0000ff00 & _ip) << 8
				| (0x00ff0000 & _ip) >> 8
				| (0xff000000 & _ip) >> 24;
			_port = port;
		}
		
		void set_address(TSharedPtr<FInternetAddr> addr) {
			endpoint = FIPv4Endpoint(addr);
			uint32 ip;
			addr->GetIp(ip);
			int32 port;
			addr->GetPort(port);
			char address_buff[4*5+5]; // max needed bytes even if garbage values read
			sprintf(
				address_buff,
				"%d.%d.%d.%d:%d\0",
				(0xff000000 & ip) >> 24,
				(0x00ff0000 & ip) >> 16,
				(0x0000ff00 & ip) >> 8,
				0x000000ff & ip,
				port
			);
			address = FString(address_buff);
			server_order_ip =
				(0x000000ff & ip) << 24
				| (0x0000ff00 & ip) << 8
				| (0x00ff0000 & ip) >> 8
				| (0xff000000 & ip) >> 24;
			_port = port;
		}
	};
	
	struct CLData {
		uint32_t status;
		uint32_t flags;
		double time_stamp;
		char name[NAME_LEN+4]; // 1 for null, 3 to avoid padding
		char admin_key[ADMIN_KEY_LEN];
		uint8_t client_data[CLIENT_DATA_LEN];
		uint8_t* client_data_ptr;
		enum READ_STATUS {
			READ_INIT,
			READ_GROUP,
			READ_IPLIST,
			READ_EMPTY,
			READ_ERROR
		} read_status;
		
		CLData() {
			zero();
		}

		// TODO: make this read less hacky
		void packet(uint8_t* buffer) {
			memcpy((void*)buffer, (void*)(&status), 28);
			memcpy(buffer+28, (void*)(((uint8*)(&status))+32), DATAGRAM_SAFE_LEN-28);
		}

		void unpacket(uint8_t* buffer) {
			memcpy((void*)&status, (void*)buffer, 28);
			memcpy((void*)&admin_key, buffer+28, DATAGRAM_SAFE_LEN-28);
		}

		void zero() {
			memset((void*)(&status), 0, DATAGRAM_SAFE_LEN);
			client_data_ptr = client_data;
			read_status = READ_INIT;
		}

		void set_name(const char* in_name) {
			const int len_in = strlen(in_name);
			memcpy(name, in_name, (len_in <= NAME_LEN ? len_in : MYM::NAME_LEN));
		}

		void set_name(const FString& in_name) {
			char* _name = TCHAR_TO_ANSI(*in_name);
			const int len_in = strlen(_name);
			memcpy(name, _name, (len_in <= NAME_LEN ? len_in : NAME_LEN));
		}

		READ_STATUS init_read_client_data() {
			if (read_status == READ_INIT && client_data_ptr == client_data) {
				read_advance(0);
				if (read_status == READ_INIT) {
					read_status = READ_ERROR;
				}
			}
			else {
				read_status = READ_ERROR;
			}
			return read_status;
		}

		// internal. could make private
		void read_advance(uint32 depth) {
			int32 remaining = CLIENT_DATA_LEN - (client_data_ptr - client_data);
			if (remaining < 6) {
				read_status = READ_EMPTY;
			} 
			uint32 val = *((uint32*)client_data_ptr);
			if (val == 0) {
				client_data_ptr += 2;
				val = *((uint32*)client_data_ptr);
				if (val == IPLIST_PREFIX) {
					if (remaining < 12) {
						read_status = READ_EMPTY;
					}
					else {
						client_data_ptr += 4;
						read_status = READ_IPLIST;
					}
				}
				else if (val == GROUP_PREFIX) {
					if (remaining < 24) {
						read_status = READ_EMPTY;
					}
					else {
						client_data_ptr += 4;
						read_status = READ_GROUP;
					}
				}
				else if (val == NO_PREFIX) {
					read_status = READ_EMPTY;	
				}
				else if (val == SUFFIX) {
					if (depth == 1) {
						read_status = READ_EMPTY;
					}
					else {
						client_data_ptr += 4;
						read_advance(1);
					}
				}
				else {
					client_data_ptr -= 2;
				}
			}
			else {
				if (read_status == READ_GROUP && remaining < 24) {
					read_status = READ_EMPTY;
				}
				else if (read_status == READ_IPLIST && remaining < 12) {
					read_status = READ_EMPTY;
				}
			}
		}

		READ_STATUS read_client_data(CommData& c) {
			if (read_status == READ_GROUP) {
				char name_buf[12];
				memcpy(name_buf, client_data_ptr, 12);
				client_data_ptr += 12;
				uint32 ip = *((uint32*)client_data_ptr);
				client_data_ptr += 4;
				uint16 port = *((uint16*)client_data_ptr);
				client_data_ptr += 2;
				c.set_name(name_buf);
				c.set_address(ip, port, false);
				read_advance(0);
			}
			else if (read_status == READ_IPLIST) {
				uint32 ip = *((uint32*)client_data_ptr);
				client_data_ptr += 4;
				uint16 port = *((uint16*)client_data_ptr);
				client_data_ptr += 2;
				c.set_address(ip, port, false);
				read_advance(0);
			}
			else {
				read_status = READ_ERROR;
			}
			return read_status;
		}
	};

	
}
