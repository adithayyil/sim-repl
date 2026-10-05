#include <stdint.h>
#include "bmp3.h"
#define U(a) (*(volatile uint32_t *)(a))
#define GPIOA 0x40020000u
#define SPI1  0x40013000u
#define USART2_DR  (*(volatile uint32_t *)0x40004404)
#define USART2_CR1 (*(volatile uint32_t *)0x4000440C)

volatile uint32_t done, chip_id_seen, ndelays, delays[16];
volatile int32_t  r_init, r_set, r_mode[2], r_get[2];
volatile double   Tc[2], Pc[2];

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
    (void)p; if (ndelays < 16) delays[ndelays] = us; ndelays++;
}

int main(void) {
    struct bmp3_dev dev;
    struct bmp3_settings st;
    /* `d` is deliberately left uninitialised, and main.c is deliberately frozen.
     * At least one mutant (bmp388 m163) makes the driver pick its next register
     * from whatever is in `d`, so its recorded SPI log is a function of the stack
     * garbage here -- and that garbage shifts if the code size of main.c shifts.
     * "Improvements" that only change how dev/st are zeroed (memset vs the byte
     * loop) have already changed m163's recorded bus log.  Zero `d` as well, and
     * re-record the corpus, if that is ever worth doing; do not do it silently. */
    struct bmp3_data d;
    USART2_CR1 = (1u << 13) | (1u << 3);
    U(GPIOA + 0x00) = (U(GPIOA + 0x00) & ~(3u << 8)) | (1u << 8);
    cs_high();
    U(SPI1) = (1u << 2) | (1u << 6) | (1u << 9) | (1u << 8);

    for (unsigned i = 0; i < sizeof dev; i++) ((uint8_t *)&dev)[i] = 0;
    for (unsigned i = 0; i < sizeof st; i++) ((uint8_t *)&st)[i] = 0;
    dev.intf = BMP3_SPI_INTF; dev.read = spi_read; dev.write = spi_write;
    static uint8_t ctx; dev.delay_us = delay_us; dev.intf_ptr = &ctx;

    r_init = bmp3_init(&dev);
    chip_id_seen = dev.chip_id;
    st.press_en = BMP3_ENABLE; st.temp_en = BMP3_ENABLE;
    st.odr_filter.press_os = BMP3_OVERSAMPLING_8X; st.odr_filter.temp_os = BMP3_OVERSAMPLING_2X;
    st.odr_filter.odr = BMP3_ODR_50_HZ; st.odr_filter.iir_filter = BMP3_IIR_FILTER_COEFF_3;
    r_set = bmp3_set_sensor_settings(BMP3_SEL_PRESS_EN | BMP3_SEL_TEMP_EN | BMP3_SEL_PRESS_OS | BMP3_SEL_TEMP_OS |
                                     BMP3_SEL_ODR | BMP3_SEL_IIR_FILTER, &st, &dev);
    for (int k = 0; k < 2; k++) {
        st.op_mode = BMP3_MODE_FORCED;
        r_mode[k] = bmp3_set_op_mode(&st, &dev);
        dev.delay_us(30000, dev.intf_ptr);
        r_get[k] = bmp3_get_sensor_data(BMP3_PRESS_TEMP, &d, &dev);
        Tc[k] = d.temperature; Pc[k] = d.pressure;
    }
    if (r_init == 0 && r_set == 0 && r_mode[0] == 0 && r_mode[1] == 0 &&
        r_get[0] == 0 && r_get[1] == 0 && (chip_id_seen == 0x50 || chip_id_seen == 0x60)) put("OK\n");
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
