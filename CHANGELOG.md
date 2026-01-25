# Changelog

## [v2.1.7] - 2026-01-25
### Fixed
- **Method Restoration:** v2.1.6에서 누락되었던 `async_get_entity_registry`, `async_send_action` 등 핵심 메서드 전수 복구.
- **Syntax Fix:** `gateway.py` 내 비정상적으로 종료된 루프 구조 수정 (`SyntaxError` 해결).

## [v2.1.6] - 2026-01-25
### Added
- **RingBuffer:** 고성능 원형 버퍼 기반 패킷 파싱 도입.
- **Immediate Polling:** 제어 성공 직후 상태 강제 동기화 기능 추가.
- **Namespace Migration:** `lunDreame`에서 `wknight1`으로 리브랜딩.
