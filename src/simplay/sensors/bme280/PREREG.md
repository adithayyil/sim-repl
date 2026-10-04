# Pre-registration: BME280 driver mutation audit (written before any mutant is run)

Driver under test: boschsensortec/BME280_SensorAPI @ c90d419492e26dd95586598a794e65eb2760753a (BSD-3), bme280.c + bme280_defs.h, built with BME280_64BIT_ENABLE.
Sim: simantic 0.3.1 (GitHub main tarball), Renode engine 0.5.19, backend=renode, repl= (no account).
Peer: my own datasheet-based BME280 SPI model (Bosch BME280 datasheet rev 1.23). Trim values and raw ADC values are synthetic.

Checks (all derived from the datasheet, not from the driver):
  L0 status  : firmware printed its own "all calls returned BME280_OK" line.
  L1 plausible: compensated T/P/H land in sane ranges (what a quick smoke test asserts).
  L2 numeric : compensated outputs equal the datasheet fixed-point formulas (section 4.2.3) applied to the peer's trim+raw data.
  L3 bus     : SPI transactions obey datasheet section 6.3 + register map (RW bit, reset word 0xB6, ctrl_hum before ctrl_meas,
               ctrl/config values implied by the requested settings, calibration + data burst reads at the right addresses).

Mutants: generated mechanically (not hand-picked) from operator classes ROR, AOR(+/-), shift(<< >>), bitwise(&,|), logical(&&,||),
integer-constant +-1 / bit-flip, over function bodies in bme280.c and #define constants in bme280_defs.h. Seed 20261004. Target N=200 sampled uniformly from all sites.
Mutant status: compile_fail | hang/crash | no-observable-difference (NOD: identical UART, bus trace, output RAM vs golden; NOT proven equivalent) | observed.
Metric: of 'observed' mutants, fraction caught by each check and by unions. Single stimulus scenario (2 measurements), so NOD mutants are "not exercised", not "equivalent".

Predictions (written now):
  P1  L0 catches <= 30% of observed mutants.
  P2  L2 catches more than L0 and L1 (paired, same mutants).
  P3  L3 catches a non-empty set that L2 misses (settings/ordering faults the numbers cannot show).
  P4  L2 u L3 catches >= 80% of observed mutants.
Kill: if P2 fails (L2 <= L0), the "assert on real outputs beats status prints" story does not hold for this driver and I will say so.
Known biases: I wrote the peer and the checks; the peer's raw data does not depend on oversampling except 'skipped'.

## Addendum A (written before any mutant was built or run)

Scenario: SPI mode, osr_t=2x, osr_p=8x, osr_h=1x, filter=4, standby=62.5 ms, forced mode, two measurements. Harness uses the driver's own macros.
Driver units (fixed-point build): T in 0.01 degC, P in 0.01 Pa, H in Q22.10 %RH.
Oracle validity check: the datasheet-formula oracle reproduces 25.08 degC / ~100653 Pa for the Bosch example raw values 519888 / 415148.

L0: firmware prints "OK" iff every API return code == 0 and chip_id == 0x60.
L1: both measurements inside room-condition bounds: T 1500..3500, P 9000000..10500000, H 20480..81920.
L2: T,P,H of both measurements == oracle exactly, AND meas_delay == 27700 us (datasheet 9.1).
L3 (bus/protocol, all must hold): (1) first transaction reads 0xD0; (2) a write of 0xB6 to 0xE0 follows, then >=1 read of 0xF3, and the first recorded
    delay after reset >= 2000 us; (3) calibration burst reads 0x88 x26 and 0xE1 x7 after the reset; (4) RW bit: read control bytes have bit7=1,
    write control bytes bit7=0; (5) at each measurement trigger the device registers are (ctrl_hum,ctrl_meas,config)=(0x01,0x51,0x28);
    (6) the ctrl_hum write precedes the ctrl_meas write; (7) each trigger is followed by a burst read of 0xF7 x8.

Classification: 'no_completion' = firmware never reaches DONE within 2 s wall (hang/fault). These are reported separately and EXCLUDED from catch rates,
because every check trivially catches them. 'NOD' = identical UART, SPI trace and RAM results to golden. Catch rates use mutants with status 'observed' only.
Mutation sites are only lines compiled in this configuration (BME280_64BIT_ENABLE, no DOUBLE, no 32BIT): bme280.c excluding lines 323-364, 1122-1241, 1326-1387.

## Addendum B (written after the golden run, before any mutant was built)

Observation: the unmodified Bosch driver FAILS my pre-registered exact-equality L2 on pressure. Cause (verified by re-running the oracle with C-truncating division):
the datasheet reference code uses `>>` (floor) where bme280.c uses `/` (truncate toward zero); when `inner*dig_T3` is negative, t_fine differs by 1,
which moves P by 3 units of 0.01 Pa (0.03 Pa) on both measurements. T and H are exact. This is a difference between two Bosch artifacts, not a bug.
Deviation (chosen after seeing golden, before any mutant): L2 = T exact AND H exact AND |P - P_oracle| <= 8 (0.08 Pa, far below the part's +-100 Pa accuracy)
AND meas_delay == 27700. Mutants that move P by <= 8 units escape L2 by construction. I also report L2x (the original exact form) for transparency; golden fails L2x.

## Results (200 mechanical mutants, seed 20261004, two full sweeps, verdicts identical; only the iteration count of one hang differs)

Status: 199 observed, 1 no_completion (m026, infinite poll loop; excluded). Of 199 observed, 73 (36.7%) were identical to golden in UART+SPI trace+RAM ("NOD": not exercised by
this single scenario; NOT proven equivalent). 126 differed from golden; catch rates are over those 126.
  L0 status print : 16/126 = 12.7%  [8.0, 19.6]      L1 plausibility: 52/126 = 41.3% [33.1, 50.0]
  L2 numeric      : 103/126 = 81.7% [74.1, 87.5]     L3 bus protocol: 44/126 = 34.9% [27.2, 43.6]
  L2 or L3        : 118/126 = 93.7% [88.0, 96.7]     all four       : 119/126 = 94.4%
  caught only by: L0 1, L1 0, L2 47, L3 15; caught by nothing 7.
  Paired exact McNemar: L2 vs L0 88-1 (P=3e-25); L2 vs L1 51-0; L3 vs L0 32-4; L3 vs L2 15-74.
Predictions: P1 (L0<=30%) yes; P2 (L2>L0,L1) yes; P3 (L3 catches what L2 misses) yes, 15; P4 (L2|L3>=80%) yes. Kill did not fire.
Caveats: one scenario, one driver, one synthetic peer written by me; L1 bounds and L3 clauses are my choices; mutants on the same line are not independent (CI are per-mutant, not clustered);
'golden fails L2x' means the strict datasheet-exact check would have rejected the real driver.
