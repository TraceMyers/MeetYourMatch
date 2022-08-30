// Fill out your copyright notice in the Description page of Project Settings.

#include "MYMSubsystem.h"

#include <future>
#include <stdlib.h>
#include <SocketSubsystem.h>
#include <chrono>
#include "MYMWorker.h"

// #include "AllowWindowsPlatformAtomics.h"
// #include "windows.h" // any native windows header
// #include "HideWindowsPlatformAtomics.h"

#define UE_TEXT TEXT

void UMYMSubsystem::print(const char* format_str, ...) {
	char print_buffer[PBUFSIZ];
	va_list args;
	va_start(args, format_str);
	vsnprintf(print_buffer, PBUFSIZ, format_str, args);
	const FString fstr(print_buffer);
	UE_LOG(LogTemp, Warning, UE_TEXT("%s"), *fstr);
}

void UMYMSubsystem::print(const FString& fstr) {
	UE_LOG(LogTemp, Warning, UE_TEXT("%s"), *fstr);
}

void UMYMSubsystem::Initialize(FSubsystemCollectionBase& collection) {
	running_thread = false;
	worker = nullptr;
}

void UMYMSubsystem::Deinitialize() {
	if (worker != nullptr) {
		delete worker;
	}
}

void UMYMSubsystem::testfunc() {
	
}

void UMYMSubsystem::find_match() {
	// -- initialize networking socket and endpoints--
	
	info_key = 0;
	running_thread = true;
	worker = new FMYMWorker(&info_key, &(*(int8*)play_group));
}

void UMYMSubsystem::stop_finding_match() {
	delete worker;
	worker = nullptr;
	running_thread = false;
}

