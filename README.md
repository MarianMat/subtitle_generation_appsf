# Generator napisów V5

Samodzielna aplikacja Streamlit do generowania napisów SRT z filmów i audio.

## Funkcje
- Wgrywanie wideo / audio
- Wyodrębnianie audio przez FFmpeg (bez pydub)
- Dzielenie długich plików na segmenty
- Transkrypcja przez OpenAI (Whisper)
- Generowanie i edycja pliku SRT
- Pobieranie SRT / TXT
- Podgląd wideo z napisami

## Wdrożenie na Streamlit Cloud
1. Utwórz nowe repozytorium GitHub i wgraj zawartość tego folderu
   do katalogu głównego repo (nie ZIP-em, tylko pliki).
2. Wejdź na https://share.streamlit.io → *New app*.
3. Wskaż repozytorium i ustaw **Main file path** na `app.py`.
4. W *Settings → Secrets* dodaj:
