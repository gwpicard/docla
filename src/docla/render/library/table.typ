#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let table(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let data = sec.data
  let columns = data.at("columns", default: ())
  let rows = data.at("rows", default: ())
  let width = content-frame.w / calc.max(1, columns.len())
  let row-height = (content-frame.h - space(4)) / 11
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    set block(above: 0pt, below: 0pt)
    set text(..type-style("slides", "body"), fill: colour("ink"))
    fit-box("figure", sec.id, content-frame.w, row-height * 11, {
      el("figure", sec.id, {
        place(top + left, dy: row-height - space(1), line(length: content-frame.w, stroke: 0.5pt + colour("hairline")))
        grid(
          columns: (width,) * columns.len(),
          ..columns.map(cell => fit-box("table-header", sec.id, width, row-height, el("table-header", sec.id, text(weight: "bold", str(cell)), width: width))),
          ..rows.flatten().map(cell => fit-box("table-cell", sec.id, width, row-height, el("table-cell", sec.id, str(cell), width: width))),
        )
      }, width: content-frame.w)
    })
    if source-line != "" {
      fit-box("figure-source", sec.id, content-frame.w, space(4), el("figure-source", sec.id, source-line, width: content-frame.w))
    }
    for (i, item) in items.enumerate() {
      let citations = sec.at("citations", default: ()).at(i, default: ())
      fit-box("item", sec.id, content-frame.w, row-height, el("item", sec.id, [#item.body #cite-keys(citations)]))
    }
  })
})
