"""Mutation audits of sensor-driver checks under Simantic/Renode.

Two audits live here: Bosch's BME280 and BMP388 sensor-API drivers, each driven
by a synthetic SPI peer built from the datasheet, each checked by four levels
(L0 status line, L1 plausible values, L2 datasheet arithmetic, L3 bus traffic)
and attacked with mechanically generated mutants.
"""

__all__ = ["sensors"]
