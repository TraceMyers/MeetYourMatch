// Fill out your copyright notice in the Description page of Project Settings.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Networking.h"
#include "Common.h"
#include "MYMSubsystem.generated.h"


UCLASS()
class MYM_API UMYMSubsystem : public UGameInstanceSubsystem {
	
	GENERATED_BODY()
	
public:
	
	virtual void Initialize(FSubsystemCollectionBase& collection) override;
	virtual void Deinitialize() override;
	
	UFUNCTION(BlueprintCallable, Category=MYMSubsystem)
	void testfunc();
	UFUNCTION(BlueprintCallable, Category=MYMSubsystem)
	void find_match();
	UFUNCTION(BlueprintCallable, Category=MYMSubsystem)
	void stop_finding_match();
	
	static void print(const char* format_str, ...);
	static void print(const FString& fstr);
	
	static constexpr int PBUFSIZ = 2048;

private:
	
	class FMYMWorker* worker;
	
	int32 info_key;
	MYM::CommData play_group[MYM::MAX_PLAY_CLIENTS];
	MYM::CommData* play_group_self;

	bool running_thread;

	ISocketSubsystem* socket_subsystem;
};
