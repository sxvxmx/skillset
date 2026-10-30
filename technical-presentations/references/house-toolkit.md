# House toolkit

The bundled `assets/house-kit/` is a snapshot of the original workspace's shared tools, template, Russian-language detailed guide, and `guideline.yaml`. It is the default authoring toolkit for this skill; its example is not a universal technical presentation standard. Adapt the shared style to the assignment when needed. Preserve this single shared style and tool set when creating topics; do not copy it into each topic. Use a writable project copy if adapting the toolkit; do not overwrite a user's existing files. The source snapshot can diverge from the original workspace.

The toolkit requires Python 3.11+, `uv`, dependencies in `pyproject.toml`/`uv.lock`, and appropriate font files. It uses Arial and Courier New when the default macOS font files are available; otherwise the bundled Liberation Sans and Liberation Mono fonts provide a redistributable fallback. Set `DECK_FONT_DIR` to use the expected Arial and Courier New filenames explicitly. The fallback has its own family name, so a third-party editor may need those fonts installed for matching rendering. Other formats or video may have extra dependencies described in the guide. Inspect and adapt the template's example subject, language and slide structure rather than presenting it as the requested content.

From the toolkit root, create a new topic (a path outside the skill folder is fine), then edit its `deck.yaml` and add assets:

```sh
uv run --extra presentation python tools/presentation.py init /path/to/new-topic
uv run --extra presentation python tools/presentation.py build /path/to/new-topic/deck.yaml
uv run --extra presentation python tools/presentation.py check /path/to/new-topic/deck.yaml
uv run python tools/deckcheck.py /path/to/new-topic/dist/slides.pptx --strict
uv run python tools/deckcheck.py /path/to/new-topic/dist/slides.pdf --strict
uv run python tools/selftest.py
uv run --extra presentation --extra report python -m unittest discover -s tools -p 'test_*.py'
```

The default outputs are PPTX, static PDF and separate speaker-script PDF, with no embedded notes. Zero errors and warnings are required by this toolkit; a crashed check is an error. Inspect all slide and script pages and test the requested player separately. If the user requests a different style, notes or outputs, honor that request by adapting the toolkit or supplementing it with suitable tooling. The script labels support English and Russian: set brief.language to an English or Russian language name or code. The optional video HTML player currently has Russian interface labels and needs adaptation for other languages. For other script languages, adapt the labels and verify font coverage and text shaping before delivery; the current generator does not promise full support for all writing systems. See the bundled `PRESENTATION_GUIDE.md` for schemas, player and media details, and checks. Do not weaken checks to make a deck pass.
