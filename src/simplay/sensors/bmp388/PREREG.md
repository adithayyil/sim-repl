# BMP388 driver mutation audit (replication of the BME280 audit on a second driver)
Written 2026-10-04, BEFORE building any firmware or peer for this driver.

Driver: Bosch BMP3_SensorAPI commit db4cf8e4140c593b8c3d85f8c6c07335c7ffa9dc (BSD-3), default FLOAT compensation path (BMP3_64BIT_COMPENSATION not defined).
Datasheet: BST-BMP388-DS001-07 rev 1.7 (sha256 in this dir's listing, bmp3_ds.pdf 1ab21c90...9fdec2). Oracle written from datasheet Sec. 3.11, 4.3, 5.3, 9.
Sensor peer: synthetic BMP388 written by me from the datasheet; trim and raw ADC values are made up and NOT from a real part.

Scenario (fixed): bmp3_init -> bmp3_set_sensor_settings(press_en, temp_en, press_os=8x, temp_os=2x, odr=50Hz, iir=coeff_3) ->
2x { bmp3_set_op_mode(FORCED); wait; bmp3_get_sensor_data(PRESS_TEMP) }. SPI, STM32F4 Cortex-M4 in Simantic/Renode.

Mutants: 300, seed 20261005, same mechanical operators as the BME280 run (ROR, AOR, SHIFT, BITWISE, LOGICAL, CONST, DEFCONST),
sampled uniformly over compiled sites of bmp3.c (float-path only; integer-path branch excluded) and numeric #define constants in bmp3_defs.h.
NOD = identical UART + SPI trace + RAM to golden ("not exercised by this scenario", NOT proven equivalent). Catch rates are over observed, non-NOD mutants.
Hangs/no_completion are excluded and counted.

Checks (defined now, not changed after seeing results):
  L0  status: firmware prints OK iff every driver return code is 0 and chip_id in {0x50,0x60}.
  L1  plausibility: both T in [15,35] C and both P in [90000,105000] Pa.
  L2  numeric: |T - T_oracle| <= 0.01 C and |P - P_oracle| <= 1.0 Pa for both measurements (oracle = datasheet Sec. 9 float formulas in Python double, trim scaling per Sec. 3.11).
      The driver computes in double with a float32 pow helper, the datasheet reference in float32; exact equality is not expected, hence the tolerance (chosen a priori, ~2% of the +-50 Pa pressure accuracy).
  L3  bus invariants (datasheet Sec. 4.2, 4.3, 5.3): (a) first transaction is a read of 0x00 with control 0x80 (bit7=RW=1) and exactly one dummy byte before data;
      (b) every read transaction has control bit7 set, every write control byte has bit7 clear (addresses 7-bit);
      (c) softreset is a write pair (0x7E,0xB6) preceded by a STATUS(0x03) read; (d) calibration is a single burst read of 0x31 for 21 bytes AFTER the reset;
      (e) only writable registers {0x1B,0x1C,0x1D,0x1F,0x7E} are ever written (writes to reserved registers are a violation);
      (f) at each forced-mode trigger the device state is OSR=0x0B, ODR=0x02, CONFIG=0x04, PWR_CTRL enables=0b11 (i.e. settings were written BEFORE the mode write), exactly 2 triggers;
      (g) each trigger is followed by a burst read of 0x04 for 6 bytes (+dummy); (h) first driver delay after reset >= 2000 us (start-up 2 ms).

Predictions (replication of BME280 result): P1 L0 catch <= 30%. P2 L2 catch > L0 and > L1 (exact McNemar). P3 L3 catches >=1 mutant L2 misses.
P4 L2|L3 >= 80% of non-NOD mutants. P5 ordering of single-level rates is L2 > L1 > L3 > L0 as on BME280 (this is the weakest prediction; L1 vs L3 were within CI overlap there).
Kill: if L2|L3 < 50% or L2 <= L0, the BME280 finding does not generalize and the write-up must say so.
Known limits before running: one scenario, one driver, synthetic peer, mutants on one line are not independent, L1/L3 clauses are my choices, and most of bmp3.c (FIFO, interrupts, status, normal mode) is NOT exercised, so a large NOD fraction is expected.

## Addendum A (after the golden run, before any mutant was built)
Golden result: L0, L1, L2 pass; pre-registered L3 FAILED on the unmodified Bosch driver. Cause (read from bmp3.c:876 and the observed trace):
`bmp3_set_regs` burst write uses `temp_len = len * 2` (bme280.c uses `len*2 - 1`). A 3-register burst therefore clocks 1 control + 6 buffer bytes = 7 bytes:
three complete (control,data) pairs plus ONE trailing byte taken from `temp_buff[5]`, which `interleave_reg_addr` never writes (uninitialised stack; 0x00 in this run).
On a real BMP388 that is probably harmless (a control byte with no data before CSB rises) but it is a datasheet-protocol irregularity and reads uninitialised memory. Not a confirmed field failure; I have not tested a part.
Deviation (chosen before any mutant): L3(e) inspects complete (control,data) pairs only; exactly one trailing unpaired byte on a write transaction is tolerated. Consequence: mutants that only change that trailing byte escape L3 by construction.
All other L3 clauses, L0, L1, L2 unchanged.

## Addendum B (before mutant generation)
The BMP3 float path contains float literals (quantisation divisors such as 1073741824.0f, 0.125f). Operator CONST therefore also covers float literals: replaced by 2x or 0.5x the value (not +-1, which is meaningless for 2^48).
Site pool: bmp3.c lines >= 738 (function bodies) excluding the integer-compensation branch (lines 2539-2696) and preprocessor lines; plus integer constants inside UINT8_C/UINT16_C/UINT32_C/INT8_C defines in bmp3_defs.h.
Float-valued #defines (BMP3_MIN_TEMP_DOUBLE etc.) are not mutated. Build flags: -O1 -mfloat-abi=soft -ffreestanding -fno-builtin, stubs.c for memcpy/memset (not mutated).

## Results (300 mechanical mutants, seed 20261005, two full sweeps with identical verdict fields on all 300)
All 300 built and ran to completion. 201 (67.0%) were NOD (identical UART + SPI trace + RAM to golden; "not exercised by this scenario", not proven equivalent): only one forced-mode scenario
is run, so FIFO, interrupts, normal mode, status and error paths are never reached. 99 differed from golden; rates are over those 99 (Wilson 95% in brackets; line-clustered bootstrap in line_boot.py output).
  L0 33/99 = 33.3% [24.8, 43.1]   L1 43/99 = 43.4% [34.1, 53.3]   L2 73/99 = 73.7% [64.3, 81.4]   L3 54/99 = 54.5% [44.8, 64.0]   L2|L3 95/99 = 96.0% [90.1, 98.4]
  only-L2 27, only-L3 21, only-L0 0, only-L1 0, caught by nothing 4.  McNemar exact: L2 vs L0 41-1 P=2e-11; L2 vs L1 30-0 P=2e-9; L3 vs L0 31-10 P=0.0015; L3 vs L2 22-41 P=0.023.
Predictions: P1 (L0<=30%) NOT MET: L0 caught 33.3% (just above). P2 met. P3 met (21 L3-only). P4 met (96.0%). P5 (order L2>L1>L3>L0) NOT MET: observed L2 > L3 > L1 > L0, L1 vs L3 CIs overlap.
Kill (L2|L3<50% or L2<=L0) did not fire.
Golden caveat (Addendum A): the unmodified driver fails my first L3 because bmp3_set_regs clocks one trailing uninitialised byte on burst writes (len*2 vs the BME280 driver's len*2-1).

## Addendum C (post hoc, offline from stored traces; clause_ablate.py in ~/.cache/sim-play)
Blind re-authoring of L3 by an independent agent was attempted and FAILED to run (opencode-go 429 quota, kiro 403); it has NOT been done. Substitute: clause ablation of my own L3.
The reconstruction reproduces the stored L3 catches exactly (BME280 44, BMP388 54).
"trigger_state" (sensor registers at the moment a measurement is triggered equal the scenario's configured values) carries most of L3:
  BME280: alone 33/126; removing it loses 23 of L3's 44 catches; 11 of the 15 L3-only catches.   BMP388: alone 38/99; removing it loses 16 of 54; 15 of the 22 L3-only catches.
Reading: much of what I called "bus protocol" is a configuration-state check against the scenario, not a wire-protocol check. The bus-ordering/burst clauses contribute 0-5 catches each.
Honest consequence: the claim "L3 is a datasheet protocol check that complements numeric L2" overstates; the defensible claim is "a scenario-derived state/sequence check complements numeric L2". Its clauses are still author-chosen.
