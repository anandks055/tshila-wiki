# Wiki Chatbot

A conversational AI that generates comprehensive Wikipedia-style encyclopedia articles about topics from Indian heritage, drawing from Sanskrit dictionaries, Puranic texts, and heritage passage databases.

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) running locally with `qwen2.5:32b` pulled:
  ```
  ollama pull qwen2.5:32b
  ```

## Installation

```bash
pip install -r requirements.txt
```

## Running

```bash
streamlit run agent_ollama.py
```

The app will be available at `http://localhost:8501`.

## How it works

1. Enter any topic from Indian heritage (e.g. *Srirama*, *Yuddha*, *Dharma*)
2. The agent queries three APIs from the Bheri heritage database:
   - **Dict API** — word definitions from Sanskrit lexicons
   - **Chunk API** — relevant passages from heritage texts
   - **Verse API** — matching Sanskrit verses
3. All retrieved data is synthesised into a 1500–2000 word encyclopedia article with section headings, inline citations, and a references list

## Configuration

API authentication and model settings are configured directly in `agent.py`:

| Setting | Description |
|---|---|
| `jwt_token` | Bearer token for the Bheri API |
| `ollama_model` | Ollama model used (default: `qwen2.5:32b`) |
| `num_predict` | Max tokens to generate (default: `8192`) |
| `num_ctx` | Context window size (default: `16384`) |

## Batch Page Generation

Two helper scripts are provided for creating static markdown pages from a
list of topics:

* `generate_static_pages.py` – the original sequential generator (topics are
  processed one at a time). It always reads `yoga_ayurveda_pages.txt` and
  appends ` - done` to each entry as it completes.
* `generate_static_pages_batch.py` – a newer, parallelised version that can
  work on any list file. It accepts the following options (all optional):

```sh
python generate_static_pages_batch.py \ 
    --list path/to/list.txt \      # default: yoga_ayurveda_pages.txt or list_of_pages_new.txt
    --workers 5                    # number of concurrent topics
    --pause 1.0                    # seconds to sleep after each completion
    --limit 20                     # only process first 20 pending topics
```

The `--limit` flag is handy for quickly ticking off a few entries while you
verify the behaviour; leave it off to run the entire list.

The batch script is fully backwards‑compatible and does not modify the
sequential generator, so you can safely experiment with it without affecting
the existing workflow.

