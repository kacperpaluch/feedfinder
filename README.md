# feedfinder

[![Docker Hub](https://img.shields.io/docker/pulls/kpa90/feedfinder?logo=docker)](https://hub.docker.com/r/kpa90/feedfinder)

Wklejasz adres strony, podcastu albo kanału YouTube – dostajesz adres kanału RSS/Atom.
Jedna strona WWW plus proste API w JSON. Jeden plik Pythona, wyłącznie biblioteka standardowa, bez bazy danych i bez stanu.

## Obsługiwane źródła

| Źródło | Co wkleić | Jak znajdowany jest feed |
|---|---|---|
| Dowolna strona WWW | adres strony lub samego feedu | `<link rel="alternate">` w HTML, a gdy go brak – typowe ścieżki (`/feed`, `/rss`, `/rss.xml`, `/feed.xml`, `/atom.xml`, `/index.xml`) |
| Apple Podcasts | `podcasts.apple.com/…/id123…` | oficjalne API iTunes Lookup |
| Spotify | `open.spotify.com/show/…` | Spotify nie udostępnia RSS – podcast jest wyszukiwany po nazwie w katalogu Apple i potwierdzany tytułem najnowszego odcinka |
| Deezer | `deezer.com/show/…` | wyszukiwanie po nazwie w katalogu Apple |
| YouTube | kanał (`/@nazwa`, `/channel/UC…`), film lub playlista | feed kanału albo playlisty |
| SoundCloud | profil użytkownika | feed profilu |
| Reddit | subreddit, użytkownik lub wątek | `.rss` dla danej ścieżki |
| GitHub | repozytorium lub użytkownik | wydania, tagi i commity repozytorium albo aktywność użytkownika |
| Google News | adres wyszukiwania lub tematu | odpowiednik w `/rss` |

Dla Spotify i Deezera wynik bywa przybliżony: jeśli dopasowanie opiera się tylko na tytule albo nie ma dokładnego trafienia, aplikacja pokazuje do pięciu kandydatów z adnotacją – sprawdź, czy to właściwy podcast.

## Uruchomienie

Obraz jest dostępny na [Docker Hub](https://hub.docker.com/r/kpa90/feedfinder) dla `linux/amd64` i `linux/arm64`. Nie trzeba niczego budować ani klonować repozytorium.

### Docker Compose

Zapisz jako `compose.yaml` (lub pobierz [plik z repozytorium](compose.yaml)):

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

Aplikacja działa pod adresem <http://localhost:8000>.

### Portainer

*Stacks → Add stack → Web editor*, wklej powyższy plik i kliknij *Deploy the stack*.

### Samo `docker run`

```bash
docker run -d --name feedfinder --restart unless-stopped --read-only -p 8000:8000 kpa90/feedfinder:latest
```

## Konfiguracja

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `PORT` | `8000` | Port, na którym aplikacja nasłuchuje wewnątrz kontenera. |

Żeby wystawić usługę na innym porcie hosta, wystarczy zmienić mapowanie, np. `"9090:8000"` – zmiennej `PORT` nie trzeba ruszać.

Kontener nie potrzebuje wolumenów: nic nie zapisuje i nie przechowuje żadnych danych.

## Użycie

### Strona WWW

Otwórz `http://localhost:8000` i wklej adres – wyszukiwanie rusza od razu po wklejeniu (albo po kliknięciu *Szukaj*). Każdy znaleziony feed można skopiować jednym kliknięciem lub otworzyć; kopiowanie działa także przez zwykłe `http` w sieci lokalnej.
Wyszukiwanie da się też podlinkować: `http://localhost:8000/?url=<adres>`.

### API

```
GET /api?url=<adres>
```

Schemat `https://` można pominąć. Adres powinien być zakodowany (URL-encoded), maksymalnie 2000 znaków.

```bash
curl -G --data-urlencode "url=https://www.youtube.com/@veritasium" http://localhost:8000/api
```

```json
{"title": "Veritasium", "feeds": [{"url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCHnyfMqiRRG1u-2MsSQLbXA"}], "ok": true}
```

Pola odpowiedzi:

| Pole | Typ | Opis |
|---|---|---|
| `ok` | bool | Czy znaleziono feed. |
| `title` | string | Tytuł strony, kanału lub podcastu (może być pusty). |
| `feeds` | lista | Znalezione feedy. Każdy ma `url` i opcjonalnie `label` (np. „Wydania”, „Tagi”). |
| `note` | string | Opcjonalna uwaga, gdy dopasowanie podcastu jest niepewne. |
| `error` | string | Komunikat błędu – tylko gdy `ok` ma wartość `false`. |

Błąd wyszukiwania też zwraca HTTP 200 – o wyniku decyduje pole `ok`:

```json
{"ok": false, "error": "Na tej stronie nie znaleziono kanału RSS."}
```

## Bezpieczeństwo

- **Ochrona przed SSRF** – aplikacja pobiera wyłącznie adresy `http`/`https` wskazujące na publiczne IP. Adresy prywatne, loopback i link-local są odrzucane, także po przekierowaniu.
- Kontener działa jako użytkownik `nobody`, z systemem plików tylko do odczytu (`read_only: true`).
- Pobierane jest najwyżej 3 MB odpowiedzi, z limitem czasu 10 s.
- **Brak uwierzytelniania i limitu zapytań.** Każdy, kto ma dostęp do portu, może zlecać pobieranie stron z adresu IP Twojego serwera. Przy wystawieniu do internetu postaw przed usługą reverse proxy z autoryzacją (i HTTPS).

## Aktualizacja i rollback

```bash
docker compose pull && docker compose up -d
```

Oprócz `:latest` każde wydanie ma stały tag z krótkim hashem commita (lista na [Docker Hub](https://hub.docker.com/r/kpa90/feedfinder/tags)). Żeby wrócić do starszej wersji, podmień w `compose.yaml` `:latest` na konkretny tag i ponownie wykonaj `docker compose up -d`.

## Uruchomienie ze źródeł

Wymagany jest tylko Python 3 (obraz używa 3.13), bez dodatkowych pakietów:

```bash
python3 app.py            # http://localhost:8000
PORT=9090 python3 app.py  # inny port
```

Własny obraz:

```bash
docker build -t feedfinder .
```

## Ograniczenia

- Spotify i Deezer: działa tylko dla podcastów obecnych w katalogu Apple Podcasts; podcasty na wyłączność nie mają RSS.
- Strony renderowane w całości przez JavaScript albo blokujące boty mogą nie zwrócić feedu.
- Wyniki nie są cache'owane – każde zapytanie pobiera stronę na nowo.
