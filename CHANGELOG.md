# Changelog

## [v2.2.0] - 2026-01-25
### Added
- **Network Resilience:** 공유기 재부팅 등 네트워크 단절 시 자동 복구 및 복구 직후 즉시 재검색(Auto-Discovery) 수행.
- **Availability Monitoring:** 월패드 무반응(전원 꺼짐 등) 감지 시 엔티티를 자동으로 '사용 불가능(Unavailable)' 상태로 전환.
- **Heartbeat Enhancement:** 마지막 활동뿐만 아니라 실제 수신 시간을 추적하여 통신 신뢰성 강화.

## [v2.1.9] - 2026-01-25
### Added
- **Keep-Alive Heartbeat:** EW11 소켓 타임아웃(30s) 방지를 위한 자동 유휴 쿼리 로직 도입.
### Changed
- **Timing Optimization:** EW11 하드웨어 설정(Gap Time 50ms)에 맞춰 `IDLE_GAP_SEC` 및 `RECV_POLL_SEC` 최적화.
- **Improved Response Time:** RS485 버스 유휴 감지 시간을 단축하여 제어 반응 속도 개선.

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
