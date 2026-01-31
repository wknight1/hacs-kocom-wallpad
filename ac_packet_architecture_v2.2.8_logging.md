# [기술 문서] Kocom 통합구성요소 로깅 아키텍처 (v2.2.8)

이 문서는 v2.2.8 버전에서 도입된 **계층적 로깅(Hierarchical Logging)** 및 **UI 기반 디버그 전략**을 다룹니다.

---

### 1. 설계 배경 (Design Context)

복잡한 RS485 통신 통합환경에서 발생하는 문제는 크게 세 가지 범주로 나뉩니다.
1.  **Transport:** 소켓 연결, EOF, 타임아웃 등 하위 계층 문제.
2.  **Controller:** 체크섬 오류, 미지원 기기 패킷, 파싱 오류 등 프로토콜 문제.
3.  **Gateway:** 상태 동기화 실패, 재시도 초과, 엔티티 가용성 등 상위 로직 문제.

기존의 단일 로거 시스템에서는 이 모든 로그가 섞여 있어 특정 문제를 격리 분석하기 어려웠습니다.

---

### 2. 계층적 로깅 구조 (Logger Hierarchy)

v2.2.8부터 로거는 다음과 같이 트리 구조를 가집니다.

*   `custom_components.kocom_wallpad` (Root)
    *   `.transport` : 하위 통신 계층 (TCP/Serial)
    *   `.controller` : 중간 파싱 계층 (Packet/Buffer)
    *   `.gateway` : 상위 관리 계층 (Logic/State)

#### **활용 예시**
패킷 흐름만 깨끗하게 보고 싶다면 `configuration.yaml`에 다음과 같이 설정할 수 있습니다.
```yaml
logger:
  logs:
    custom_components.kocom_wallpad.transport: debug
```

---

### 3. UI 기반 로깅 (UI-Based Strategy)

Home Assistant의 최신 기능을 활용하여 사용자 편의성을 극대화했습니다.

1.  **Hot-Reload Logging:** `configuration.yaml` 수정 없이 UI에서 즉시 로깅 수준을 변경합니다.
2.  **Diagnostic Export:** 디버그 로깅 종료 시 HA가 자동으로 해당 통합구성요소의 로그만 추출하여 파일(`.txt`)로 제공합니다. 이를 통해 사용자는 수천 줄의 `home-assistant.log`를 뒤질 필요 없이 정제된 데이터만 개발자에게 전달할 수 있습니다.

---

### 4. 로그 분석 가이드 (For Developers)

*   **Transport 로그(`LOGGER.info`):** "소켓 연결 성공"과 같은 핵심 라이프사이클.
*   **Controller 로그(`LOGGER.debug`):** "Packet received: raw=..." 전수 기록.
*   **Gateway 로그(`LOGGER.warning`):** "명령 응답 없음" 등 사용자가 알아야 할 예외 상황.

이러한 범주화는 향후 자동화된 로그 분석 툴이나 AI 지원 디버깅을 위한 기초 데이터가 됩니다.
