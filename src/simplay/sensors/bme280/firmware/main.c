#include <stdint.h>
#include "bme280.h"
#define U(a) (*(volatile uint32_t *)(a))
#define GPIOA 0x40020000u
#define SPI1  0x40013000u
#define USART2_DR  (*(volatile uint32_t *)0x40004404)
#define USART2_CR1 (*(volatile uint32_t *)0x4000440C)

volatile uint32_t done, chip_id_seen, meas_delay, ndelays, delays[16];
volatile int32_t  r_init, r_set, r_mode[2], r_get[2], r_delay;
volatile int32_t  Tc[2];
volatile uint32_t Pc[2], Hc[2];

static void put(const char *s) { while (*s) USART2_DR = (uint32_t)*s++; }
static uint8_t xfer(uint8_t b) {
    while (!(U(SPI1 + 8) & 2)) {}
    U(SPI1 + 12) = b;
    while (!(U(SPI1 + 8) & 1)) {}
    return (uint8_t)U(SPI1 + 12);
}
static void cs_low(void)  { U(GPIOA + 0x14) &= ~(1u << 4); }
static void cs_high(void) { U(GPIOA + 0x14) |= (1u << 4); }

static int8_t spi_read(uint8_t reg, uint8_t *data, uint32_t len, void *p) {
    (void)p; cs_low(); xfer(reg);
    for (uint32_t i = 0; i < len; i++) data[i] = xfer(0x00);
    cs_high(); return 0;
}
static int8_t spi_write(uint8_t reg, const uint8_t *data, uint32_t len, void *p) {
    (void)p; cs_low(); xfer(reg);
    for (uint32_t i = 0; i < len; i++) xfer(data[i]);
    cs_high(); return 0;
}
static void delay_us(uint32_t us, void *p) {
    (void)p;
    if (ndelays < 16) { delays[ndelays] = us; }
    ndelays++;
}

int main(void) {
    struct bme280_dev dev;
    struct bme280_settings st;
    struct bme280_data d;
    USART2_CR1 = (1u << 13) | (1u << 3);
    U(GPIOA + 0x00) = (U(GPIOA + 0x00) & ~(3u << 8)) | (1u << 8);
    cs_high();
    U(SPI1) = (1u << 2) | (1u << 6) | (1u << 9) | (1u << 8);

    dev.intf = BME280_SPI_INTF; dev.read = spi_read; dev.write = spi_write;
    dev.delay_us = delay_us; dev.intf_ptr = 0;

    r_init = bme280_init(&dev);
    chip_id_seen = dev.chip_id;
    st.osr_h = BME280_OVERSAMPLING_1X; st.osr_p = BME280_OVERSAMPLING_8X; st.osr_t = BME280_OVERSAMPLING_2X;
    st.filter = BME280_FILTER_COEFF_4; st.standby_time = BME280_STANDBY_TIME_62_5_MS;
    r_set = bme280_set_sensor_settings(BME280_SEL_ALL_SETTINGS, &st, &dev);
    r_delay = bme280_cal_meas_delay((uint32_t *)&meas_delay, &st);
    for (int k = 0; k < 2; k++) {
        r_mode[k] = bme280_set_sensor_mode(BME280_POWERMODE_FORCED, &dev);
        dev.delay_us(meas_delay, dev.intf_ptr);
        r_get[k] = bme280_get_sensor_data(BME280_ALL, &d, &dev);
        Tc[k] = d.temperature; Pc[k] = d.pressure; Hc[k] = d.humidity;
    }
    if (r_init == 0 && r_set == 0 && r_delay == 0 && r_mode[0] == 0 && r_mode[1] == 0 &&
        r_get[0] == 0 && r_get[1] == 0 && chip_id_seen == 0x60) put("OK\n");
    put("DONE\n");
    done = 1;
    for (;;) {}
}

extern uint32_t _estack, _sidata, _sdata, _edata, _sbss, _ebss;
void Reset_Handler(void) {
    uint32_t *s = &_sidata, *d = &_sdata;
    while (d < &_edata) *d++ = *s++;
    for (d = &_sbss; d < &_ebss; d++) *d = 0;
    main();
}
__attribute__((section(".isr_vector"), used)) const void *vectors[] = { &_estack, Reset_Handler };
