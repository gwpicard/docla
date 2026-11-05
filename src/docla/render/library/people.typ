#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let people(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let gutter = space(2)
  let width = (content-frame.w - 2 * gutter) / 3
  let height = content-frame.h / 2
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    set block(above: 0pt, below: 0pt)
    fit-box("body", sec.id, content-frame.w, content-frame.h, {
      place(top + left, dy: height - space(1), line(length: content-frame.w, stroke: 0.5pt + colour("hairline")))
      grid(
        columns: (width, width, width),
        column-gutter: gutter,
        ..items.enumerate().map(((i, item)) => {
          let citations = sec.at("citations", default: ()).at(i, default: ())
          fit-box("item", sec.id, width, height, {
            fit-box("name", sec.id, width, height / 2, {
              set text(..type-style("slides", "body"), fill: colour("ink"))
              el("name", sec.id, if calc.rem(i, 3) == 2 { align(right, item.head) } else { item.head }, width: width)
            })
            fit-box("role", sec.id, width, height / 2, {
              set text(..type-style("slides", "body"), fill: colour("ink"))
              el("role", sec.id, if calc.rem(i, 3) == 2 { align(right, [#item.body #cite-keys(citations)]) } else { [#item.body #cite-keys(citations)] }, width: width)
            })
          })
        }),
      )
    })
  })
})
