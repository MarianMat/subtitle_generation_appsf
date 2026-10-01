# Aplikacja Generowanie Napisów V5 — jednoplikowa

Cały kod aplikacji znajduje się w `app.py`. Nie ma własnych importów ani folderu `v5`.

## Wdrożenie
1. Utwórz nowe repozytorium GitHub.
2. Wgraj wszystkie pliki z tego folderu do katalogu głównego repozytorium.
3. W Streamlit Community Cloud ustaw **Main file path** na `app.py`.
4. W Secrets dodaj:

```toml
OPENAI_API_KEY = "twój_klucz"
OPENAI_TRANSCRIPTION_MODEL = "whisper-1"
```

`packages.txt` instaluje FFmpeg. Wersję Pythona wybierz w ustawieniach wdrożenia; nie ma tu `runtime.txt`.

## Funkcje
- wgrywanie i odtwarzanie filmu
- wyodrębnienie audio do MP3
- podział audio na 15-minutowe części
- transkrypcja OpenAI z timestampami segmentów
- edycja i pobieranie SRT
- podgląd filmu z napisami

Model musi obsługiwać `verbose_json` oraz `timestamp_granularities=["segment"]`. Jeśli API zwróci błąd modelu lub timestampów, sprawdź bieżącą dokumentację OpenAI.
