/* AFID test fixture: a library that depends on libfixture_dep.so and on a library that is
 * intentionally absent from fixture trees (libmissing_fixture.so). */
extern int fixture_dep_value(void);
extern int fixture_missing_value(void);
int thermal_fixture_read(void) { return fixture_dep_value() + fixture_missing_value(); }
