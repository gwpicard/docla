#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let comparison(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let gutter = space(2)
  let column-width = (content-frame.w - gutter * calc.max(0, items.len() - 1)) / calc.max(1, items.len())
  let row-height = content-frame.h / 5
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    set block(above: 0pt, below: 0pt)
    set text(..type-style("slides", "body"), fill: colour("ink"))
    grid(
      columns: (column-width,) * items.len(),
      column-gutter: gutter,
      ..items.enumerate().map(((i, item)) => {
        let citations = sec.at("citations", default: ()).at(i, default: ())
        fit-box("item", sec.id, column-width, content-frame.h, {
          fit-box("column-title", sec.id, column-width, row-height, el("column-title", sec.id, [#item.head #cite-keys(citations)], width: column-width))
          for row in item.sub {
            fit-box("row", sec.id, column-width, row-height, el("row", sec.id, row, width: column-width))
          }
        })
      }),
    )
  })
})
