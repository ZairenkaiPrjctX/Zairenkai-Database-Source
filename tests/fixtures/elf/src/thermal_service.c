/* AFID test fixture: stands in for a Thermal HAL service binary. Never executed by AFID.
 * The config file name below lets tests check the "hal_config" string evidence. */
extern int thermal_fixture_read(void);
const char *config_name = "thermal_info_config.json";
int _start_fixture(void) { return thermal_fixture_read(); }
