# Fold8 Ultra YouTube patch source

이 브랜치는 `main`과 분리되어 있으며 Fold8 Ultra용 YouTube 패치 번들 빌드에만 사용합니다.

기준: `anddea/revanced-patches` v4.3.0 (`d4c3ce4b67155c4ea728aa831f5485bdb3d75934`).

## 자동 레이아웃
- 접힘 + 세로: 순정 YouTube 동작
- 접힘 + 가로: 순정 YouTube 동작
- 펼침 + 세로: Phone UI 강제, widthDp <= 480
- 펼침 + 가로: Tablet UI 강제, widthDp >= 600
- `SM-F976*`에서만 동작하며 `Change form factor = Default`일 때 활성화

## 권장 기능
AMOLED, Shorts 광고 숨김, Return YouTube Dislike, Wide search bar, 플레이어/툴바 Cast 버튼 숨김, GmsCore support(비루팅).

## 휴대폰에서 사용
빌드가 성공하면 이 브랜치에 `fold8-patches.mpp`와 `patches-bundle.json`이 자동 생성됩니다.

패치 소스:
https://raw.githubusercontent.com/Adamkk111/weather-calendar/fold8-youtube-patches/patches-bundle.json

현재 기반은 anddea/Morphe 계열이라 `.mpp`를 지원하는 Morphe Manager 또는 URV 계열 매니저에서 사용하는 것이 맞습니다.

수정 파일은 원 저작권 및 GPLv3 Section 7 고지를 유지합니다.
