# Changelog

## [v2.2.6] - 2026-01-31
### Fixed
- **Sparse Heartbeat:** 5분 이상의 장시간 유휴 시에만 최소한의 하트비트(가스밸브 상태 조회)를 전송하여 연결 유지.
    - 이전 버전에서 비프음 방지를 위해 하트비트를 완전히 제거했으나, 이로 인해 일부 환경에서 TCP 세션이 끊기거나 월패드가 '무반응'으로 오인되는 문제를 해결했습니다.
- **Improved Availability Tracking:** 가용성 판단(Unresponsive) 타임아웃을 10분에서 30분으로 연장하고, 로그에 상세 유휴 시간을 포함하여 원인 분석을 용이하게 개선.
- **Connection Stability:** 하트비트 부재로 인한 세션 종료 및 재시도 과정에서 제어 명령이 누락되는 현상 방지.

## [v2.2.5] - 2026-01-30
### Fixed
- **Zero-Beep Discovery:** 시스템 부팅 시 실행되는 자동 탐색(Discovery) 대상에서 **에어컨(AC)**과 **난방기(Thermostat)**를 제외.
    - 해당 기기들은 상태 조회(Query) 패킷 수신 시 비프음을 내는 특성이 있어, 부팅 시 소음을 유발했습니다.
    - 이제 이 기기들은 사용자가 직접 제어하거나 월패드에서 상태를 변경할 때 자동으로 등록됩니다 (Lazy Discovery).
- **Periodic Beep Fix:** 간헐적인 통합 구성요소 재시작이나 리로드 시에도 에어컨 비프음이 발생하지 않도록 조치.

## [v2.2.4] - 2026-01-30
### Fixed
- **Silent Reconnection:** 네트워크 재연결 시 자동으로 실행되던 기기 탐색(Discovery) 로직을 제거.
    - 기존에는 'Deep Silence'로 인해 소켓 타임아웃이 발생하면, 재연결 과정에서 전체 기기 탐색(20개 이상의 패킷)이 실행되어 주기적인 비프음을 유발했습니다.
    - 이제 재연결은 패킷 전송 없이 조용히 이루어지며, 기기 상태는 월패드의 브로드캐스트나 사용자의 명시적 제어 시 갱신됩니다.

## [v2.2.3] - 2026-01-30
### Fixed
- **Deep Silence:** Home Assistant의 자동 폴링(30초 주기)을 강제로 비활성화(`should_poll=False`)하여, 사용자가 조작하지 않을 때 발생하는 주기적인 비프음 및 불필요한 트래픽을 원천 차단.
- **Discovery Rate Limit:** 네트워크 연결이 불안정할 때 기기 탐색(Discovery)이 반복적으로 실행되어 비프음 폭풍을 유발하는 문제를 방지하기 위해, 재탐색 최소 간격(60초) 제한 도입.

## [v2.2.2] - 2026-01-30
### Fixed
- **Silence & Optimization:** 주기적 비프음의 근본 원인인 하트비트(Heartbeat) 기능을 완전히 비활성화.
- **Double Beep Fix:** 에어컨 등 기기 제어 성공 후 자동으로 상태 조회를 수행하던 로직을 제거하여, 제어 시 비프음이 두 번 울리는 현상 해결.

## [v2.2.1] - 2026-01-26
### Fixed
- **AC Beep & Light Auto-Off Fix:** 하트비트 쿼리 대상을 '조명'에서 '가스밸브(상태 조회)'로 변경하여, 주기적인 비프음 발생 및 특정 조명이 자동으로 꺼지는 문제 해결.
- **Light Control Safety:** 조명 상태 조회(Query) 시, 레지스트리에 상태가 없는 경우 무조건 끄는(OFF) 문제를 방지하기 위해 섀도우 상태(Shadow State) 참조 로직 추가.
### Optimized
- **AC Packet Logic:** 에어컨 제어 시 변경하지 않는 값(팬 모드, 온도 등)이 0으로 초기화되지 않도록, 현재 상태를 보존하여 패킷을 생성하는 로직 개선.

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
