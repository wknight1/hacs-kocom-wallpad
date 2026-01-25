# Changelog

## [v2.1.8] - 2026-01-25
### Changed
- **Log Level Optimization:** `Peer resolution failed` 및 `EOF` 로그를 `WARNING`에서 `DEBUG`로 하향 조정하여 로그 스팸 방지.
- **Improved Packet Filtering:** 제어 대상이 아닌 장치 간 패킷(0x61, 0x62 등)을 조용히 무시하도록 최적화.

## [v2.1.7] - 2026-01-25
### Fixed
- **Method Restoration:** v2.1.6에서 누락되었던 `async_get_entity_registry`, `async_send_action` 등 핵심 메서드 전수 복구.
- **Syntax Fix:** `gateway.py` 내 비정상적으로 종료된 루프 구조 수정 (`SyntaxError` 해결).

## [v2.1.6] - 2026-01-25
### Added
- **RingBuffer:** 고성능 원형 버퍼 기반 패킷 파싱 도입.
- **Immediate Polling:** 제어 성공 직후 상태 강제 동기화 기능 추가.
- **Namespace Migration:** `lunDreame`에서 `wknight1`으로 리브랜딩.
