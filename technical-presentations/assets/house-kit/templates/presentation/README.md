The included Russian-language technical example demonstrates the schema only. Replace its subject, audience, language, sources, narrative and script for the requested technical topic. The number and order of slides are not prescribed.

# Шаблон новой презентации

`deck.yaml` содержит **пример на семь слайдов**, а не обязательный план.
Замените тему, аудиторию, тезис, аргумент, источники и речь. Число слайдов
определяется длиной списка `slides`; номера пересчитываются при сборке.

Из корня инструментов:

```sh
uv run --extra presentation python tools/presentation.py build <папка>/deck.yaml
uv run --extra presentation python tools/presentation.py check <папка>/deck.yaml
```

Результаты: `dist/slides.pptx`, `dist/slides.pdf`, `dist/speaker-script.pdf`.
Миниатюры для просмотра и отчёт проверки: `qa/`.
Стиль наследуется из корневого `guideline.yaml` и не копируется в тему.
Сведения о макетах, изображениях и видео — в корневом `PRESENTATION_GUIDE.md`.
