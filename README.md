# Da Moa PWA 셸

Streamlit Cloud의「앱 설치」는 이름이 항상 **Streamlit**으로 고정됩니다.  
홈화면에 **Da Moa**로 설치하려면, 이 `pwa/` 폴더를 **별도 정적 호스팅**하고 그 주소에서 설치하세요.

## 1. URL 설정

`config.js`의 `iframeUrl`을 실제 Streamlit Cloud 주소로 바꿉니다.

```js
iframeUrl: "https://실제앱이름.streamlit.app/?embed=true&show_footer=false",
```

## 2. 배포

GitHub Pages / Netlify / Cloudflare Pages 등에 `pwa/` 폴더만 배포합니다.

예: GitHub Pages라면 이 폴더를 `docs/`로 옮기거나 Pages 소스를 `pwa`로 지정.

## 3. 폰에서 설치

1. 배포된 **PWA 셸 주소**(`.streamlit.app`가 아님)를 폰 브라우저로 연다  
2. 홈 화면에 추가 / 앱 설치  
3. 이름이 **Da Moa**로 표시되는지 확인
