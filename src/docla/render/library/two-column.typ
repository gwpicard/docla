#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let two-column(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let entries = if items.len() > 0 { items } else { paragraphs }
  let midpoint = calc.ceil(entries.len() / 2)
  let column-width = (content-frame.w - space(4)) / 2
  let row-height = content-frame.h / 4
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    fit-box("body", sec.id, content-frame.w, content-frame.h, {
      set text(..type-style("slides", "body"), fill: colour("ink"))
      set block(above: 0pt, below: 0pt)
      grid(
        columns: (column-width, column-width),
        column-gutter: space(4),
        ..(0, 1).map(column => {
          let start = if column == 0 { 0 } else { midpoint }
          let end = if column == 0 { midpoint } else { entries.len() }
          for i in range(start, end) {
            let role = if items.len() > 0 { "item" } else { "paragraph" }
            let body = if items.len() > 0 {
              let citations = sec.at("citations", default: ()).at(i, default: ())
              [#entries.at(i).body #cite-keys(citations)]
            } else { entries.at(i) }
            fit-box(role, sec.id, column-width, row-height, el(role, sec.id, body, width: column-width))
          }
        }),
      )
    })
  })
})
