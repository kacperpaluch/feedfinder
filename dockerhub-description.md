# feedfinder

Wklejasz adres strony, podcastu albo kanału YouTube – dostajesz adres kanału RSS/Atom.
Strona WWW plus proste API w JSON. Jeden plik Pythona, wyłącznie biblioteka standardowa, bez bazy danych i bez stanu.

Kod źródłowy i pełna dokumentacja: <https://github.com/kacperpaluch/feedfinder>

## Obsługiwane źródła

- dowolna strona WWW (`<link rel="alternate">` oraz typowe ścieżki typu `/feed`, `/rss.xml`)
- Apple Podcasts, Spotify, Deezer, SoundCloud
- YouTube (kanały, filmy, playlisty)
- Reddit, GitHub (wydania, tagi, commity), Google News

## Uruchomienie

`compose.yaml`:

```yaml
services:
  feedfinder:
    image: kpa90/feedfinder:latest
    container_name: feedfinder
    restart: unless-stopped
    ports:
      - "8000:8000" # host:kontener – zmień lewą stronę, aby wystawić inny port
    environment:
      - PORT=8000 # port nasłuchu wewnątrz kontenera
    read_only: true
```

```bash
docker compose up -d
```

Albo bez Compose:

```bash
docker run -d --name feedfinder --restart unless-stopped --read-only -p 8000:8000 kpa90/feedfinder:latest
```

Aplikacja działa pod adresem `http://localhost:8000`. Wolumeny nie są potrzebne.

## Konfiguracja

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `PORT` | `8000` | Port nasłuchu wewnątrz kontenera. |

## API

```bash
curl -G --data-urlencode "url=https://www.youtube.com/@veritasium" http://localhost:8000/api
```

```json
{"title": "Veritasium", "feeds": [{"url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCHnyfMqiRRG1u-2MsSQLbXA"}], "ok": true}
```

Gdy feedu nie ma: `{"ok": false, "error": "…"}` (również z HTTP 200).

## Tagi

- `latest` – najnowsza wersja
- `<krótki hash commita>` – stałe wydania, do rollbacku

Platformy: `linux/amd64`, `linux/arm64`.

## Bezpieczeństwo

Aplikacja odrzuca adresy prywatne i lokalne (ochrona przed SSRF), działa jako `nobody` na systemie plików tylko do odczytu.
Nie ma uwierzytelniania ani limitu zapytań – przy wystawieniu do internetu postaw przed nią reverse proxy z autoryzacją.
