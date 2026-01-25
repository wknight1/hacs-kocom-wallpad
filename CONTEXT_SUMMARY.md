# Kocom Wallpad Integration Context Summary

## 📌 프로젝트 개요
- **목적:** 코콤 월패드 RS485 통신 통합 (HACS)
- **리포지토리:** `https://github.com/wknight1/hacs-kocom-wallpad`
- **현재 버전:** v2.1.3 (안정성 강화 패치 적용)

## ✅ 완료된 작업
1.  **네임스페이스 및 브랜딩 전환:** `lunDreame` → `wknight1` 전수 교체.
2.  **고성능 아키텍처 도입:**
    -   `RingBuffer` 구현 (메모리 재할당 최소화, `len()` 호출 오류 수정 완료).
    -   `Immediate Polling` 알고리즘 (제어 후 즉시 상태 조회로 동기화 보장).
3.  **시스템 안정성 극대화 (Critical Fix):**
    -   무한 재시작 원인(EOF 무한 루프) 해결 및 루프 내 안전 딜레이(`0.01s`) 추가.
    -   모든 비동기 루프에 `try-except` 예외 격리 적용.
    -   `serial_asyncio` 지연 임포트(Lazy Import)로 부팅 시 블로킹 방지.
4.  **라이브러리 최적화:** `pyserial-asyncio-fast` 시도 후 불안정성으로 인해 안정적인 `pyserial-asyncio`로 롤백.
5.  **문서화:** Mermaid 다이어그램 포함 전문 `README.md` 작성 및 전체 코드 한국어 주석화.

## ⚙️ 주요 기술 명세
- **Transport:** 지수 백오프 재연결, EOF 감지 및 자동 복구.
- **Gateway:** 송신 큐(Queue) 기반 처리, 최대 3회 재시도, 연속 실패 시 세션 재시작.
- **Controller:** 패킷 체크섬 검증, 링버퍼 기반 스트림 파싱.

## 🔍 향후 과제 및 주의사항
- **로그 확인:** 재시작 이슈 재발 시 `custom_components.kocom_wallpad: debug` 설정으로 원인 추적 가능.
- **기기 호환성:** 특정 모델에서 상태 패킷이 다를 경우 디버그 로그의 `raw` 데이터 분석 필요.

---
*본 파일은 다음 세션의 빠른 문맥 파악을 위해 생성되었습니다.*
