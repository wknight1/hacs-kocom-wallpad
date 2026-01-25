# Changelog

## [v2.1.4] - 2026-01-25
### Added
- **Atomic Reconnection:** `asyncio.Lock`을 도입하여 중복 재연결 시도 방지.
- **Backpressure Management:** 송신 큐(maxsize=50) 도입으로 시스템 부하 방지.
- **Enhanced Lifecycle Management:** 통합 구성요소 언로드 시 백그라운드 태스크의 완벽한 정리를 보장.
- **Defensive Logging:** 모든 비동기 루프에 `try-except` 블록을 적용하여 시스템 Crash 방지 및 상세 트레이스 로깅.

### Fixed
- **Boot Loop Issue:** EOF 상황에서 무한 루프에 빠지던 버그 수정.
- **Method Restoration:** 누락되었던 `async_send_action` 및 `on_device_state` 메서드 복구.

## [v2.1.0] - 2026-01-25
### Added
- **RingBuffer:** 고성능 원형 버퍼 기반 패킷 파싱 도입.
- **Immediate Polling:** 제어 성공 직후 상태 강제 동기화 기능 추가.
- **Namespace Migration:** `lunDreame`에서 `wknight1`으로 리브랜딩.
