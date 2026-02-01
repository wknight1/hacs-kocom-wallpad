# Changelog

## [2.4.2] - 2026-02-01

### Critical Safety Fixes 🛡️
- **Passive Query Enforcement:** All device queries (Thermostat, AC, Ventilation, Light, Gas) now send zeroed payloads (`00...`). This prevents unintended state changes (e.g., setting thermostat to 40°C or turning on lights) during discovery or reconnection.
- **Gas Valve Stability:** Removed hardcoded `0x02` command for Gas Valve. It now correctly uses `0x00` for queries and closing, fixing the issue where the gas controller would power cycle or reset.

### Improvements 🚀
- **Enhanced Logging:** Logs now include human-readable interpretations of sent packets (e.g., `Type=THERMOSTAT, ... (Mode=HEAT, Set=24C)`), making troubleshooting much easier.

## [2.4.1] - 2025-05-15
... (Previous versions)