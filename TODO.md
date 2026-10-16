# TODO — cose da correggere prossimamente

_Al momento non ci sono problemi aperti._

## 1. ~~TOC: le voci dei sottolivelli non vengono tradotte nel file di output~~

**CORRETTO** (commit del fix + test di regressione
`tests/test_book.py::test_nested_toc_titles_are_translated_too`, che falliva
prima della correzione: l'output era `['IT<Introduction>', 'IT<Part Two>',
'Chapter 2', 'Chapter 3']`).

*Sintomo.* Traducendo un libro, nel TOC dell'EPUB prodotto i titoli dei
**primi livelli** erano tradotti, mentre le voci dei **sottolivelli successivi**
restavano nella lingua originale. Riguardava **solo le voci del TOC**, non il
contenuto dei capitoli (tradotto correttamente).

*Causa.* `TocNode.write_back()` riscriveva solo il proprio titolo e non ricorreva
in `self.nodes`.

*Fix.* La ricorsione in `write_back()` (modulo condiviso → sync del gemello).

