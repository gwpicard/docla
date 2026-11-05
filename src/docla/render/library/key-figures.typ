#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let key-figures(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let gutter = space(2)
  let width = (content-frame.w - gutter * calc.max(0, items.len() - 1)) / calc.max(1, items.len())
  let value-height = content-frame.h / 2
  let caption-height = content-frame.h - value-height
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    set block(above: 0pt, below: 0pt)
    grid(
      columns: (width,) * items.len(),
      column-gutter: gutter,
      ..items.enumerate().map(((i, item)) => {
        let citations = sec.at("citations", default: ()).at(i, default: ())
        fit-box("item", sec.id, width, content-frame.h, {
          fit-box("figure-value", sec.id, width, if item.head.len() > 6 { 0pt } else { value-height }, {
            set text(..type-style("slides", "figure"), fill: colour("accent"))
            el("figure-value", sec.id, item.head, width: width)
          })
          fit-box("figure-caption", sec.id, width, if item.body.len() > 60 { 0pt } else { caption-height }, {
            set text(..type-style("slides", "body"), fill: colour("ink"))
            el("figure-caption", sec.id, [#item.body #cite-keys(citations)], width: width)
          })
        })
      }),
    )
  })
})
