# Darwin test corpus (Project Gutenberg)

These EPUB files are the **realistic end-to-end fixtures** used by the test
suite (`tests/test_darwin_corpus.py`). They are English-language books by
**Charles Darwin**, in the public domain (Project Gutenberg), downloaded in the
**`.epub.images`** edition so the corpus also exercises **illustration
handling** (inline `<img>` preservation).

| File | Project Gutenberg | Title | Images |
| --- | --- | --- | --- |
| `origin_of_species.epub` | [#1228](https://www.gutenberg.org/ebooks/1228) | *On the Origin of Species* (6th ed.) | 1 (cover) |
| `voyage_of_the_beagle.epub` | [#944](https://www.gutenberg.org/ebooks/944) | *The Voyage of the Beagle* | 15 (40 `<img>` in the text) |
| `descent_of_man.epub` | [#2300](https://www.gutenberg.org/ebooks/2300) | *The Descent of Man, and Selection in Relation to Sex* | 1 (cover) |

*The Travel of the Beagle* is the illustration-heavy fixture: its 15 images (40
`<img>` tags across the chapters) are the ones used to verify that **pictures
survive translation**.

**Source / licence:** Project Gutenberg (<https://www.gutenberg.org>). These texts
are in the **public domain** in the United States; the Project Gutenberg header
and licence are kept inside each file.

To (re)download or refresh them: `python tools/fetch_darwin_fixtures.py`.
