from agno.agent import Agent, RunOutput
import requests
import json
import os
import secrets
import logging
from typing import Optional
from agno.models.ollama import Ollama

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("heritage_agent")

api_key = "4f0f3c205b36918e044f2bb0f205ba3dd765c1ca"  # updated per user request
ollama_model = Ollama(
    id="qwen2.5:32b",
    options={
        "temperature": 0.7,
        "top_p": 0.9,
        "num_predict": 8192,
        "num_ctx": 16384,
    }
)

# writer_model uses the same capable model
writer_model = ollama_model
# use the supplied API key for authentication in the required format
# the API expects 'Authorization: Token <api_key>' (not Bearer)
headers = {"Authorization": f"Token {api_key}"}


def _summarize(tool_payload):
    """Return a tiny summary of the tool payload showing at most three items per category.

    This helper is used for debug logging and to send minimal data back to the UI.  The
    payload may be a raw string or a dict containing a ``results`` key.
    """
    # keep only the first three items from each result category
    if not isinstance(tool_payload, dict):
        return tool_payload
    results = tool_payload.get('results', {}) if 'results' in tool_payload else tool_payload
    summary = {}
    for name, data in results.items():
        if isinstance(data, dict):
            if name == 'chunks':
                summary[name] = data.get('data', [])[:3]
            elif name == 'verses':
                if isinstance(data, list):
                    summary[name] = data[:3]
                else:
                    summary[name] = data.get('data', [])[:3] if isinstance(data.get('data'), list) else data
            elif name == 'definition':
                defs = data.get('details', {}).get('definitions', []) if isinstance(data, dict) else []
                summary[name] = defs[:3]
            else:
                summary[name] = data
        elif isinstance(data, list):
            summary[name] = data[:3]
        else:
            summary[name] = data
    return summary

def heritage_lookup(verse_part: Optional[str] = None, dict_word: Optional[str] = None, chunk_query: Optional[str] = None) -> str:
    """
    Use this tool to perform the following queries based on input:
    - Search for verses containing the specified `verse_part`. It returns the top matching verses along with comprehensive details, including meanings, translations, composer names, and additional relevant information.
    - Retrieve a concise summary, meanings, definitions and additional information for specified name, word, place or concept from multiple sources [parameter: `dict_word`]. This also returns words similar to the input. If an exact match isn't found, it provides only the similar words without detailed definitions.
    - Retrieve relevant text chunks related to Indian heritage based on the provided query (`chunk_query`). This fetches and returns a list of the most relevant text chunks from the database by identifying maximum similarity with the input query.

    Args:
        verse_part (str): Short phrase or fragment (2-3 words) to search Sanskrit verses.
        dict_word (str): A single word of name, word, place or concept to retrieve definitions and related info.
        chunk_query (str): A heritage-related query to fetch relevant text chunks.

    Returns:
        str: A JSON-formatted string containing results based on the input provided. If multiple fields are provided, all respective results are included.
    """
    results = {}

    if chunk_query:
        logger.info("[CHUNK API] query=%r", chunk_query)
        try:
            response = requests.get(
                "https://project.iith.ac.in/bheri/chunk/multivec/",
                headers=headers,
                params={"inp_str": chunk_query},
                timeout=30,
            )
            response.raise_for_status()
            res = response.json()
            count = len(res.get('data', []))
            logger.info("[CHUNK API] ✓ success — %d chunks returned", count)
            logger.debug("[CHUNK API] response payload: %s", res)
            results['chunks'] = res
        except Exception as e:
            logger.error("[CHUNK API] ✗ failed — %s", e)
            results['chunks'] = {"error": str(e)}

    if dict_word:
        logger.info("[DICT API] word=%r", dict_word)
        try:
            response = requests.get(
                "https://project.iith.ac.in/bheri/dict/v1_5/get_defs/",
                headers=headers,
                params={"word": dict_word},
                timeout=30,
            )
            response.raise_for_status()
            res = response.json()
            logger.debug("[DICT API] response payload: %s", res)
            if res.get('found_match'):
                def_count = len(res['details'].get('definitions', []))
                logger.info("[DICT API] ✓ exact match — %d definition(s) found", def_count)
                for i in range(def_count):
                    res['details']['definitions'][i] = {
                        'text': res['details']['definitions'][i]['text'],
                        'source': res['details']['definitions'][i]['src_short_title'],
                        'source_url': res['details']['definitions'][i]['source_url'],
                    }
            else:
                similar = res.get('similar_words', [])
                throttled = 'detail' in res and 'throttled' in res.get('detail', '')
                if throttled:
                    logger.warning("[DICT API] ✗ rate-limited — %s", res.get('detail'))
                else:
                    logger.info("[DICT API] ✓ no exact match — %d similar word(s): %s",
                                len(similar), similar[:5])
            results['definition'] = res
        except Exception as e:
            logger.error("[DICT API] ✗ failed — %s", e)
            results['definition'] = {"error": str(e)}

    if verse_part:
        logger.info("[VERSE API] phrase=%r", verse_part)
        try:
            response = requests.get(
                "https://project.iith.ac.in/bheri/verse/v1/find/",
                headers=headers,
                params={"input_string": verse_part},
                timeout=30,
            )
            response.raise_for_status()
            # Handle potential NDJSON (multiple JSON objects) by reading only first object
            text = response.text.strip()
            try:
                res = json.loads(text)
            except json.JSONDecodeError:
                res = json.loads(text.split('\n')[0])
            logger.debug("[VERSE API] response payload: %s", res)
            count = len(res) if isinstance(res, list) else (len(res.get('data', [])) if isinstance(res, dict) else '?')
            logger.info("[VERSE API] ✓ success — %s verse(s) returned", count)
            results['verses'] = res
        except Exception as e:
            logger.error("[VERSE API] ✗ failed — %s", e)
            results['verses'] = {"error": str(e)}

    # Summary: which sources will feed the wiki generation
    active_sources = [k for k, v in results.items() if isinstance(v, dict) and 'error' not in v or isinstance(v, list)]
    logger.info("[TOOL RESULT] sources available for wiki generation: %s", active_sources)

    return json.dumps({"results": results}, ensure_ascii=False)


# ── Stage 1: tool-caller agent ──────────────────────────────────────────────
_tool_agent = Agent(
    name="Data Fetcher",
    model=ollama_model,
    tools=[heritage_lookup],
    instructions=[
        "Call heritage_lookup with ALL THREE parameters: "
        "dict_word=<the topic>, "
        "chunk_query=<a detailed English question about the topic's history and significance>, "
        "verse_part=<the topic word in IAST transliteration>. "
        "Return the raw tool result without any commentary."
    ],
    markdown=False,
)


def _build_article_prompt(topic: str, tool_data: str) -> str:
    """Build an explicit article-writing prompt with data inlined."""
    try:
        data = json.loads(tool_data) if isinstance(tool_data, str) else tool_data
    except Exception:
        data = {}
    # `data` may be a dict or a list (e.g. when the tool-caller returned
    # its own response content).  Ensure we always treat `results` as a
    # dictionary-like container.  If it's a list, wrap it so later code
    # can iterate over it without blowing up.  (The original code
    # assumed `data` had a `.get` method, which fails for lists.)
    if isinstance(data, list):
        results = {"list_results": data}
    else:
        results = data.get("results", data)

    # decide if only dictionary definitions are available
    dict_defs = []
    defn = results.get("definition", {})
    if isinstance(defn, dict) and defn.get("found_match"):
        dict_defs = defn.get("details", {}).get("definitions", [])
    chunks_data = results.get("chunks", {})
    chunks = chunks_data.get("data", []) if isinstance(chunks_data, dict) else []
    dict_only = bool(dict_defs) and not bool(chunks)

    if dict_only:
        header = [
            f"Explain the meaning of **{topic}** using only the dictionary definitions below.",
            "Do not attempt to produce a long Wikipedia-style article – a brief explanation or paragraph paraphrasing the definitions is sufficient.",
            "Do not fabricate any additional content beyond what the definitions provide.",
            "",
            "=== SOURCE DATA ===",
            "",
        ]
    else:
        header = [
            f"Write a comprehensive Wikipedia-style encyclopedia article about **{topic}** in Indian heritage.",
            ("The article must be based solely on the source data provided below. "
             "Do not invent any facts or narrative that cannot be traced to the definitions, chunks, "
             "or verses supplied. If the data is sparse, acknowledge the limitation rather than "
             "hallucinating unrelated material."),
            "",
            "HARD REQUIREMENTS — you MUST follow all of these:",
            "1. Write ONLY in English prose. No bullet points, no numbered lists anywhere in the article body.",
            "2. Article MUST be at least 2000 words. Do NOT stop early.",
            "3. Start with an untitled opening paragraph of 200+ words introducing the topic.",
            "4. Write exactly 10 or more ## section headings. Choose meaningful titles based on the source data.",
            "5. Under EVERY ## section, write at least 3 full paragraphs (5-7 sentences each). Never write only one paragraph per section.",
            "6. You MUST cite sources **for every factual statement** you make. Use bracketed reference identifiers like [ref1], [ref2], etc. Assign ref numbers sequentially in the order you refer to the material below.  If you describe something that comes from a particular definition, chunk, or verse, append the appropriate ref id immediately after the sentence.",
            "7. The final article MUST contain a ## Sources and References section at the very end.  It should list every ref id with a human‑readable source name, one per line.  Example:",
            "   ref1: Puranic Encyclopaedia",
            "   ref2: Arthashastra",
            "   ...",
            "   if you fail to include this section, the system will append it automatically after generation.",
            "8. The article’s body MUST include at least one reference token such as [ref1].  In fact, the first paragraph should contain [ref1].  If you cannot show a normal citation, simply append `[ref1]` at the end of the opening paragraph.  The system will also enforce this after generation if necessary.",
            "9. Use ALL definitions and passages provided below — do not skip any.",
            "9. - Use *Markdown* for formatting.",
            "- Summarize in simple language, then add supporting detail from tool outputs.",
            "- Every factual statement must have a source block right after it.",

            "=== SOURCE DATA ===",
            "",
        ]

    body = []
    # Build a simple reference map that the writer can reuse when citing.
    # We will also return this map later to append a sources section if missing.
    ref_map = []

    # Definitions
    defn = results.get("definition", {})
    if isinstance(defn, dict) and defn.get("found_match"):
        defs = defn.get("details", {}).get("definitions", [])
        body.append(f"DEFINITIONS FROM {len(defs)} SOURCES (use each one in the article):")
        for i, d in enumerate(defs, 1):
            src = d.get("source", "Unknown source")
            text = d.get("text", "")
            body.append(f"  SOURCE {i} — {src}:")
            body.append(f"  {text}")
            body.append("")
            ref_map.append((f"ref{len(ref_map)+1}", src))

    # Chunks
    chunks_data = results.get("chunks", {})
    if isinstance(chunks_data, dict) and "data" in chunks_data:
        chunks = chunks_data["data"]
        body.append(f"HERITAGE PASSAGES (use all {len(chunks)} in the article):")
        for i, c in enumerate(chunks, 1):
            src_title = c.get("source_title", "")
            ref = c.get("reference", "")
            text = c.get("text", "")
            body.append(f"  PASSAGE {i} — {src_title} ({ref}):")
            body.append(f"  {text}")
            body.append("")
            ref_map.append((f"ref{len(ref_map)+1}", src_title or ref or "Chunk"))

    # Verses
    verses_data = results.get("verses", {})
    verse_list = []
    if isinstance(verses_data, list):
        verse_list = verses_data
    elif isinstance(verses_data, dict):
        verse_list = verses_data.get("data", [])
    if verse_list:
        body.append(f"VERSES ({len(verse_list)} total):")
        for i, v in enumerate(verse_list[:5], 1):
            body.append(f"  VERSE {i}: {str(v)[:300]}")
            ref_map.append((f"ref{len(ref_map)+1}", v.get('reference','Verse'))) if isinstance(v, dict) else ref_map.append((f"ref{len(ref_map)+1}", 'Verse'))
        body.append("")

    # insert reference map section for model clarity
    if ref_map:
        body.append("REFERENCE_MAP:")
        for rid, name in ref_map:
            body.append(f"{rid}: {name}")
        body.append("")
    footer = [
        "=== END OF SOURCE DATA ===",
        "",
        "NOW BEGIN WRITING the article. Start with the opening paragraph immediately.",
        "Remember: minimum 2000 words, 10+ sections, 3+ paragraphs per section, English only.",
        "Keep writing until all sections are fully developed. Do not stop after a few paragraphs.",
    ]

    # attach ref_map to prompt by serialising it also in a comment section
    prompt_text = "\n".join(header + body + footer)
    return prompt_text


import re

def _parse_inline_refs(text: str) -> dict:
    """Extract {int: source_name} from the References section embedded in a definition text.

    Handles two formats:
      Format A (number in middle): 'Mahabharata, 7.35, [5], translated by Kisari Mohan Ganguli'
      Format B (number at start):  '[1] abhimanyu, Conc. Encyl. Hinduism, Swami Harshananda'
    """
    refs = {}
    idx = text.find('\nReferences:\n')
    if idx == -1:
        idx = text.rfind('\nReferences:')
    if idx == -1:
        return refs
    block = text[idx:]
    for line in block.splitlines()[1:]:  # skip the 'References:' header line itself
        line = line.strip()
        if not line or line.startswith('[https://') or line.startswith('http'):
            continue
        # Format B: "[N] source text"
        m = re.match(r'^\[(\d+)\]\s+(.+)$', line)
        if m:
            refs[int(m.group(1))] = m.group(2).strip()
            continue
        # Format A: "source prefix, [N], source suffix"
        m = re.match(r'^(.+?),\s*\[(\d+)\],\s*(.+)$', line)
        if m:
            refs[int(m.group(2))] = f"{m.group(1).strip()}, {m.group(3).strip()}"
            continue
    return refs


def _build_flexible_prompt(topic: str, tool_data: str) -> str:
    """Build a prompt for the flexible writer agent.

    This version is much more lenient than the strict Wikipedia-style prompt and
    is intended to produce output proportional to the amount of context returned
    by the heritage_lookup tool.  If only dictionary definitions are present, the
    prompt becomes very simple: no sections, just a brief paraphrase of those
    definitions.  Chapters and headings are only suggested when multiple chunks
    of passage data exist.
    """
    try:
        data = json.loads(tool_data) if isinstance(tool_data, str) else tool_data
    except Exception:
        data = {}
    results = data.get("results", data) if isinstance(data, dict) else data

    # Use ONLY the dictionary/definition API response — chunks and verses are ignored.
    defs = []
    defn = results.get("definition", {})
    if isinstance(defn, dict) and defn.get("found_match"):
        defs = defn.get("details", {}).get("definitions", [])

    if defs:
        header = [
            f"""Write an encyclopedia-style article about **{topic}** using ONLY the information below.

DO NOT invent any new facts, characters, events, or narrative beyond what is present in the supplied text. If the source material is brief, your output should be correspondingly brief (do not pad for length).

Use fluent English prose and Markdown formatting for any headings you choose to include.
Preferably use Indic categories like Shruti, smriti, purana, itihasa, kavya etc instead of mythology, sacred texts or others.
Do not use the term "Hinduism" and instead use the term "Indic knowledge traditions".

## Completeness (critical)
- Include ALL content from the source texts — every named person, warrior, event, quote, and detail.
- Do NOT summarise lists; if the source gives 20 warriors killed, list all 20.
- Do NOT omit direct quotes; if a speaker's exact words are given, reproduce them fully.
- Do NOT collapse step-by-step sequences; reproduce every step in the order given.
- If the source material is long and rich, your article must be correspondingly long and complete.

## Reference handling
- The source texts below have already had their inline [N] citations substituted with the correct final reference numbers matching the REFERENCE_MAP.
- Copy those [N] numbers through exactly as they appear — do NOT change, remove, or renumber them.
- Every factual sentence must carry its citation(s) inline, e.g. "…fought valiantly [3][5]."
- Do NOT cite a number that does not appear in the REFERENCE_MAP.
- Do NOT leave a REFERENCE_MAP entry uncited if the fact it supports appears in your article.

## Sources and References section
- Add a ## Sources and References section at the very end.
- List every reference number that you cited inline, with its exact name from the REFERENCE_MAP.
- Format: [N]: source name
- No URLs.

=== SOURCE DATA ===""",
            "",
        ]

    else:
        header = [
            f"No dictionary definitions were found for **{topic}**.",
            "State that the information is limited and no article could be generated.",
        ]

    body = []
    # global ordered unique references keyed by normalised name
    # value: (sequential_number, display_name, url)
    global_refs = {}

    def _add_ref(name: str, url: str = "") -> str:
        """Add ref to global map and return its assigned number."""
        norm = re.sub(r'\s+', ' ', name.strip().lower())
        if norm not in global_refs:
            n = len(global_refs) + 1
            global_refs[norm] = (n, name.strip(), url)
        return str(global_refs[norm][0])

    def _substitute_refs(text: str, inline_map: dict, src_url: str) -> str:
        """Replace every [N] in text body with the correct REFERENCE_MAP number.

        inline_map: {orig_int -> source_name} from _parse_inline_refs().
        The embedded 'References:' tail is also stripped so the LLM doesn't
        see the old numbering at all.
        """
        # Strip the embedded References block
        for marker in ('\nReferences:\n', '\nReferences:'):
            idx = text.find(marker)
            if idx != -1:
                text = text[:idx]
                break

        def replace_bracket(m):
            orig = int(m.group(1))
            ref_name = inline_map.get(orig)
            if ref_name:
                new_num = _add_ref(ref_name, src_url)
                return f"[{new_num}]"
            return m.group(0)  # leave unchanged if not found

        return re.sub(r'\[(\d+)\]', replace_bracket, text)

    if defs:
        body.append(f"DEFINITIONS FROM {len(defs)} SOURCES:")
        for i, d in enumerate(defs, 1):
            src = d.get("source", "Unknown source")
            src_url = d.get("source_url", "")
            text = d.get("text", "")
            # Always register the top-level source first so it gets [1], [2]… slots
            _add_ref(src, src_url)
            # Parse embedded References section to get orig_num -> source_name map
            inline_map = _parse_inline_refs(text)
            # Pre-register all sources from this definition's reference list
            for ref_name in inline_map.values():
                _add_ref(ref_name, src_url)
            # Substitute inline [N] numbers with correct final numbers, strip old References block
            clean_text = _substitute_refs(text, inline_map, src_url)
            body.append(f"  SOURCE {i} — {src}:")
            body.append(f"  {clean_text}")
            body.append("")

    if global_refs:
        ref_map = sorted(global_refs.values(), key=lambda x: x[0])  # sort by assigned number
        body.append("REFERENCE_MAP:")
        body.append("The inline citation numbers in the source texts above have already been")
        body.append("substituted to match this map. Copy them through as-is — do NOT renumber.")
        for num, name, _url in ref_map:
            body.append(f"  [{num}]: {name}")
        body.append("")

    footer = [
        "=== END OF SOURCE DATA ===",
        "",
        "IMPORTANT: The inline [N] citations in the source texts above already use the correct",
        "final reference numbers from the REFERENCE_MAP. Do NOT change them.",
        "Include ALL content from the source texts — do not skip quotes, lists, or sequences.",
        "For every named warrior, event, quote, or detail in the source, include it in the article.",
    ]

    # Build a plain {num: name} dict for the post-processor
    final_ref_map = {num: name for (num, name, _url) in global_refs.values()}

    return "\n".join(header + body + footer), final_ref_map


def _fix_citations(article: str, ref_map: dict) -> str:
    """Post-process the LLM article to guarantee citation correctness.

    Strategy:
    1. Strip the LLM's entire ## Sources and References section.
    2. Scan the article body for every [N] token.
    3. Drop any [N] where N is not a key in ref_map (invalid citation).
    4. Collect the set of valid N values actually used.
    5. Append a clean ## Sources and References section built from ref_map,
       listing only the entries that are cited in the body.

    This means the Sources section is always generated by Python and is
    always 100% consistent with the inline citations.
    """
    if not ref_map:
        return article

    # 1. Strip the LLM's Sources section
    for marker in ("\n## Sources and References", "\n## Sources & References",
                   "\n## References", "\n## Sources"):
        idx = article.find(marker)
        if idx != -1:
            article = article[:idx]
            break

    # 2. Remove any [N] that is NOT in ref_map
    def _clean_ref(m):
        n = int(m.group(1))
        return m.group(0) if n in ref_map else ""
    article = re.sub(r'\[(\d+)\]', _clean_ref, article)

    # 3. Collect all valid [N] actually used.
    used = sorted({int(m.group(1)) for m in re.finditer(r'\[(\d+)\]', article)})

    # 4. Rebuild Sources section from Python
    if used:
        sources_block = "\n\n## Sources and References\n"
        for n in used:
            sources_block += f"[{n}]: {ref_map[n]}\n"
        article = article.rstrip() + sources_block

    return article


# ── Stage 2: writer agents (no tools) ─────────────────────────────────────────
# original writer with strict requirements
_WRITER_SYSTEM = (
    "You are a senior Wikipedia editor and Indology scholar writing long-form encyclopedia articles. "
    "When given source data and a writing task, you produce a VERY LONG article of 2000+ words. "
    "You write only in flowing English prose — no bullet points, no numbered lists. "
    "You use ## for section headings only. "
    "You elaborate extensively on every point, never summarizing briefly. "
    "You must include at least 10 ## sections, each with at least 3 full paragraphs. "
    "Do not invent any additional facts or make up content not supported by the supplied source data. ",
    ("If the available definitions and passages are sparse, acknowledge the limitation "
     "instead of filling space with unrelated narrative.")
)

_writer_agent = Agent(
    name="Article Writer",
    model=writer_model,
    system_message=_WRITER_SYSTEM,
    markdown=True,
)

# new flexible writer that adapts length to supplied context
_FLEXIBLE_SYSTEM = (
    "You are an encyclopedia writer. When given source data, produce a coherent article in English prose. "
    "Do not enforce any fixed word count, section count, or paragraph rules. "
    "Let the length of the article be roughly proportional to the amount of data provided. "
    "Use Markdown for headings where appropriate, but do not invent arbitrary structure. "
    "Only use the provided definitions and heritage passages; ignore verse data altogether. ",
    ("Critically: do not fabricate or hallucinate information. If the supplied material is minimal, "
     "acknowledge that there is limited information and refrain from padding the text with "
     "irrelevant or nonsensical passages.")
)

_flexible_writer_agent = Agent(
    name="Flexible Writer",
    model=writer_model,
    system_message=_FLEXIBLE_SYSTEM,
    markdown=True,
)


def _extract_sources_from_tool_data(tool_data):
    """Return a list of human readable sources extracted from the tool data.

    The writer agent may sometimes omit a sources section; we can regenerate it
    from the underlying JSON and append it automatically.
    """
    try:
        data = json.loads(tool_data) if isinstance(tool_data, str) else tool_data
    except Exception:
        return []
    results = data.get("results", data) if isinstance(data, dict) else {}
    sources = []
    # definitions
    defn = results.get("definition", {})
    if isinstance(defn, dict) and defn.get("found_match"):
        for d in defn.get("details", {}).get("definitions", []):
            sources.append(d.get("source", "Unknown"))
    # chunks
    chunks = results.get("chunks", {}).get("data", []) if isinstance(results.get("chunks"), dict) else []
    for c in chunks:
        sources.append(c.get("source_title") or c.get("reference") or "Chunk")
    # verses
    verses = results.get("verses", [])
    if isinstance(verses, dict):
        verses = verses.get("data", [])
    for v in verses:
        if isinstance(v, dict):
            sources.append(v.get("reference", "Verse"))
    return sources


def chatbot(query, user_id, session_id):
    if not session_id:
        session_id = secrets.token_urlsafe(16)
        yield json.dumps({'content': session_id, 'event': 'SessionID'}) + "\n"

    logger.info("[QUERY] user=%s session=%s query=%r", user_id, session_id, query)
    logger.info("[MODEL] tool-caller=qwen2.5:32b writer=qwen2.5:32b (two-stage)")

    # ── Stage 1: fetch data via tool ─────────────────────────────────────────
    tool_run = _tool_agent.run(
    f"""
Call the heritage_lookup tool.

Parameters:
dict_word = "{query}"
chunk_query = "Explain the history, cultural significance, and references of {query} in Indian heritage texts."
verse_part = "{query}"

Return ONLY the tool result.
""",
)

    # Extract raw tool result from the tool agent's message history
    tool_data_str = None
    if tool_run and tool_run.messages:
        for msg in reversed(tool_run.messages):
            role = getattr(msg, 'role', None)
            if role == 'tool':
                content = getattr(msg, 'content', None)
                if content:
                    tool_data_str = str(content)
                    break

    if not tool_data_str:
        # Fallback: use the agent's final response as context
        tool_data_str = tool_run.content if tool_run else "{}"
        logger.warning("[STAGE 1] no tool message found, using agent response as context")
    else:
        logger.info("[STAGE 1] tool data extracted (%d chars)", len(tool_data_str))


    try:
        parsed_tool = json.loads(tool_data_str)
    except Exception:
        parsed_tool = tool_data_str
    brief = _summarize(parsed_tool)
    # log only the brief summary rather than the entire payload
    logger.info("[STAGE 1] API response summary: %r", brief)
    # emit a tool_response event so Streamlit UI can show the brief data
    yield json.dumps({'content': json.dumps({'debug_api': brief, 'results': parsed_tool.get('results') if isinstance(parsed_tool, dict) else None}), 'event': 'tool_response'}) + "\n"

    # Signal tool parameters to UI
    yield json.dumps({'content': f"Data fetched for: {query}", 'event': 'ToolParameters'}) + "\n"

    # ── Stage 2: write the article ────────────────────────────────────────────
    logger.info("[STAGE 2] writing encyclopedia article")
    article_prompt = _build_article_prompt(query, tool_data_str)
    logger.info("[STAGE 2] article prompt built (%d chars)", len(article_prompt))

    run_output: RunOutput = _writer_agent.run(
        article_prompt,
        stream=False,
        user_id=user_id,
        session_id=session_id + "_writer",
    )

    if run_output and isinstance(run_output.content, str):
        content = run_output.content
        # make sure at least one ref token appears in the body
        body_text = content.split("## Sources and References")[0]
        if "ref1" not in body_text:
            # insert into first paragraph if possible
            parts = body_text.split("\n\n")
            if parts:
                parts[0] = parts[0].rstrip() + " [ref1]"
                body_text = "\n\n".join(parts)
            content = body_text + content[len(body_text):]
        # ensure there is a sources section at the end
        if "## Sources and References" not in content:
            sources = _extract_sources_from_tool_data(tool_data_str)
            if sources:
                content += "\n\n## Sources and References\n"
                for idx, src in enumerate(sources, 1):
                    content += f"ref{idx}: {src}\n"
        yield json.dumps({'content': content, 'event': 'RunContent'}) + "\n"

    logger.info("[STAGE 2] article generation complete")


def chatbot_flexible(query, user_id, session_id):
    """Flexible two-stage chatbot that uses only the dictionary API.

    The fetch (stage 1) portion is identical; only stage 2 uses
    `_flexible_writer_agent` with a relaxed prompt that ignores verses and
    has no length restrictions.  The streaming protocol and event handling
    remain the same so the caller may treat both agents interchangeably.
    """
    # initial session id handling mirrors chatbot()
    if not session_id:
        session_id = secrets.token_urlsafe(16)
        yield json.dumps({'content': session_id, 'event': 'SessionID'}) + "\n"

    logger.info("[QUERY] user=%s session=%s query=%r", user_id, session_id, query)
    logger.info("[MODEL] tool-caller=qwen2.5:32b flexible-writer (two-stage)")

    # Stage 1: fetch only dictionary information (skip chunks/verses)
    logger.info("[STAGE 1] invoking heritage_lookup (%s) with dict only", query)
    try:
        tool_data_str = heritage_lookup(dict_word=query)
        logger.info("[STAGE 1] heritage_lookup returned %d chars", len(tool_data_str))
    except Exception as e:
        logger.error("[STAGE 1] heritage_lookup failed: %s", e)
        tool_data_str = "{}"

    # Summary event for UI

    try:
        parsed_tool = json.loads(tool_data_str)
    except Exception:
        parsed_tool = tool_data_str
    brief = _summarize(parsed_tool)
    logger.info("[STAGE 1] API response summary: %r", brief)
    yield json.dumps({'content': json.dumps({'debug_api': brief, 'results': parsed_tool.get('results') if isinstance(parsed_tool, dict) else None}), 'event': 'tool_response'}) + "\n"
    yield json.dumps({'content': f"Data fetched for: {query}", 'event': 'ToolParameters'}) + "\n"

    # Stage 2: use flexible writer
    logger.info("[STAGE 2] writing flexible article")
    article_prompt, ref_map = _build_flexible_prompt(query, tool_data_str)
    logger.info("[STAGE 2] flexible prompt built (%d chars, %d refs)", len(article_prompt), len(ref_map))

    run_output: RunOutput = _flexible_writer_agent.run(
        article_prompt,
        stream=False,
        user_id=user_id,
        session_id=session_id + "_flexible",
    )

    if run_output and isinstance(run_output.content, str):
        content = _fix_citations(run_output.content, ref_map)
        yield json.dumps({'content': content, 'event': 'RunContent'}) + "\n"

    logger.info("[STAGE 2] flexible article generation complete")


if __name__ == "__main__":
    query = "Srirama"
    user_id = "test_user"
    session_id = None
    full = ""
    for response in chatbot(query, user_id, session_id):
        data = json.loads(response)
        ev = data.get('event', '')
        c = data.get('content', '')
        if ev == 'RunContent' and isinstance(c, str):
            full += c
    print(full)
    print(f"\n--- Words: {len(full.split())} | Sections: {full.count(chr(10)+'## ')} ---")