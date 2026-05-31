################################################################################
# Automatically-generated file. Do not edit!
################################################################################

-include makefile.init

RM := rm -rf

# All of the sources participating in the build are defined here
-include sources.mk
-include Startup/subdir.mk
-include Src/subdir.mk
-include Drivers/STM32F1xx_HAL_Driver/Src/subdir.mk
-include subdir.mk
-include objects.mk

ifneq ($(MAKECMDGOALS),clean)
ifneq ($(strip $(S_UPPER_DEPS)),)
-include $(S_UPPER_DEPS)
endif
ifneq ($(strip $(C_DEPS)),)
-include $(C_DEPS)
endif
endif

-include makefile.defs

SRC_PATH = Drivers/CMSIS

# Add inputs and outputs from these tool invocations to the build variables 

.DEFAULT_GOAL := all

# All Target
all: build/EBiCS_Firmware.elf post-build

# Tool invocations
build/EBiCS_Firmware.elf: $(OBJS) $(USER_OBJS) STM32F103C6Tx_FLASH_Bootloader.ld
	@echo 'Building target: $@'
	@echo 'Invoking: MCU GCC Linker'
	arm-none-eabi-gcc -mcpu=cortex-m3 -mthumb -mfloat-abi=soft -L $(SRC_PATH) -specs=nosys.specs -specs=nano.specs -T"STM32F103C6Tx_FLASH_Bootloader.ld" -Wl,-Map=output.map -Wl,--gc-sections -o "build/EBiCS_Firmware.elf" @"objects.list" $(USER_OBJS) $(LIBS) -lm
	@echo 'Finished building target: $@'
	@echo ' '

# Other Targets
clean:
	-$(RM) build/*
	-$(RM) output/*
	-@echo ' '

FORCE:

post-build: FORCE
	-@echo 'Generating hex and Printing size information:'
	arm-none-eabi-objcopy -O ihex "build/EBiCS_Firmware.elf" "build/EBiCS_Firmware.hex"
	arm-none-eabi-objcopy -O binary "build/EBiCS_Firmware.elf" "build/EBiCS_Firmware.bin"
	arm-none-eabi-size "build/EBiCS_Firmware.elf"
	stat "build/EBiCS_Firmware.bin"
	-@echo ' '
	mkdir -p output
	javac make/hexToLsh.java -d .
	java -cp . hexToLsh
	-@echo 'Firmware processing completed'

# Flash target - flash the lsh file via serial
flash:
	@echo 'Flashing firmware via serial...'
	python3 tools/flash.py

.PHONY: all clean dependents flash FORCE post-build

-include makefile.targets
