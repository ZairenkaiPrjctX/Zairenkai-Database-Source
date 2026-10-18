# redistributable/

Payload files that may be published. Every file here (except this README) must have a
matching SHA-256 entry with license evidence in `config/redistributable_allowlist.yml`;
`afid policy check` fails otherwise. The directory is empty by default: AFID's catalog is
useful from metadata alone, and proprietary firmware files are indexed, not stored.
