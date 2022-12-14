// Fill out your copyright notice in the Description page of Project Settings.

#include "MYMWorker.h"
#include "MYMSubsystem.h"
#include "Kismet/KismetSystemLibrary.h"
#include <chrono>
#include <random>

FMYMWorker::FMYMWorker(int32* _info_key, int8* _play_group) {
	if ((socket_subsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)) == nullptr) {
		UMYMSubsystem::print("ERROR FMYMWorker::FMYMWorker(): socket subsystem is nullptr");
		return;
	}
	// TODO: set all server port choosing to depend on user setting if they want it
	// TODO: custom out port as well
	port_ct = 3;
	double inv_port_ct = 1.0 / port_ct;
	double draw = std::rand() / RAND_MAX;
	const int port_ct_m1 = port_ct - 1;
	int32 server_port_main = 0;
	for (int i = 0; i < port_ct_m1; i++) {
		const int32 server_port = 7777 + i;
		MYM::CommData& s = server_all[i];
		s.name = "Server Port 1";
		s.set_address(remote_ip, server_port);
		if (draw < inv_port_ct * (i + 1)) {
			// temp, just picking one of the (as of writing, 3) available server ports
			// to exclusively send to
			server_port_main = server_port;
		}
	}
	if (server_port_main == 0) {
		server_port_main = 7777 + port_ct_m1;
	}
	local.name = FString("no name");
	local.set_local_address(7780);
	local.is_host = false;
	server_main.name = FString("JoeSevere!");
	server_main.set_address(remote_ip, server_port_main);
	server_main.is_host = false;

	socket = FUdpSocketBuilder(socket_description)
		.AsNonBlocking()
		.AsReusable()
		.BoundToEndpoint(local.endpoint)
		.WithReceiveBufferSize(MYM::DATAGRAM_SAFE_LEN)
		.WithSendBufferSize(MYM::DATAGRAM_SAFE_LEN)
		.WithBroadcast();
	if (socket == nullptr) {
		UMYMSubsystem::print("ERROR FMYMWorker::FMYMWorker(): FUdpSocketBuilder returned nullptr");
		return;
	}
	
	info_key = _info_key;
	play_group = &(*(MYM::CommData*)_play_group);
	thread = FRunnableThread::Create(this, TEXT("FMYMWorker"));
	server_contact_rate = 3.0;
}

FMYMWorker::~FMYMWorker() {
	if (thread) {
		thread->Kill();
		delete thread;
	}	
}

#pragma endregion

bool FMYMWorker::Init() {
	UMYMSubsystem::print("FMYMWorker::Init() thread started");
	run_thread = true;
	play_group[0].is_host = true;
	latcheck_group_size = 0;
	in_group_size = 0;
	return true;
}

uint32 FMYMWorker::Run() {
	src_addr = socket_subsystem->CreateInternetAddr();
	in_cldata.zero();
	in_cldata.status = MYM::STATUS_NONE;

	// -- the register process, wherein we init connection with server and wait for it to tell us --
	// -- we've advanced to the matchmaking stage --
	UMYMSubsystem::print("**trying client");
	send_server_status(MYM::STATUS_REG_CLIENT);
	MYM::CLStatus reg_status = _register(MYM::STATUS_REG_CLIENT);
	if (!run_thread) {;}
	else if (reg_status == MYM::STATUS_NONE) {
		UMYMSubsystem::print("**trying host");
		send_server_status(MYM::STATUS_REG_HOST, 5);
		reg_status = _register(MYM::STATUS_REG_HOST, 5);
		if (reg_status != MYM::STATUS_REG_HOST) {
			UMYMSubsystem::print("**host fail");
			return MYM::THREAD_FAILURE;
		}
		UMYMSubsystem::print("**host success");
		local.is_host = true;
	}
	else if (reg_status == MYM::STATUS_REG_CLIENT) {
		UMYMSubsystem::print("**client success");
	}
	else {
		return MYM::THREAD_FAILURE;	
	}

	// -- do --
	if (run_thread) {
		if (local.is_host) {
			host_matchmaking();	
		}
		else {
			client_matchmaking();	
		}
	}
	// if latcheck_client, we're ungrouped and will be only getting a list of hosts to latcheck
	// if latcheck_host, we're a host and getting clients to open our ports to as well as our group info
	// if host_ready, our group is full and we can start the game, get group info
	// if join_session, the host has loaded the map and we can join, get group info
	// if in_group, session is not full and not started, get group info
	
	if (socket_subsystem == nullptr && (socket_subsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)) == nullptr) {
		UMYMSubsystem::print("ERROR FMYMWorker::Run(): socket subsystem is nullptr");
		return MYM::THREAD_FAILURE;
	}
	socket_subsystem->DestroySocket(socket);
	return MYM::THREAD_SUCCESS;
}

void FMYMWorker::Stop() {
	run_thread = false;
}

MYM::CLStatus FMYMWorker::_register(MYM::CLStatus status, int8 client_ct) {
	FPlatformProcess::Sleep(1.0);
	double time_elapsed = 0.0;
	double total_time_elapsed = 0.0;
	double no_pending_time = 0.0;
	double delta_time;
	bool got_first_reply = false;
	auto prev_time = std::chrono::system_clock::now();
	while (run_thread) {
		elapse_time(0.001, delta_time, prev_time);
		time_elapsed += delta_time;
		
		if (time_elapsed >= server_contact_rate) {
			total_time_elapsed += time_elapsed;
			if (no_pending_time > MYM::NO_REPLY_TIMEOUT) {
				UMYMSubsystem::print(
					"FMYMWorker::_register(): %2.lf seconds elapsed with no response. returning.",
					no_pending_time
				);
				return MYM::STATUS_NONE;
			}
			if (total_time_elapsed > MYM::REGISTER_TIMEOUT) {
				UMYMSubsystem::print(
					"FMYMWorker::_register(): %.2lf seconds elapsed while trying to register. returning.",
					total_time_elapsed
				);
				return MYM::STATUS_NONE;
			}
			if (!got_first_reply) {
				send_server_status(status, client_ct);
				FPlatformProcess::Sleep(0.05);
				send_server_status(MYM::STATUS_GROUPING);
				FPlatformProcess::Sleep(0.05);
			}
			else {
				UMYMSubsystem::print("sending grouping");
				send_server_status(MYM::STATUS_GROUPING);
			}
			keep_server_connection_alive();
			time_elapsed = 0.0;
			continue;
		}
		
		switch(receive_and_parse()) {
		case MYM::NO_PENDING:
		case MYM::READ_FAILURE:
			no_pending_time += delta_time;
			continue;
		case MYM::THREAD_SUCCESS:
			break;
		case MYM::NULL_SOCKET:
			return MYM::ERROR_MASK;
		default:
			continue;
		}

		got_first_reply = true;
		no_pending_time = 0.0;
		if (
			in_cldata.status == MYM::STATUS_IN_GROUP
			|| in_cldata.status == MYM::STATUS_LATCHECK_CLIENT
			|| in_cldata.status == MYM::STATUS_LATCHECK_HOST
		) {
			break;
		}
		if (in_cldata.status & MYM::ERROR_MASK) {
			if (in_cldata.status == MYM::ERROR_FAST_POLL_RATE) {
				continue;
			}
			UMYMSubsystem::print("ERROR FMYMWorker::_register() server error code %04x", in_cldata.status);
			switch(in_cldata.status) {
			case MYM::ERROR_DATA_FORMAT:
			case MYM::ERROR_BAD_STATUS:
				return MYM::ERROR_MASK; // kill thread
			case MYM::ERROR_REGISTER_FAIL:
			case MYM::ERROR_INTAKE_MAXED:
			case MYM::ERROR_NO_CLIENT:
			case MYM::ERROR_GROUPING_TIMEOUT:
				return MYM::STATUS_NONE; // retry as host if client
			default:
				;
			}
		}
	}
	return status;
}

MYM::CLStatus FMYMWorker::host_matchmaking() {
	double time_elapsed = 0.0;
	double state_time_elapsed = 0.0;
	double no_pending_time = 0.0;
	double delta_time;
	bool just_entered_group = false;
	auto prev_time = std::chrono::system_clock::now();
	while (run_thread) {
		elapse_time(0.0001, delta_time, prev_time);
		time_elapsed += delta_time;
		
		if (time_elapsed >= server_contact_rate) {
			state_time_elapsed += time_elapsed;
			if (no_pending_time > MYM::NO_REPLY_TIMEOUT) {
				UMYMSubsystem::print(
					"FMYMWorker::host_matchmaking(): %.2lf seconds elapsed with no response. returning.",
					no_pending_time
				);
				return MYM::STATUS_NONE;
			}
			if (state_time_elapsed > MYM::MATCHMAKING_TIMEOUT) {
				UMYMSubsystem::print(
					"FMYMWorker::host_matchmaking(): %.2lf seconds elapsed in current state while trying to"
					" matchmake. returning.",
					state_time_elapsed
				);
				return MYM::STATUS_NONE;
			}
			send_server_status(MYM::STATUS_GROUPING);
			keep_server_connection_alive();
			time_elapsed = 0.0;
			continue;
		}
		
		switch(receive_and_parse()) {
		case MYM::NO_PENDING:
			no_pending_time += delta_time;
			continue;
		case MYM::THREAD_SUCCESS:
			break;
		case MYM::NULL_SOCKET:
			return MYM::ERROR_MASK;
		case MYM::READ_FAILURE:
		default:
			continue;
		}
		// status latcheck host or status host ready
		no_pending_time = 0.0;
		if (in_cldata.status == MYM::STATUS_PING) {
			host_pingback();	
		}
		else if (in_cldata.status == MYM::STATUS_LATCHECK_HOST) {
			host_read_in_data();
			if (latcheck_group_size > 0) {
				for (int i = 0; i < latcheck_group_size && i < MYM::MAX_LATCHECK_CLIENTS; i++) {
					MYM::CommData comm = latcheck_group[i];
					host_allow_ping(comm.endpoint);
				}
			}
		}
		else if (in_cldata.status == MYM::STATUS_HOST_READY) {
			host_read_in_data();
			return MYM::STATUS_HOST_READY;
		}
		else if (in_cldata.status & MYM::ERROR_MASK) {
			if (in_cldata.status == MYM::ERROR_FAST_POLL_RATE) {
				continue;
			}
			UMYMSubsystem::print(
				"ERROR FMYMWorker::host_matchmaking() server error code %04x",
				in_cldata.status & MYM::ERROR_MASK
			);
			switch(in_cldata.status) {
			case MYM::ERROR_DATA_FORMAT:
			case MYM::ERROR_BAD_STATUS:
				return MYM::ERROR_MASK; 
			case MYM::ERROR_REGISTER_FAIL:
			case MYM::ERROR_INTAKE_MAXED:
			case MYM::ERROR_NO_CLIENT:
			case MYM::ERROR_GROUPING_TIMEOUT:
				return MYM::STATUS_NONE; 
			default:
				// ignore
				;
			}
		}
	}
	return MYM::STATUS_NONE;
}

MYM::CLStatus FMYMWorker::client_matchmaking() {
	double time_elapsed = 0.0;
	double state_time_elapsed = 0.0;
	double no_pending_time = 0.0;
	double delta_time;
	double latcheck_time_elapsed = 0.0;
	double latcheck_round_time_elapsed = 0.0;
	bool checking_latency = false;
	bool just_entered_group = false;
	auto prev_time = std::chrono::system_clock::now();
	while (run_thread) {
		elapse_time(0.0001, delta_time, prev_time);
		time_elapsed += delta_time;
		if (checking_latency) {
			latcheck_time_elapsed += delta_time;
			latcheck_round_time_elapsed += delta_time;
		}
		else {
			latcheck_time_elapsed = 0.0;
			latcheck_round_time_elapsed = 0.0;
		}
		
		if (time_elapsed >= server_contact_rate) {
			if (checking_latency) {
				if (latcheck_time_elapsed > MYM::LATCHECK_TIME) {
					client_send_server_latencies();
					latcheck_time_elapsed = 0.0;
					checking_latency = false;
				}
			}
			keep_server_connection_alive();
			state_time_elapsed += time_elapsed;
			if (no_pending_time > MYM::NO_REPLY_TIMEOUT) {
				UMYMSubsystem::print(
					"FMYMWorker::client_matchmaking(): %.2lf seconds elapsed with no response. returning.",
					no_pending_time
				);
				return MYM::STATUS_NONE;
			}
			if (state_time_elapsed > MYM::MATCHMAKING_TIMEOUT) {
				UMYMSubsystem::print(
					"FMYMWorker::client_matchmaking(): %.2lf seconds elapsed in current state while trying to"
					" matchmake. returning.",
					state_time_elapsed
				);
				return MYM::STATUS_NONE;
			}
			
			if (!checking_latency) {
				send_server_status(MYM::STATUS_GROUPING);
			}
			time_elapsed = 0.0;
			continue;
		}
		if (checking_latency && latcheck_round_time_elapsed > MYM::LATCHECK_ROUND_TIME) {
			for (int i = 0; i < latcheck_group_size && i < MYM::MAX_LATCHECK_CLIENTS; i++) {
				MYM::CommData comm = latcheck_group[i];
				client_send_ping(comm.endpoint);
			}
			latcheck_round_time_elapsed = 0.0;
		}

		switch(receive_and_parse()) {
		case MYM::NO_PENDING:
			no_pending_time += delta_time;
			continue;
		case MYM::THREAD_SUCCESS:
			break;
		case MYM::NULL_SOCKET:
			return MYM::ERROR_MASK;
		case MYM::READ_FAILURE:
		default:
			continue;
		}

		no_pending_time = 0.0;
		if (in_cldata.status == MYM::STATUS_PINGBACK) {
			if (!checking_latency || latcheck_group_size < 1) {
				continue;
			}
			int32 full_latbuf_ct = client_handle_pingback();	
			if (full_latbuf_ct == latcheck_group_size) {
				latcheck_time_elapsed = 0.0;
				checking_latency = false;
				client_send_server_latencies();
			}
		}
		else if (in_cldata.status == MYM::STATUS_LATCHECK_CLIENT) {
			latcheck_group_size = client_read_in_data(
				MYM::CLData::READ_IPLIST,
				latcheck_group,
				MYM::MAX_LATCHECK_CLIENTS
			);
			if (latcheck_group_size > 0) {
				checking_latency = true;
				for (int i = 0; i < latcheck_group_size && i < MYM::MAX_LATCHECK_CLIENTS; i++) {
					MYM::CommData comm = latcheck_group[i];
					comm.reset_latency();
					client_send_ping(comm.endpoint);
				}
			}
			else {
				UMYMSubsystem::print("ERROR FMYMWorker::client_matchmaking(): latcheck group size 0");
			}
		}
		else if (in_cldata.status == MYM::STATUS_IN_GROUP) {
			if (!just_entered_group) {
				state_time_elapsed = 0.0;
				just_entered_group = true;
			}
			in_group_size = client_read_in_data(
				MYM::CLData::READ_GROUP,
				play_group,
				MYM::MAX_PLAY_CLIENTS
			);
			if (in_group_size < 1) {
				UMYMSubsystem::print("ERROR FMYMWorker::client_matchmaking(): play group size 0");
			}
			// just waiting to join
		}
		else if (in_cldata.status == MYM::STATUS_JOIN_SESSION) {
			in_group_size = client_read_in_data(
				MYM::CLData::READ_GROUP,
				play_group,
				MYM::MAX_PLAY_CLIENTS
			);
			return MYM::STATUS_JOIN_SESSION;
		}
		else if (in_cldata.status & MYM::ERROR_MASK) {
			if (in_cldata.status == MYM::ERROR_FAST_POLL_RATE) {
				continue;
			}
			UMYMSubsystem::print(
				"ERROR FMYMWorker::client_matchmaking() server error code %04x",
				in_cldata.status & MYM::ERROR_MASK
			);
			switch(in_cldata.status) {
			case MYM::ERROR_DATA_FORMAT:
			case MYM::ERROR_BAD_STATUS:
				return MYM::ERROR_MASK; 
			case MYM::ERROR_REGISTER_FAIL:
			case MYM::ERROR_INTAKE_MAXED:
			case MYM::ERROR_NO_CLIENT:
			case MYM::ERROR_GROUPING_TIMEOUT:
				return MYM::STATUS_NONE; 
			default:
				// ignore
				;
			}
		}
	}
	return MYM::STATUS_NONE;
}

int32 FMYMWorker::client_read_in_data(MYM::CLData::READ_STATUS target_status, MYM::CommData* group, int32 max_grp_sz) {
	MYM::CLData::READ_STATUS read_status = in_cldata.init_read_client_data();
	int32 group_size = 0;
	if (read_status == target_status) {
		for ( ; group_size < max_grp_sz; group_size++) {
			read_status = in_cldata.read_client_data(group[group_size]);
			if (read_status == MYM::CLData::READ_EMPTY) {
				break;
			}
			if (read_status != target_status) {
				UMYMSubsystem::print(
					"ERROR FMYMWorker::client_read_in_data() cldata read error. ignoring last read."
				);
				break;
			}
		}
	}
	else if (read_status != MYM::CLData::READ_EMPTY) {
		UMYMSubsystem::print("ERROR FMYMWorker::read_client_data() init cldata latcheck read error");
	}
	return group_size;
}

void FMYMWorker::host_read_in_data() {
	MYM::CLData::READ_STATUS read_status = in_cldata.init_read_client_data();
	if (read_status == MYM::CLData::READ_GROUP) {
		for (in_group_size = 0; in_group_size < MYM::MAX_PLAY_CLIENTS; in_group_size++) {
			read_status = in_cldata.read_client_data(play_group[in_group_size]);
			if (read_status == MYM::CLData::READ_EMPTY || read_status == MYM::CLData::READ_IPLIST) {
				break;
			}
			if (read_status == MYM::CLData::READ_ERROR) {
				UMYMSubsystem::print(
					"ERROR FMYMWorker::host_read_in_data() cldata group read error. ignoring last read."
				);
				break;
			}
		}	
	}
	if (read_status == MYM::CLData::READ_IPLIST) {
		for (latcheck_group_size = 0; latcheck_group_size < MYM::MAX_LATCHECK_CLIENTS; latcheck_group_size++) {
			read_status = in_cldata.read_client_data(latcheck_group[latcheck_group_size]);
			if (read_status == MYM::CLData::READ_EMPTY) {
				break;
			}
			if (read_status == MYM::CLData::READ_ERROR) {
				UMYMSubsystem::print(
					"ERROR FMYMWorker::host_read_in_data() cldata latcheck read error. ignoring last read."
				);
				break;
			}
		}	
	}
}

void FMYMWorker::send_server_status(MYM::CLStatus status, int8 client_ct) {
	out_cldata.zero();
	out_cldata.status = status;
	out_cldata.set_name(local.name);
	out_cldata.client_data[0] = client_ct;
	uint8_t packet_buff[MYM::DATAGRAM_SAFE_LEN];
	out_cldata.packet(packet_buff);
	int32_t bytes_sent;
	socket->SendTo(packet_buff, MYM::DATAGRAM_SAFE_LEN, bytes_sent, *server_main.endpoint.ToInternetAddr());
}

void FMYMWorker::keep_server_connection_alive() {
	out_cldata.zero();
	out_cldata.status = MYM::STATUS_PORT_OPEN;
	uint8_t packet_buff[MYM::DATAGRAM_SAFE_LEN];
	out_cldata.packet(packet_buff);
	int32_t bytes_sent;
	for (int i = 0; i < port_ct; i++) {
		socket->SendTo(packet_buff, MYM::DATAGRAM_SAFE_LEN, bytes_sent, *(server_all[i].endpoint.ToInternetAddr()));
	}
}

void FMYMWorker::client_send_ping(FIPv4Endpoint& endpoint) {
	out_cldata.zero();
	out_cldata.status = MYM::STATUS_PING;
	out_cldata.time_stamp = get_timestamp();
	uint8_t packet_buff[MYM::DATAGRAM_SAFE_LEN];
	out_cldata.packet(packet_buff);
	int32_t bytes_sent;
	socket->SendTo(packet_buff, MYM::DATAGRAM_SAFE_LEN, bytes_sent, *endpoint.ToInternetAddr());
}

void FMYMWorker::host_pingback() {
	out_cldata.zero();
	out_cldata.status = MYM::STATUS_PINGBACK;
	out_cldata.time_stamp = in_cldata.time_stamp;
	uint8_t packet_buff[MYM::DATAGRAM_SAFE_LEN];
	out_cldata.packet(packet_buff);
	int32_t bytes_sent;
	socket->SendTo(packet_buff, MYM::DATAGRAM_SAFE_LEN, bytes_sent, *last_comm.endpoint.ToInternetAddr());
}

void FMYMWorker::host_allow_ping(FIPv4Endpoint& endpoint) {
	out_cldata.zero();
	out_cldata.status = MYM::STATUS_PORT_OPEN;
	uint8_t packet_buff[MYM::DATAGRAM_SAFE_LEN];
	out_cldata.packet(packet_buff);
	int32_t bytes_sent;
	socket->SendTo(packet_buff, MYM::DATAGRAM_SAFE_LEN, bytes_sent, *endpoint.ToInternetAddr());
}

int32 FMYMWorker::client_handle_pingback() {
	int32 full_latbuf_ct = 0;
	for (int i = 0; i < latcheck_group_size && i < MYM::MAX_LATCHECK_CLIENTS; i++) {
		MYM::CommData& comm = latcheck_group[i];
		if (comm.latbuf_full) {
			full_latbuf_ct++;	
		}
		else if (last_comm.server_order_ip == comm.server_order_ip && last_comm._port == comm._port) {
			bool latbuf_full = comm.update_latency(get_timestamp() - in_cldata.time_stamp);
			if (latbuf_full) {
				full_latbuf_ct++;
			}
			break;
		}
	}
	return full_latbuf_ct;
}

void FMYMWorker::client_send_server_latencies() {
	// TODO / CHECK: python padded the doubles for some buggy reason... that won't happen here
	out_cldata.zero();
	out_cldata.flags |= MYM::CL_ADDRESSES_LATENCIES;
	out_cldata.status = MYM::STATUS_GROUPING;
	int j = 0;
	for (int i = 0; i < latcheck_group_size && i < MYM::MAX_LATCHECK_CLIENTS; i++) {
		MYM::CommData comm = latcheck_group[i];
		if (comm.latbuf_full) {
			*((uint32*)(out_cldata.client_data + (j * 14))) = comm.server_order_ip;
			*((uint16*)(out_cldata.client_data + (j * 14 + 4))) = comm._port;
			*((double*)(out_cldata.client_data + (j * 14 + 6))) = comm.latency();
			j += 14;
			FPlatformProcess::Sleep(0.04);
		}
	}
	uint8_t packet_buff[MYM::DATAGRAM_SAFE_LEN];
	out_cldata.packet(packet_buff);
	int32_t bytes_sent;
	socket->SendTo(packet_buff, MYM::DATAGRAM_SAFE_LEN, bytes_sent, *server_main.endpoint.ToInternetAddr());
}

uint32 FMYMWorker::receive_and_parse() {
	if (socket == nullptr) {
		UMYMSubsystem::print("ERROR FMYMWorker::Run(): null socket");
		return MYM::NULL_SOCKET;
	}
	
	uint32 pending_data_size = MYM::DATAGRAM_SAFE_LEN;
	if (!(socket->HasPendingData(pending_data_size))) {
		return MYM::NO_PENDING;
	}
	int bytes_read = 0;
	socket->RecvFrom(
		recv_data,
		MYM::DATAGRAM_SAFE_LEN,
		bytes_read,
		*src_addr,
		ESocketReceiveFlags::None
	);
	if (bytes_read != MYM::DATAGRAM_SAFE_LEN) {
		return MYM::NO_PENDING;
	}
	in_cldata.zero();
	in_cldata.unpacket(recv_data);
	
	last_comm.set_name(in_cldata.name);
	last_comm.set_address(src_addr);
	UMYMSubsystem::print(
		"Message from %s:\nname:%s, status:0x%04x, time_stamp:%.5lf",
		*last_comm.address, *last_comm.name, in_cldata.status, in_cldata.time_stamp
	);
	return MYM::THREAD_SUCCESS;
}

void FMYMWorker::elapse_time(double amt, double& delta, std::chrono::time_point<std::chrono::system_clock>& prev) {
	FPlatformProcess::Sleep(amt);
	auto new_time = std::chrono::system_clock::now();
	auto new_duration = std::chrono::duration<double>(new_time.time_since_epoch());
	auto prev_duration = std::chrono::duration<double>(prev.time_since_epoch());
	delta = (new_duration - prev_duration).count();
	prev = new_time;
}

double FMYMWorker::get_timestamp() {
	// https://stackoverflow.com/questions/45464711/how-to-convert-stdchronosystem-clocknow-to-double
	// user AndyG	
	auto current_time = std::chrono::system_clock::now();
	auto duration_in_seconds = std::chrono::duration<double>(current_time.time_since_epoch());
	return duration_in_seconds.count();
}
