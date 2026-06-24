# P12 Parameter Reading

This document describes how the P12 (Push Assist) parameter is read from the King-Meter display in the EBiCS Firmware.

## Overview

The P12 parameter is received from the display during the **Settings mode** (command code `0x53`) of the KM_901U protocol.

## P12 - Push Assist Current

- **Description**: Push Assist current setting
- **Values**: 0/100/200/300mA (encoded as 2-bit value)
- **Source**: `KM_Message[6]` (payload byte 2)
- **Bit Position**: bits 5-4 (upper 2 bits of lower nibble)
- **Code Location**: `Src/display_kingmeter.c:467`

```c
KM_ctx->Settings.P12_Value = (KM_Message[6] & 0x30)>>4;
```

The value is masked with `0x30` (binary: `00110000`) and then shifted right by 4 bits to obtain a 2-bit value representing:
- 0: 0mA
- 1: 100mA
- 2: 200mA
- 3: 300mA

## Message Structure (Settings Mode)

The settings message uses command `0x53` with the following relevant payload structure:

| Byte Index | Field | Description |
|------------|-------|-------------|
| 4 | PAS_RUN_Direction | Bit 7: PAS direction |
| 4 | P17_Function | Bit 6: P17 setting |
| 5 | PAS_SCN_Tolerance | Full byte: P02 Tolerance |
| 6 | P18_Function | Bit 7: P18 Throttle enable |
| 6 | P19_Function | Bit 6: P19 Auto detect |
| 6 | Reverse | Bit 5: Reverse setting |
| 6 | P12_Value | Bits 5-4: P12 Push Assist current |
| 6 | PAS_N_Ratio | Bits 0-4: P05 PAS Level |

## Protocol Context

These settings are part of the King-Meter 901U protocol used in setting mode. The checksum validation occurs before these values are extracted (see `Src/display_kingmeter.c:458`).
