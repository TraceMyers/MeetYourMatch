
#pragma once

#include <chrono>

#include "CoreMinimal.h"
#include "HAL/Runnable.h"
#include "Networking.h"
#include "Common.h"

class MYM_API FMYMWorker : public FRunnable {
	
public:
	
	FMYMWorker(int32* info_key, int8* play_group);
	virtual ~FMYMWorker() override;

	bool Init() override;
	uint32 Run() override;
	void Stop() override;

private:

	uint32 receive_and_parse();
	MYM::CLStatus _register(MYM::CLStatus status);
	MYM::CLStatus host_matchmaking();
	MYM::CLStatus client_matchmaking();
	int32 client_read_in_data(MYM::CLData::READ_STATUS target_status, MYM::CommData* group, int32 max_group_size);
	void server_send_status(MYM::CLStatus status);
	void server_keep_alive();
	void client_send_ping(FIPv4Endpoint& endpoint); // TODO: these have bad naming scheme
	int32 client_handle_pingback();
	void client_send_server_latencies();
	static inline void elapse_time(double amt, double& ctr, std::chrono::time_point<std::chrono::system_clock>& prev);
	static inline double get_timestamp();

	FRunnableThread* thread;
	FSocket* socket;
	bool run_thread;
	TSharedPtr<FInternetAddr> src_addr;

	int32* info_key;
	uint8 recv_data[MYM::DATAGRAM_SAFE_LEN];
	ISocketSubsystem* socket_subsystem;

	int64 timer;
	double server_contact_rate;
	int32 port_ct;
	char* remote_ip = "154.12.226.174";
	FString socket_description = "UDP Listen Socket";
	int32 latcheck_group_size;
	int32 in_group_size;
	
	MYM::CLData in_cldata;
	MYM::CLData out_cldata;
	MYM::CommData local;
	MYM::CommData server_main;
	MYM::CommData server_all[3];
	MYM::CommData last_comm;
	MYM::CommData latcheck_group[MYM::MAX_LATCHECK_CLIENTS];
	MYM::CommData* play_group;
};
