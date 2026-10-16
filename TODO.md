# TODO — cose da correggere prossimamente

## 1. TOC: le voci dei sottolivelli non vengono tradotte nel file di output

**Sintomo.** Traducendo un libro, nel TOC dell'EPUB prodotto i titoli dei
**primi livelli** sono tradotti, mentre le voci dei **sottolivelli successivi**
restano nella lingua originale. Riguarda **solo le voci del TOC**, non il
contenuto dei capitoli (che è tradotto correttamente).

**Causa individuata.** In `noesis_ebook_translator/book.py`:

* `_parse_toc()` costruisce l'albero dei nodi **con i figli** (le voci annidate
  finiscono in `TocNode.nodes`), e `lib/element.py::get_toc_elements()` le
  raccoglie ricorsivamente → **vengono tradotte** (sono nella cache);
* ma `TocNode.write_back()` (riga ~64) riscrive **solo la propria** `title` e
  **non ricorre in `self.nodes`**, e `translate_epub()` chiama `write_back()`
  soltanto sui nodi di primo livello:

  ```python
  for node in toc_nodes:
      node.write_back()
  ```

  Quindi per le voci annidate la traduzione esiste ma non viene mai riportata
  sull'oggetto `ebooklib` → il titolo resta in originale.

**Fix proposto** (3 righe):

```python
    def write_back(self) -> None:
        if self.source is not None:
            try:
                self.source.title = self.title
            except Exception:
                pass          # pragma: no cover - defensive
        for child in self.nodes:      # <-- mancava
            child.write_back()
```

**Attenzione (repo gemello).** `book.py` è un modulo **condiviso** (inlineato in
`noesis-ebook-translator-engine`): dopo il fix va rilanciato
`tools/sync_from_desktop.py` nel repo gemello.

**Test da aggiungere.** Un EPUB con TOC a 3 livelli (esiste già
`tests/fixtures.py::build_rich_epub` con una `epub.Section` annidata, e il
corpus ha libri con TOC multilivello): dopo la traduzione, aprire l'EPUB di
output e verificare che **anche i titoli di secondo/terzo livello** contengano il
marcatore del motore fittizio (`IT<...>`).
