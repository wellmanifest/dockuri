# Wellmanifest Dockuri Standard (DOCK-STD-001)

Version: `0.1.0`  
Status: `PROPOSED / ACTIVE`  
Normative Reference: `wellmanifest/dockuri`  
Complementary Standards: [`wellmanifest/apx`](https://github.com/wellmanifest/apx), [`wellmanifest/uriprocess`](https://github.com/wellmanifest/uriprocess), [`wellmanifest/poa`](https://github.com/wellmanifest/poa)

---

## 1. Cel i zasady architektoniczne

Standard **Dockuri** definiuje protokół ultra-szybkiego wywoływania i łączenia w potoki (pipelining) pojedynczych funkcji i procedur pochodzących z heterogenicznych projektów (Python, JavaScript/TypeScript, Rust, PHP, Go, C/C++) bez ponoszenia kosztów zimnego startu kontenerów czy procesów.

### Zasady nadrzędne:
1. **Zero Cold-Start (< 2.0 ms latency)**: Wywołanie funkcji z dowolnego projektu musi odbywać się przez gorącego demona (pre-warmed worker daemon) za pośrednictwem lokalnego gniazda uniksowego (**Unix Domain Socket - UDS**) lub pamięci operacyjnej, eliminując opóźnienia `docker run` czy ponownego startu interpretera.
2. **Zero-Copy dla dużych ładunków**: Dane powyżej 64 KB (obrazy, audio, wektory, pliki binarne) nie są serializowane w JSON/NDJSON, lecz przekazywane za pomocą deskryptorów pamięci współdzielonej (`/dev/shm` lub `mmap`).
3. **Determinizm i Audytowalność**: Każde wywołanie procedury generuje jednoznaczny identyfikator, a cały potok funkcji (pipeline DAG) generuje zbiorczy kwit wykonania (**CompositeExecutionReceipt** zgodny z `wellmanifest.wellman/receipt/v1`).
4. **Językowa poligloticzność**: Klient Dockuri może w jednym łańcuchu połączyć funkcję w Rust z funkcją w Pythonie i funkcją w Node.js bez wiedzy o ich wewnętrznych stosach technologicznych.

---

## 2. Reguły normatywne

### `DOCK-MAN-001: Procedure Manifest Contract`
Każdy projekt włączany do siatki Dockuri musi posiadać w swoim korzeniu plik [`dockuri.json`](schemas/dockuri-manifest.schema.json).
Manifest musi określać:
* `$schema`: URL schematu `https://wellmanifest.org/schemas/dockuri-v1.json`.
* `app`: Identyfikator aplikacji/projektu (np. `taskand`, `faktury`, `base64`).
* `version`: Wersja semantyczna semver.
* `transport`: Domyślny transport IPC (UDS, stdio, http) ze ścieżką do gniazda socket.
* `procedures`: Słownik eksportowanych procedur, ich schematy wejścia/wyjścia (JSON Schema) oraz deklarację efektu ubocznego (`effect: pure | idempotent | mutating`).

### `DOCK-IPC-001: IPC Protocol Envelope`
Komunikacja pomiędzy orkiestratorem Dockuri a workerem odbywa się za pomocą ramek **NDJSON** (Newline Delimited JSON) kodowanych w UTF-8, przesyłanych przez strumień UDS lub stdio.

#### Ramka żądania (Request):
```json
{
  "id": "req-98fbc12a",
  "proc": "base64.encode",
  "args": { "text": "hello world" },
  "ctx": { "trace_id": "tr-001", "timeout_ms": 500 },
  "shm": null
}
```

#### Ramka odpowiedzi (Response):
```json
{
  "id": "req-98fbc12a",
  "ok": true,
  "result": { "encoded": "aGVsbG8gd29ybGQ=" },
  "error": null,
  "metrics": { "duration_us": 85 }
}
```

### `DOCK-UDS-001: Unix Domain Socket Path & Permissions`
1. Ścieżka do gniazda uniksowego jest wyznaczana według hierarchii:
   * Zmienna środowiskowa `DOCKURI_SOCKET`.
   * Zmienna środowiskowa `DOCKURI_RUN_DIR/<app>.sock`.
   * Standardowa ścieżka systemowa `/run/dockuri/<app>.sock` (jeśli proces ma uprawnienia zapisu).
   * Ścieżka użytkownika `~/.dockuri/run/<app>.sock`.
2. Plik gniazda musi posiadać uprawnienia `0660` (lub `0600`), umożliwiając dostęp uprawnionym procesom użytkownika lub grupy wykonawczej.

### `DOCK-SHM-001: Zero-Copy Shared Memory Protocol`
1. Dla ładunków przekraczających 64 KB (np. wideo, dźwięk, ramki graficzne, tablice numpy/safetensors) dane są umieszczane w pamięci RAM `/dev/shm/dockuri/<buffer_id>`.
2. W ramce IPC pole `shm` przyjmuje strukturę:
```json
{
  "shm": {
    "path": "/dev/shm/dockuri/buf-4412.raw",
    "offset": 0,
    "size": 1048576,
    "format": "raw/bytes"
  }
}
```
3. Worker mapuje pamięć do swojej przestrzeni adresowej za pomocą `mmap` i zwraca wynik również w buforze SHM bez kopiowania danych do pętli JSON.

### `DOCK-LFT-001: Auto-Spawn and Graceful Fallback`
1. W przypadku, gdy żądany socket UDS nie istnieje lub demon nie odpowiada:
   * Klient Dockuri sprawdza dyrektywę `transport.auto_spawn` w `dockuri.json`.
   * Jeśli flaga jest włączona (`true`), klient jednorazowo uruchamia polecenie z `transport.spawn_cmd` w tle (demonizuje) i czeka do 500 ms na gotowość gniazda.
   * W razie braku możliwości uruchomienia demona, klient stosuje `fallback` zdefiniowany w manifeście (`native` lub `http`).

### `DOCK-PNG-001: System Ping & Latency Budget`
Każdy zgodny worker Dockuri **musi** implementować wbudowaną procedurę systemową `__ping__`:
* Żądanie: `{"id": "...", "proc": "__ping__", "args": {}}`
* Odpowiedź: `{"id": "...", "ok": true, "result": {"status": "pong", "runtime": "cpython-3.11", "uptime_s": 1420}}`
* Budżet czasowy: Czas round-trip żądania `__ping__` przez UDS **nie może przekraczać 2.0 ms** (wymóg testu zgodności).

### `DOCK-PIP-001: Pipeline Composition & Composite Execution Receipt`
1. Dockuri umożliwia łączenie procedur w deklaratywny graf DAG:
```json
{
  "pipeline": "process_invoice",
  "stages": [
    { "step": 1, "use": "proc://base64.decode", "input": "$input.raw_pdf" },
    { "step": 2, "use": "proc://ocr.extract_text", "input": "$stages.1.result" },
    { "step": 3, "use": "proc://faktury.parse_nip", "input": "$stages.2.result" }
  ]
}
```
2. Wynik wykonania całego potoku jest autoryzowany jednym kwitem wykonania (**CompositeExecutionReceipt**) zawierającym skróty kryptograficzne każdego etapu bez narzutu dyskowego $O(1)$.
