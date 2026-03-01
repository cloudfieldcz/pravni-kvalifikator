# Právní Kvalifikátor — technická dokumentace implementace

Datum: 2026-02-26

Tento dokument popisuje *aktuální implementaci v repozitáři* (nikoli původní návrhy). Je určen pro vývojáře, kteří chtějí systém spustit, upravovat, nebo pochopit tok dat mezi webem, agenty, MCP serverem a SQLite databázemi.

## 1) Přehled architektury

Systém kvalifikuje popsaný skutek jako:
- **trestný čin** (typ `TC`) podle trestního zákoníku a speciálních trestních zákonů,
- nebo **přestupek** (typ `PR`) primárně podle přestupkového zákona.

Vysoká úroveň:

```text
Web (FastAPI + Jinja2 + SSE)
  └─ spustí LangGraph pipeline (5 agentů)
       ├─ LLM (Azure OpenAI chat)
       └─ MCP klient (SSE/JSON-RPC)
             └─ MCP server (FastMCP)
                   └─ laws.db (SQLite + sqlite-vec)

+ sessions.db (SQLite) pro web session + výsledky + agent log
```

Klíčové vlastnosti:
- **MCP server je stateless** (jen čte/zapisuje do `laws.db`, embeddingy jsou v téže DB).
- **Web vrstva** drží uživatelské session a historii kvalifikací v `sessions.db`.
- **SSE streaming**:
  - Web endpoint poskytuje `EventSource` stream průběžných stavů agentů.
  - Agent logování běží přes `agents/activity.py` a může se perzistovat do `sessions.db` callbackem registrovaným webem.

## 2) Struktura repozitáře (prakticky)

- `src/pravni_kvalifikator/mcp/` — MCP server, SQLite vrstva, scraper/parser/indexer.
- `src/pravni_kvalifikator/agents/` — LangGraph workflow + agenti.
- `src/pravni_kvalifikator/web/` — FastAPI web, šablony, session DB.
- `scripts/` — offline pipeline (scrape → metadata → embeddings).
- `data/` — runtime artefakty (DB soubory); do gitu se necommitují (viz `.gitignore`).

## 3) Spuštění a základní příkazy

### 3.1 Požadavky
- Python **3.12+**
- `uv` (správa závislostí)

### 3.2 Instalace

```bash
uv sync
uv sync --group dev
```

### 3.3 Lokální běh

- MCP server (STDIO entrypoint):

```bash
uv run pq-mcp
```

- MCP server přes HTTP/SSE (pro web/klienta):

```bash
uv run uvicorn pravni_kvalifikator.mcp.server:app --port 8001
```

- Web aplikace:

```bash
uv run pq-web
```

Konfigurace je přes `.env` (viz `src/pravni_kvalifikator/shared/config.py`).

## 4) Konfigurace (`shared/config.py`)

Konfigurace je implementovaná jako Pydantic `Settings` singleton:
- `get_settings()` vrací cached instanci.
- `.env` se načítá automaticky (pokud existuje).

Důležité proměnné:
- Azure OpenAI:
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_API_KEY`
  - `AZURE_OPENAI_CHAT_DEPLOYMENT` (default `gpt-5.2`)
  - `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` (default `text-embedding-3-large`)
- DB:
  - `LAWS_DB_PATH` (default `./data/laws.db`)
  - `SESSIONS_DB_PATH` (default `./data/sessions.db`)
- Web/MCP:
  - `MCP_SERVER_URL` (default `http://localhost:8001`)
  - `WEB_HOST`, `WEB_PORT`, `MCP_SERVER_HOST`, `MCP_SERVER_PORT`
- Scraper:
  - `SCRAPER_DELAY` (default 1.5s)
  - `SCRAPER_USER_AGENT`

Konstanta embedding dimenze:
- `EMBEDDING_DIMENSIONS = 1536`

## 5) Databáze `laws.db` (SQLite + sqlite-vec)

Implementace: `src/pravni_kvalifikator/mcp/db.py` (`class LawsDB`).

### 5.1 Relační schéma

Tabulky:
- `laws`
  - `sbirkove_cislo` (unikátní), `nazev`, `typ`, `oblasti` (JSON string), `popis`, `content_hash` (SHA-256 HTML obsahu pro detekci změn)
- `chapters`
  - vazba na `laws(id)`
  - členění: `cast_*`, `hlava_*`, `dil_*`, plus `popis`
  - unikátnost: `UNIQUE(law_id, cast_cislo, hlava_cislo, dil_cislo)`
- `paragraphs`
  - vazba na `chapters(id)`
  - `cislo` je **TEXT** (např. `"205a"`), `plne_zneni`, volitelné `metadata` (JSON string)
  - unikátnost: `UNIQUE(chapter_id, cislo)`
- `damage_thresholds`
  - hranice škod (seed při `create_tables()`)

Poznámka: připojení DB zapíná:
- `PRAGMA journal_mode=WAL`
- `PRAGMA foreign_keys=ON`
- načtení rozšíření `sqlite_vec.load(conn)`

### 5.2 Vektorové schéma (sqlite-vec)

Virtual tables (`vec0`):
- `vec_laws(law_id PRIMARY KEY, embedding float[1536])`
- `vec_chapters(chapter_id PRIMARY KEY, embedding float[1536])`
- `vec_paragraphs(paragraph_id PRIMARY KEY, embedding float[1536])`

Embeddingy se ukládají jako BLOB přes `struct.pack("{n}f", *embedding)`.

### 5.3 Vektorové dotazy

Vektorové hledání používá syntaxi sqlite-vec:

```sql
WHERE v.embedding MATCH ? AND k = ?
ORDER BY v.distance
```

Filtrování podle `law_id` / `chapter_id` se dělá aplikačně:
- při filtrování se načte `top_k * 3` výsledků, pak se odfiltrují a vezme prvních `top_k`.

### 5.4 Hranice škod

Tabulka `damage_thresholds` se seeduje při `create_tables()`.

Aktuálně seed v kódu používá kategorie a hranice:
- `nepatrná`: 0–9 999
- `nikoli nepatrná`: 10 000–49 999
- `větší`: 50 000–99 999
- `značná`: 100 000–999 999
- `velkého rozsahu`: 1 000 000+

Upozornění: názvosloví a hranice se můžou lišit od přesného znění § 138 TZ; berte to jako implementační konfiguraci v DB (případně kandidát na úpravu).

## 6) Databáze `sessions.db` (web session, výsledky, agent log)

Implementace: `src/pravni_kvalifikator/web/session.py` (`class SessionDB`).

Tabulky:
- `sessions(id TEXT PRIMARY KEY, created_at, updated_at)`
- `qualifications`
  - `id` (autoincrement)
  - `session_id` FK → `sessions`
  - `popis_skutku`, `typ` (`TC`/`PR`)
  - `stav` (`pending`/`processing`/`completed`/`error`)
  - `vysledek` (JSON string), `error_message`, `completed_at`
- `agent_log`
  - `qualification_id` FK → `qualifications`
  - `agent_name`, `stav`, `zprava`, `data` (JSON string)

## 7) MCP server (FastMCP)

Implementace:
- `src/pravni_kvalifikator/mcp/main.py` — definice toolů
- `src/pravni_kvalifikator/mcp/server.py` — SSE/HTTP transport pro uvicorn

### 7.1 Transport

V projektu se používají dva režimy:
- **STDIO** (`pq-mcp`) — `FastMCP.run()`
- **SSE/HTTP** (`uvicorn pravni_kvalifikator.mcp.server:app`) — endpoint `/sse`

### 7.2 Lazy inicializace

- `LawsDB` se inicializuje lazy (`_get_db()`), cesta je z `Settings.laws_db_path`.
- `EmbeddingClient` se inicializuje lazy (`_get_embedder()`), používá Azure OpenAI embedding deployment.

### 7.3 Tooling API (9 nástrojů)

Všechny tool funkce vrací `str` — **JSON string** (`json.dumps(..., ensure_ascii=False, indent=2)`).

Navigace:
- `list_laws(typ: str | None)`
- `list_chapters(law_id: int)`
- `list_paragraphs(chapter_id: int)`
- `get_paragraph_text(paragraph_id | law_sbirkove_cislo+paragraph_cislo)`
- `get_damage_thresholds()`

Sémantika (vyžaduje embeddingy):
- `search_laws(query: str, top_k: int = 5)`
- `search_chapters(query: str, law_id: int | None = None, top_k: int = 5)`
- `search_paragraphs(query: str, chapter_id: int | None = None, top_k: int = 10)`

Keyword:
- `search_paragraphs_keyword(keywords: str, chapter_id: int | None = None, top_k: int = 10)`

## 8) MCP klient (`shared/mcp_client.py`)

Agenti komunikují s MCP serverem přes SSE/JSON-RPC:

- Otevře se `GET {MCP_SERVER_URL}/sse` a čte se SSE stream.
- První `data:` zpráva obsahuje session URL.
- Klient pošle `initialize` (id=1) POSTem na session URL.
- Po úspěšném init pošle `tools/call` (id=2) a čeká na odpověď.

Návratová hodnota je typicky `text` z `result.content[0].text`, což je JSON string vyprodukovaný MCP tool funkcí.

## 9) Agent pipeline (LangGraph)

Implementace:
- `src/pravni_kvalifikator/agents/orchestrator.py`
- konkrétní agenti: `law_identifier.py`, `head_classifier.py`, `paragraph_selector.py`, `qualifier.py`, `reviewer.py`

### 9.1 Celkový tok pipeline

```text
               ┌──────────────────────┐
               │   Popis skutku       │
               │   + typ (TC/PR)      │
               └──────────┬───────────┘
                          │
                   route_by_type
                     ┌────┴─────┐
               PR    │          │   TC
                     ▼          │
         ┌────────────────┐     │
         │  Agent 0:      │     │
         │  Law Identifier│     │
         │  (jen PR)      │     │
         └───────┬────────┘     │
                 │              │
                 ▼              ▼
         ┌─────────────────────────┐
         │  Agent 1:               │
         │  Head Classifier        │
         └────────────┬────────────┘
                      │ error? ──► END
                      ▼
         ┌─────────────────────────┐
         │  Agent 2:               │
         │  Paragraph Selector     │
         └────────────┬────────────┘
                      │ error? ──► END
                      ▼
         ┌─────────────────────────┐
         │  Agent 3:               │
         │  Qualifier              │
         └────────────┬────────────┘
                      │ error? ──► END
                      ▼
         ┌─────────────────────────┐
         │  Agent 4:               │
         │  Reviewer               │
         └────────────┬────────────┘
                      ▼
                  Výsledek
```

### 9.2 Stav (State)

Stav je TypedDict `QualificationState` (viz `agents/state.py`):

```text
QualificationState
│
│── popis_skutku: str              ◄── vstup
│── typ: str ("TC" / "PR")        ◄── vstup
│── qualification_id: int          ◄── vstup (ID pro logování)
│
│── identified_laws: list[dict]    ◄── Agent 0 (jen PR)
│── candidate_chapters: list[dict] ◄── Agent 1
│── candidate_paragraphs: list[dict] ◄── Agent 2
│
│── kvalifikace: list[dict]        ◄── Agent 3
│── skoda: dict                    ◄── Agent 3
│── okolnosti: dict                ◄── Agent 3
│
│── final_kvalifikace: list[dict]  ◄── Agent 4
│── review_notes: list[str]        ◄── Agent 4
│
│── error: str | None              ◄── při chybě → END
```

Agenti vracejí **pouze změněné klíče** — LangGraph dělá merge automaticky.

### 9.3 Routing

`route_by_type(state)`:
- `PR` → `law_identifier` (přestupky potřebují identifikaci zákonů)
- `TC` → `head_classifier` (vždy TZ 40/2009)

Po každém kroku se kontroluje `state["error"]` a při chybě se pipeline ukončí.

### 9.4 Agenti — detailní popis

#### Agent 0: Law Identifier (jen přestupky)

- **Účel**: Identifikovat relevantní zákony pro přestupek (pro TC se přeskakuje — vždy TZ).
- **MCP volání**: `search_laws(query=popis_skutku, top_k=10)` — sémantické hledání přes `vec_laws`.
- **LLM zpracování**: Dostane popis skutku + top 10 zákonů. Ohodnotí relevanci každého.
- **Filtr**: confidence > 0.3 (škála: 0.7–1.0 vysoce relevantní, 0.3–0.7 možná, <0.3 vyloučen).
- **Výstup**: `identified_laws = [{ law_id, nazev, confidence, reason }]`

#### Agent 1: Head Classifier

- **Účel**: Klasifikovat relevantní hlavy (kapitoly) zákonů.
- **MCP volání**:
  - Pro TC: `search_chapters(query=popis, top_k=10)` — hledá ve všech hlavách TZ.
  - Pro PR: pro každý identifikovaný zákon `search_chapters(query=popis, law_id=law_id, top_k=5)`.
- **LLM zpracování**: Merguje výsledky ze všech vyhledávání, zvažuje souběh (jednočinný i vícečinný).
- **Filtr**: confidence > 0.3.
- **Výstup**: `candidate_chapters = [{ chapter_id, hlava_nazev, law_nazev, confidence, reason }]`

#### Agent 2: Paragraph Selector

- **Účel**: Vybrat konkrétní paragrafy kombinací sémantického + klíčového hledání.
- **MCP volání** (pro každou kandidátní hlavu):
  1. `search_paragraphs(query=popis, chapter_id=ch_id, top_k=5)` — sémantické hledání (vec)
  2. `search_paragraphs_keyword(keywords=popis, chapter_id=ch_id, top_k=5)` — klíčové hledání (LIKE)
  3. `get_paragraph_text(paragraph_id=pid)` — plný text pro každý nalezený paragraf

```text
  Sémantické výsledky     Klíčové výsledky
  (vec_paragraphs)        (SQL LIKE)
         │                      │
         └──────────┬───────────┘
                    ▼
           Merge + deduplikace
           (podle paragraph_id)
                    │
                    ▼
           get_paragraph_text()
           pro každý kandidát
                    │
                    ▼
              LLM hodnocení
```

- Duální vyhledávání zajišťuje, že se najdou jak **synonyma** (sémantické: "ukradl" → "přisvojí si"), tak **přesné právní termíny** (klíčové: "násilí proti úřední osobě").
- **Filtr**: relevance_score > 0.3.
- **Výstup**: `candidate_paragraphs = [{ paragraph_id, cislo, nazev, plne_zneni, relevance_score, matching_elements }]`

#### Agent 3: Qualifier (jádro kvalifikace)

- **Účel**: Kompletní právní kvalifikace — rozbor znaků skutkové podstaty.
- **MCP volání**: `get_damage_thresholds()` — hranice škod dle § 138 TZ.
- **LLM analyzuje 6 aspektů**:

| Aspekt | Popis |
|--------|-------|
| Znaky skutkové podstaty | objekt, objektivní stránka, subjekt, subjektivní stránka |
| Kvalifikované podstaty | vyšší odstavce (odst. 2, 3, 4) s přitěžujícími okolnostmi |
| Škoda | odhad výše → kategorie dle § 138 (nikoli nepatrná ≥10K, větší ≥100K, značná ≥1M, velkého rozsahu ≥10M Kč) |
| Stadium | dokonaný / pokus / příprava |
| Forma účastenství | pachatel (§ 22) / spolupachatel (§ 23) / účastník (§ 24) |
| Confidence | 0.9–1.0 všechny znaky, 0.7–0.9 většina, 0.5–0.7 některé chybí, <0.3 vyloučen |

- **Výstup**:
  - `kvalifikace = [{ paragraf, nazev, confidence, duvod_jistoty, chybejici_znaky, stadium, forma_zavineni }]`
  - `skoda = { odhadovana_vyse, kategorie, relevantni_hranice }`
  - `okolnosti = { organizovana_skupina, recidiva, priprava_trestna }`

#### Agent 4: Reviewer

- **Účel**: Křížová kontrola konzistence, úplnosti a právní správnosti.
- **MCP volání**: žádné — pracuje čistě s LLM nad existujícím stavem.
- **LLM kontroluje 5 oblastí**:
  1. **Souběh trestných činů** — jednočinný (jeden skutek → více TČ, např. vloupání = krádež + porušování domovní svobody) i vícečinný. Může přidat chybějící kvalifikace.
  2. **Správnost kvalifikace** — správné odstavce/písmena, forma zavinění, stadium, kategorie škody.
  3. **Konzistence confidence** — příliš vysoké pro neúplné → snížit, příliš nízké pro zřejmé → zvýšit.
  4. **Klasifikace TC vs PR** — mohl by skutek být opačného typu?
  5. **Review notes** — dokumentace každé úpravy s odůvodněním.
- **Výstup**:
  - `final_kvalifikace = [{ ...pole z Agent 3..., review_adjustment }]`
  - `review_notes = ["Přidán souběh s § 178 TZ...", ...]`

### 9.5 Přehled MCP volání podle agenta

| Agent | MCP nástroje | Počet volání |
|-------|-------------|-------------|
| 0: Law Identifier | `search_laws` | 1× |
| 1: Head Classifier | `search_chapters` | 1× (TC) nebo N× (PR, N = počet zákonů) |
| 2: Paragraph Selector | `search_paragraphs`, `search_paragraphs_keyword`, `get_paragraph_text` | 2×N + M (N = hlav, M = nalezených §) |
| 3: Qualifier | `get_damage_thresholds` | 1× |
| 4: Reviewer | — | žádné |

### 9.6 Error handling

Každý uzel je obalen `_safe_node()`:
- loguje výjimku,
- zapíše `agent_activity` se stavem `error`,
- a vrátí jen `{ "error": "..." }`.

### 9.7 Activity logging a SSE

Implementace: `src/pravni_kvalifikator/agents/activity.py`.

```text
  Agent                    Activity System                    Web UI
    │                           │                               │
    │  log("started", ...)      │                               │
    │ ─────────────────────►    │──► _db_logger (sessions.db)   │
    │                           │──► _sse_queues[id].put()      │
    │                           │ ──────────────────────────►   │
    │                           │         SSE event              │
    │  log("completed", ...)    │                               │
    │ ─────────────────────►    │──► broadcast to SSE + DB      │
```

- SSE: `register_sse_queue(qualification_id)` vytvoří `asyncio.Queue`, do které se posílají eventy.
- DB persistence: web vrstva registruje callback přes `register_db_logger(fn)` při startu.
- Aktuální SSE payload posílá: `agent_name`, `stav`, `zprava`.
- Volitelný parametr `data` se do SSE **aktuálně neposílá** (pouze do DB callbacku).
- Agenti neví o webové vrstvě — čistý callback pattern bez cirkulárních závislostí.

## 10) Web aplikace (FastAPI + Jinja2)

Implementace:
- `src/pravni_kvalifikator/web/main.py` — `create_app()` + lifespan
- `src/pravni_kvalifikator/web/routes.py` — routy
- `src/pravni_kvalifikator/web/templates/` — `base.html`, `index.html`, `result.html`
- `src/pravni_kvalifikator/web/static/` — `app.js`, `style.css`

### 10.1 Endpoints

- `GET /`
  - vrací hlavní stránku
  - session cookie `session_id` (HTTP-only) se vytvoří, pokud chybí

- `POST /qualify`
  - vstup: JSON (`QualifyRequest`) obsahuje `popis_skutku`, `typ`
  - výstup: JSON (`QualifyResponse`) obsahuje `qualification_id`
  - spouští pipeline na pozadí (`BackgroundTasks`)

- `GET /qualify/{qualification_id}/stream`
  - SSE stream průběhu
  - eventy: `agent_update`, keepalive `ping`, a `done`
  - stream se ukončí, pokud:
    - přijde event se `stav == "error"`, nebo
    - přijde `completed` od agenta `reviewer`, nebo
    - DB už hlásí `stav in (completed, error)` (fallback po timeoutu)

- `GET /qualify/{qualification_id}`
  - vrací uložený záznam z `sessions.db` včetně `vysledek` (pokud je, parsuje se JSON)

- `GET /history`
  - zobrazí historii kvalifikací aktuální session

### 10.2 Session cookie

Cookie `session_id` je:
- HTTP-only
- `max_age = 24h * session_expiry_days`

## 11) Autentizace a správa tokenů

Implementace: `src/pravni_kvalifikator/web/auth.py`.

### 11.1 Přehled

Systém používá **stateless HMAC-SHA256 tokeny** — server nepotřebuje ukládat platné tokeny do DB. Validita se ověřuje kryptograficky z obsahu tokenu a sdíleného tajného klíče (`AUTH_HMAC_KEY`).

```text
┌─────────────────────────────────────────────────────────────┐
│  Token: jan:20271231:a1b2c3d4e5f6...                        │
│         ───  ────────  ──────────────                       │
│          │      │           │                               │
│      username  expiry    HMAC-SHA256(key, "jan:20271231")   │
└─────────────────────────────────────────────────────────────┘
```

Klíčové vlastnosti:
- **Zapnutí/vypnutí**: `AUTH_HMAC_KEY` v `.env` — prázdný řetězec = auth vypnutá (dev režim).
- **Stateless**: žádná tabulka tokenů v DB, validace čistě z HMAC podpisu + data expirace.
- **Session binding**: po přihlášení se `username` z tokenu stane session ID → izolace dat mezi uživateli.

### 11.2 Formát tokenu

```
USERNAME:YYYYMMDD:HEX_TOKEN
```

| Část | Pravidla | Příklad |
|------|----------|---------|
| `USERNAME` | `[a-zA-Z0-9._-]+`, max 64 znaků | `jan`, `cf`, `admin.user` |
| `YYYYMMDD` | datum expirace (inclusive) | `20271231` |
| `HEX_TOKEN` | `HMAC-SHA256(AUTH_HMAC_KEY, "USERNAME:YYYYMMDD").hexdigest()` | `a1b2c3d4...` (64 hex znaků) |

### 11.3 Generování tokenů (CLI)

Entry point: `pq-token` (definován v `pyproject.toml`, funkce `main_cli` v `auth.py`).

```bash
uv run pq-token --username <jmeno> --valid-until <YYYYMMDD>
```

Příklad:

```bash
uv run pq-token --username jan --valid-until 20271231
# Token: jan:20271231:a1b2c3d4e5f6...
```

Požadavky:
- `AUTH_HMAC_KEY` musí být nastavený v `.env` (jinak chyba).
- Username musí vyhovovat regex `^[a-zA-Z0-9._-]+$`.
- Datum musí být validní ve formátu `YYYYMMDD`.

### 11.4 Validace tokenu

Funkce `validate_token(token, key)` (`auth.py:50`):

1. Parse formátu `USERNAME:YYYYMMDD:HEX` → `ValueError` při špatném formátu.
2. Výpočet očekávaného HMAC: `HMAC-SHA256(key, "USERNAME:YYYYMMDD")`.
3. Timing-safe porovnání: `hmac.compare_digest(hex_token, expected)` — ochrana proti timing útokům.
4. Kontrola expirace: `YYYYMMDD >= today` (token platí celý den expirace).
5. Návrat: `username` (platný) nebo `None` (neplatný).

### 11.5 Přihlašovací flow

```text
GET /login
  └─ Formulář s polem pro token

POST /login (token=...)
  ├─ validate_token()
  ├─ OK → set_cookie("auth_token", httponly, secure, samesite=lax)
  │        max_age = session_expiry_days × 24h (default 30 dní)
  │        redirect → /
  └─ FAIL → 401, zobrazí chybovou hlášku

GET /logout
  └─ delete_cookie("auth_token"), redirect → /login
```

### 11.6 FastAPI middleware

Dependency `require_auth` (`auth.py:91`) je aplikovaný na všechny chráněné routy:

- `AUTH_HMAC_KEY` prázdný → přeskočí (auth vypnutá).
- Chybí cookie `auth_token` → `AuthRequired` exception → redirect na `/login`.
- Neplatný token → `AuthRequired` exception → redirect na `/login`.
- Platný token → `request.state.username = username`.

Exception handler v `web/main.py` zachytí `AuthRequired` a odpoví redirectem na `/login` + smaže neplatnou cookie.

### 11.7 Session binding

Po přihlášení se `username` z tokenu používá jako `session_id`:
- `SessionDB.create_session_with_id(username)` — idempotentní vytvoření session.
- Všechny kvalifikace a agent logy jsou vázané na tento session ID.
- Uživatelé nemají přístup k datům jiných uživatelů (`_check_qualification_access()` v `routes.py`).

### 11.8 Bezpečnostní vlastnosti

| Vlastnost | Implementace |
|-----------|-------------|
| HMAC-SHA256 podpis | Token nelze padělat bez znalosti `AUTH_HMAC_KEY` |
| Timing-safe porovnání | `hmac.compare_digest()` — ochrana proti timing útokům |
| Expirace | Token je neplatný po datu `YYYYMMDD` |
| HTTP-only cookie | JavaScript nemá přístup k tokenu |
| Secure flag | Cookie se posílá pouze přes HTTPS (v produkci) |
| SameSite=lax | Ochrana proti CSRF |
| Izolace dat | Uživatel vidí pouze své kvalifikace |

### 11.9 Konfigurace

| Proměnná | Default | Popis |
|----------|---------|-------|
| `AUTH_HMAC_KEY` | `""` (vypnuto) | Tajný klíč pro HMAC podpis tokenů |
| `SESSION_EXPIRY_DAYS` | `30` | Max. doba platnosti auth cookie (dny) |

## 12) Offline pipeline skripty

Tři skripty se pouští **v tomto povinném pořadí**:

```text
┌─────────────────────┐     ┌──────────────────────┐     ┌───────────────────────┐
│  1. load_laws.py    │ ──► │ 2. generate_metadata │ ──► │ 3. generate_embeddings│
│  Scrape + Parse     │     │    .py               │     │    .py                │
│  + uložení do DB    │     │  LLM obohacení       │     │  Vektorové embeddingy │
└─────────────────────┘     └──────────────────────┘     └───────────────────────┘
```

**Pořadí je důležité**: krok 2 generuje `popis` hlav, který se v kroku 3 použije jako vstupní text pro embedding. Bez kroku 2 budou embeddingy hlav méně kvalitní (fallback text místo LLM popisu).

```bash
uv run python scripts/load_laws.py            # 1. scrape + parse + DB
uv run python scripts/generate_metadata.py    # 2. LLM popisy + metadata
uv run python scripts/generate_embeddings.py  # 3. vektorové embeddingy
```

Všechny tři skripty jsou **inkrementální** — bezpečné opakované spuštění.

### 11.1 `scripts/load_laws.py`

Cíl: scrape + parse text zákonů a uložit do `laws.db`.

Vstupem je ručně kurátorovaný registr **61 zákonů** (`mcp/registry.py`), rozdělených na typy `TZ`, `prestupkovy` a `specialni`.

Průchod pipeline:

```text
Registry (61 zákonů)
        │
        ▼
  LawScraper.fetch()
  ├── build_url("40/2009") → https://www.zakonyprolidi.cz/cs/2009-40
  ├── httpx GET (timeout 30s, delay 1.5s mezi requesty)
  └── → raw HTML
        │
        ▼
  LawParser.parse()
  ├── BeautifulSoup hledá <div class="Frags">
  ├── Stavový automat prochází ploché <p>/<h3> elementy:
  │     CAST → HLAVA → DIL → PARA → tělo textu
  ├── Zrušené paragrafy (CSS třída SIL) se přeskakují
  └── → ParsedLaw (hierarchie: Část → Hlava → Díl → Paragraf)
        │
        ▼
  LawIndexer.index_from_html()
  ├── SHA-256 hash obsahu paragrafů (ne HTML!)
  │     hash vstup: cislo + "\x00" + nazev + "\x00" + plne_zneni + "\x01"
  ├── Porovnání s content_hash v DB
  │     shoduje se → SKIP
  │     liší se    → kaskádové smazání → re-insert
  └── Upsert: law → chapters → paragraphs
```

### 11.2 `scripts/generate_metadata.py`

Cíl: doplnit LLM-generovaná metadata do DB.

Generuje dva typy dat:

| Entita | Model | Výstup |
|--------|-------|--------|
| Hlava (chapter) | `ChapterDescription` | `popis`: 2-3 věty popisující obsah hlavy |
| Paragraf | `ParagraphMetadata` | `znaky_skutkove_podstaty`, `kvalifikovane_podstaty`, `forma_zavineni`, `priprava_trestna`, `trestni_sazba` |

- **Inkrementální**: přeskakuje chapters/paragraphs, které už mají `popis`/`metadata`.
- Používá Azure OpenAI (GPT-5.2) se structured output (Pydantic modely).

### 11.3 `scripts/generate_embeddings.py`

Cíl: vytvořit embeddingy pro laws/chapters/paragraphs a uložit do `vec_*` tabulek.

```text
                    Azure OpenAI
                    text-embedding-3-large
                    dimensions: 1536
                    batch size: 100
                    max tokens: 8192
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
     vec_laws       vec_chapters   vec_paragraphs
     text:          text:          text:
     popis nebo     popis (z       "§ {cislo}
     "{nazev}.      kroku 2)       {nazev} -
      Oblasti:      nebo fallback   {plne_zneni}"
      {oblasti}"
```

- **Inkrementální**: přeskakuje entity, které už mají embedding v `vec_*` tabulkách.
- Tokenizace: `cl100k_base` (tiktoken), budget 8 128 tokenů (8 192 − 64 safety margin).
- Příliš dlouhé texty paragrafů se oříznou na 20 000 znaků před tokenizací.
- Požadavky: nastavený Azure embedding deployment.

## 13) Testování a kvalita

- Linter/formatter:

```bash
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
```

- Testy:

```bash
uv run pytest -v
```

Testy typicky mockují externí závislosti (HTTP scrape, Azure OpenAI) a ověřují:
- parser (zakonyprolidi HTML → struktura)
- DB schema + vec search integraci
- MCP tools
- agent pipeline routing
- web endpoints + SSE tok

## 14) Provozní poznámky / limity

- `laws.db` používá WAL; v případě běhu více procesů je potřeba myslet na file-locking v SQLite.
- `sqlite-vec` vyžaduje nativní rozšíření; při problémech ověřte, že se `sqlite_vec.load(conn)` podaří.
- SSE stream má timeout 120s (s keepalive `ping`).
- Aktivita agentů se do SSE posílá bez `data` payloadu; detailní strukturovaná data jsou jen v DB logu (pokud je DB logger registrován).
