# Changelog

## [2.4.3] - 2026-02-04

### Critical Stability Fixes 🛡️
- **Proactive Reconnection:** Implemented aggressive reconnection logic that triggers if no data is received from the wallpad for 60 seconds. This effectively solves the "Zombie Connection" issue where the system remains technically connected but unresponsive.
- **Gas Valve Heartbeat Fixed:** Corrected the command generation for Gas Valve. The 15-second heartbeat (Query) now correctly sends valid RS485 packets, ensuring the connection stays alive and is verified even during idle periods.

### Documentation 📚
- **EW11 Optimization Guide:** Updated `README.md` with the latest recommended settings for EW11 (Max Accept=1, Gap Time=50ms, etc.) to match the new stability logic.

## [2.4.2] - 2026-02-01

### Critical Safety Fixes 🛡️
- **Passive Query Enforcement:** All device queries (Thermostat, AC, Ventilation, Light, Gas) now send zeroed payloads (`00...`). This prevents unintended state changes (e.g., setting thermostat to 40°C or turning on lights) during discovery or reconnection.
- **Gas Valve Stability:** Removed hardcoded `0x02` command for Gas Valve. It now correctly uses `0x00` for queries and closing, fixing the issue where the gas controller would power cycle or reset.

### Improvements 🚀
- **Enhanced Logging:** Logs now include human-readable interpretations of sent packets (e.g., `Type=THERMOSTAT, ... (Mode=HEAT, Set=24C)`), making troubleshooting much easier.

## [2.4.1] - 2025-05-15
... (Previous versions)